import hashlib
import hmac
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


def now_utc():
    return datetime.now(timezone.utc)


def iso(value):
    return value.isoformat(timespec='seconds')


def pin_hash(pin, salt):
    return hashlib.pbkdf2_hmac('sha256', pin.encode(), bytes.fromhex(salt), 200_000).hex()


def verify_pin(pin, salt, digest):
    return hmac.compare_digest(pin_hash(pin, salt), digest)


SCHEMAS = {
    'crm': '''
CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sites(id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, name TEXT NOT NULL, floors INTEGER, manager_phone TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contacts(id TEXT PRIMARY KEY, site_id TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, authorized INTEGER NOT NULL, pin_salt TEXT NOT NULL, pin_digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS service_cases(id TEXT PRIMARY KEY, call_id TEXT UNIQUE, machine TEXT, site_id TEXT, status TEXT NOT NULL, safety_flag TEXT, is_repeat_fault INTEGER, sla_due_at TEXT, report TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_case ON service_cases(machine) WHERE status IN ('dispatch_requested','dispatched','awaiting_approval','needs_dispatch');
''',
    'sap': '''
CREATE TABLE IF NOT EXISTS equipment(machine TEXT PRIMARY KEY, site_id TEXT NOT NULL, car TEXT NOT NULL, controller TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS machine_aliases(alias TEXT PRIMARY KEY, machine TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contract_terms(contract_id TEXT PRIMARY KEY, repeat_sla_hours INTEGER, parts_covered INTEGER, labor_covered INTEGER);
CREATE TABLE IF NOT EXISTS warranties(id TEXT PRIMARY KEY, machine TEXT NOT NULL, component TEXT, floor INTEGER, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, covers_labor INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS service_contracts(id TEXT PRIMARY KEY, site_id TEXT NOT NULL, tier TEXT NOT NULL, callback_window_days INTEGER NOT NULL, response_sla_hours INTEGER NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, callout_cents INTEGER NOT NULL, currency TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rates(id TEXT PRIMARY KEY, callout_cents INTEGER NOT NULL, currency TEXT NOT NULL);
''',
    'iot': '''
CREATE TABLE IF NOT EXISTS error_codes(code TEXT PRIMARY KEY, description TEXT NOT NULL, component TEXT);
CREATE TABLE IF NOT EXISTS error_events(id TEXT PRIMARY KEY, machine TEXT NOT NULL, code TEXT NOT NULL, occurred_at TEXT NOT NULL, floor INTEGER, car_position REAL, follow_up_event_id TEXT);
CREATE INDEX IF NOT EXISTS events_by_machine_time ON error_events(machine, occurred_at);
CREATE TABLE IF NOT EXISTS device_health(machine TEXT PRIMARY KEY, last_seen_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS monitoring_alerts(id TEXT PRIMARY KEY, machine TEXT NOT NULL, description TEXT NOT NULL, case_created INTEGER NOT NULL);
''',
    'field': '''
CREATE TABLE IF NOT EXISTS technicians(id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, controller TEXT NOT NULL, available INTEGER NOT NULL, travel_minutes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS work_orders(id TEXT PRIMARY KEY, case_id TEXT UNIQUE, machine TEXT NOT NULL, technician_id TEXT, status TEXT NOT NULL, completed_at TEXT, component_replaced TEXT, floor INTEGER, parent_work_order_id TEXT, estimated_arrival_at TEXT, notes TEXT);
''',
}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Store:
    """Local stand-ins for four enterprise systems. Attached DB writes are atomic.

    DELETE journals (not WAL) preserve SQLite's cross-file transaction semantics.
    External adapters need a saga/outbox instead of this local transaction.
    """
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def connect(self):
        db = sqlite3.connect(self.directory / 'runtime.sqlite', timeout=20, factory=ClosingConnection)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        for name in SCHEMAS:
            db.execute(f'ATTACH DATABASE ? AS {name}', (str(self.directory / f'{name}.sqlite'),))
        if (self.directory/'otis.sqlite').exists():
            db.execute('ATTACH DATABASE ? AS otis',(str(self.directory/'otis.sqlite'),))
        return db

    def initialize(self):
        for name, schema in SCHEMAS.items():
            with sqlite3.connect(self.directory / f'{name}.sqlite', factory=ClosingConnection) as db:
                db.executescript(schema)
        with self.connect() as db:
            db.executescript('''
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, caller TEXT NOT NULL, state TEXT NOT NULL, data TEXT NOT NULL, retries INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS webhook_replies(call_id TEXT NOT NULL, step TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(call_id, step));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, call_id TEXT, system TEXT NOT NULL, operation TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY, dedupe_key TEXT UNIQUE NOT NULL, recipient TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL, provider_id TEXT, error TEXT, created_at TEXT NOT NULL);
''')

    def seed(self, now=None):
        now = now or now_utc()
        with self.connect() as db:
            if db.execute('SELECT 1 FROM crm.customers').fetchone():
                return
            db.execute("INSERT INTO metadata VALUES ('synthetic', 'true')")
            db.execute("INSERT INTO crm.customers VALUES ('C1','Crestline Properties')")
            db.execute("INSERT INTO crm.sites VALUES ('S1','C1','Harbor Point Tower',12,'+15550100100')")
            salt = os.urandom(16).hex()
            db.execute('INSERT INTO crm.contacts VALUES (?,?,?,?,?,?,?)',
                       ('P1', 'S1', 'Priya', '+15550100100', 1, salt, pin_hash('246810', salt)))
            for machine, car in [('1001','A'), ('1002','B'), ('1003','C')]:
                db.execute('INSERT INTO sap.equipment VALUES (?,?,?,?)', (machine,'S1',car,'CTRL-X12'))
                db.execute('INSERT INTO sap.warranties VALUES (?,?,?,?,?,?,?)',
                           ('UNIT-'+machine,machine,None,None,iso(now-timedelta(days=2000)),iso(now-timedelta(days=730)),1))
                db.execute('INSERT INTO iot.device_health VALUES (?,?)', (machine,iso(now)))
            db.execute('INSERT INTO sap.warranties VALUES (?,?,?,?,?,?,?)',
                       ('PART-7','1002','landing_door_lock_contact',7,iso(now-timedelta(days=19)),iso(now+timedelta(days=71)),0))
            db.execute('INSERT INTO sap.service_contracts VALUES (?,?,?,?,?,?,?,?,?)',
                       ('SC1','S1','comprehensive',30,4,iso(now-timedelta(days=200)),iso(now+timedelta(days=165)),25000,'USD'))
            db.execute("INSERT INTO sap.rates VALUES ('standard',25000,'USD')")
            db.execute("INSERT INTO iot.error_codes VALUES ('DL17','Door lock circuit interrupted during travel','landing_door_lock_contact')")
            db.execute("INSERT INTO iot.error_codes VALUES ('RL01','Re-level and door cycle',NULL)")
            for i in range(14):
                occurred = now-timedelta(hours=1+i*10)
                floor = 7 if i < 12 else 6
                db.execute('INSERT INTO iot.error_events VALUES (?,?,?,?,?,?,?)',
                           (f'FAULT-{i}','1002','DL17',iso(occurred),floor,floor-.2,f'FOLLOW-{i}'))
                db.execute('INSERT INTO iot.error_events VALUES (?,?,?,?,?,?,?)',
                           (f'FOLLOW-{i}','1002','RL01',iso(occurred+timedelta(seconds=12)),floor,float(floor),None))
            db.execute("INSERT INTO iot.monitoring_alerts VALUES ('MON-1','1002','Repeated door circuit interruption',0)")
            db.execute("INSERT INTO field.technicians VALUES ('T1','Ravi','+15550100200','CTRL-X12',1,20)")
            db.execute("INSERT INTO field.technicians VALUES ('T2','Maya','+15550100300','CTRL-X12',1,45)")
            db.execute('INSERT INTO field.work_orders VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       ('WO-ORIGINAL',None,'1002','T1','completed',iso(now-timedelta(days=19)),
                        'landing_door_lock_contact',7,None,None,'Replaced floor 7 landing door lock contact'))

    @staticmethod
    def notify(db, key, recipient, body, now):
        db.execute('INSERT OR IGNORE INTO outbox(dedupe_key,recipient,body,status,created_at) VALUES (?,?,?,?,?)',
                   (key,recipient,body,'pending',iso(now)))

    def snapshot(self):
        with self.connect() as db:
            snapshot = {name:[dict(row) for row in db.execute(query)] for name,query in {
                'cases':'SELECT * FROM crm.service_cases ORDER BY created_at DESC',
                'work_orders':'SELECT * FROM field.work_orders',
                'notifications':'SELECT * FROM outbox',
                'routing_trace':'SELECT * FROM audit ORDER BY id',
            }.items()}
            snapshot['calls']=[dict(row) for row in db.execute('SELECT * FROM calls ORDER BY created_at DESC')]
            tables={
                'crm':['customers','sites','contacts','service_cases'],
                'sap':['equipment','machine_aliases','contract_terms','warranties','service_contracts','rates'],
                'iot':['error_codes','error_events','device_health','monitoring_alerts'],
                'field':['technicians','work_orders'],
            }
            sources={}
            for schema,names in tables.items():
                sources[schema]={}
                for table in names:
                    query=('SELECT id,site_id,name,phone,authorized FROM crm.contacts' if table=='contacts'
                           else f'SELECT * FROM {schema}.{table}')
                    try:
                        sources[schema][table]=[dict(row) for row in db.execute(query)]
                    except sqlite3.OperationalError:
                        pass
            snapshot['sources']=sources
            return snapshot
