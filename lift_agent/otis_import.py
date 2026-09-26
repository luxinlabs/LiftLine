"""Import the supplied Otis fixture without modifying its original source files."""
import json
import math
import os
import re
import shutil
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from .store import Store,iso,pin_hash

AS_OF=datetime(2026,9,26,10,15,tzinfo=ZoneInfo('America/Los_Angeles'))


def utc(value,end=False):
    if not value: return None
    dt=datetime.fromisoformat(value)
    if len(value)==10 and end: dt=dt.replace(hour=23,minute=59,second=59)
    return iso(dt.replace(tzinfo=ZoneInfo('America/Los_Angeles')).astimezone(timezone.utc))


def phone(value):
    return '+'+re.sub(r'\D','',value)


def component(value):
    text=(value or '').lower()
    if 'landing door lock' in text: return 'landing_door_lock_contact'
    if 'floor-security' in text: return 'floor_security_table'
    if 'hydraulic' in text: return 'hydraulic_control_valve'
    return re.sub('[^a-z0-9]+','_',text).strip('_') or None


def travel_minutes(lat,lon,site_lat,site_lon):
    # Transparent demo estimate: straight-line distance × 1.4 road factor, 25 km/h, 15 min prep.
    phi1,phi2=math.radians(lat),math.radians(site_lat)
    delta_phi=phi2-phi1; delta_lambda=math.radians(site_lon-lon)
    a=math.sin(delta_phi/2)**2+math.cos(phi1)*math.cos(phi2)*math.sin(delta_lambda/2)**2
    km=6371*2*math.atan2(math.sqrt(a),math.sqrt(1-a))
    return int(math.ceil((15+km*1.4/25*60)/5)*5)


def import_otis(source,directory):
    store=Store(directory); store.initialize()
    with store.connect() as db:
        if db.execute('SELECT COUNT(*) FROM crm.customers').fetchone()[0]:
            raise ValueError('Import requires an empty data directory; existing records are preserved')
    shutil.copy2(source,Path(directory)/'otis.sqlite')
    source_db=sqlite3.connect(source); source_db.row_factory=sqlite3.Row
    tables={r[0]:[dict(row) for row in source_db.execute('SELECT * FROM '+r[0])]
            for r in source_db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    source_db.close()
    work={r['work_order_id']:r for r in tables['work_orders']}
    with store.connect() as db:
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('synthetic','true')")
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('source','otis_hackathon_crm')")
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('demo_as_of',?)",(iso(AS_OF.astimezone(timezone.utc)),))
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('demo_contact_phone','+14155550142')")
        for r in tables['customers']:
            db.execute('INSERT INTO crm.customers VALUES (?,?)',(r['customer_id'],r['name']))
        for r in tables['sites']:
            manager=next((c for c in tables['contacts'] if c['site_id']==r['site_id'] and c['status']=='Active' and c['is_authorized_for_service']),None)
            db.execute('INSERT INTO crm.sites VALUES (?,?,?,?,?)',(r['site_id'],r['customer_id'],r['name'],r['floors'],phone(manager['phone']) if manager else 'DEMO_DISPATCHER'))
        for r in tables['contacts']:
            salt=os.urandom(16).hex()
            db.execute('INSERT INTO crm.contacts VALUES (?,?,?,?,?,?,?)',(r['contact_id'],r['site_id'] or '',
                r['first_name']+' '+r['last_name'],phone(r['phone']),int(r['status']=='Active' and bool(r['is_authorized_for_service'])),salt,pin_hash('246810',salt)))
        for r in tables['equipment']:
            db.execute('INSERT INTO sap.equipment VALUES (?,?,?,?)',(r['equipment_id'],r['site_id'],r['car_label'].removeprefix('Car '),r['controller_model']))
            for alias in (r['equipment_id'],r['equipment_id'].replace('-',''),r['equipment_id'].split('-')[-1],r['sap_equipment_no']):
                db.execute('INSERT INTO sap.machine_aliases VALUES (?,?)',(alias,r['equipment_id']))
            # Fixture has no heartbeat table. This is an explicit synthetic heartbeat at fixture time.
            db.execute('INSERT INTO iot.device_health VALUES (?,?)',(r['equipment_id'],iso(AS_OF.astimezone(timezone.utc))))
        for r in tables['service_contracts']:
            db.execute('INSERT INTO sap.service_contracts VALUES (?,?,?,?,?,?,?,?,?)',(r['contract_id'],r['site_id'],r['tier'].lower(),r['callback_window_days'],r['response_sla_hours'],utc(r['start_date']),utc(r['end_date'],True),round(r['non_contract_callout_usd']*100),'USD'))
            db.execute('INSERT INTO sap.contract_terms VALUES (?,?,?,?)',(r['contract_id'],r['repeat_fault_sla_hours'],r['parts_covered'],r['labor_covered']))
        db.execute("INSERT INTO sap.rates VALUES ('standard',39500,'USD')")
        for r in tables['warranties']:
            wo=work.get(r['work_order_id'])
            db.execute('INSERT INTO sap.warranties VALUES (?,?,?,?,?,?,?)',(r['warranty_id'],r['equipment_id'],
                None if r['coverage_level']=='Unit' else component(wo['component'] if wo else r['component']),
                wo['floor'] if wo else None,utc(r['start_date']),utc(r['end_date'],True),int('labor' in r['terms'].lower())))
        for r in tables['error_code_catalog']:
            comp=None
            if r['error_code']=='DLC-101': comp='landing_door_lock_contact'
            elif r['error_code'] in ('HYD-801','LEV-221'): comp='hydraulic_control_valve'
            elif r['severity'] in ('Medium','High','Critical') and r['error_code'] not in ('ALM-910',): comp=component(r['category'])
            db.execute('INSERT INTO iot.error_codes VALUES (?,?,?)',(r['error_code'],r['description'],comp))
        for r in tables['error_events']:
            db.execute('INSERT INTO iot.error_events VALUES (?,?,?,?,?,?,?)',(r['event_id'],r['equipment_id'],r['error_code'],utc(r['event_ts']),r['floor'],r['car_position'],r['related_event_id']))
        # This alert is derived from the supplied catalog threshold, not invented as an upstream case.
        db.execute("INSERT INTO iot.monitoring_alerts VALUES ('DERIVED-DLC','EQ-30002','Derived threshold: 14 DLC-101 events exceeds catalog threshold 10; no active case',0)")
        for r in tables['technicians']:
            db.execute('INSERT INTO field.technicians VALUES (?,?,?,?,?,?)',(r['technician_id'],r['full_name'],phone(r['phone']),r['certifications'],int(r['shift_status']=='Available'),travel_minutes(r['current_lat'],r['current_lon'],37.7913,-122.3931)))
        for r in tables['service_cases']:
            status={'Open':'needs_dispatch','In Progress':'dispatched','Closed':'closed','Resolved':'resolved'}[r['status']]
            db.execute('INSERT INTO crm.service_cases VALUES (?,?,?,?,?,?,?,?,?,?)',(r['case_id'],None,r['equipment_id'],r['site_id'],status,'safety' if r['safety_flag'] else None,r['is_repeat_fault'],utc(r['sla_due_at']),json.dumps({'source_record':r}),utc(r['opened_at'])))
        for r in tables['work_orders']:
            db.execute('INSERT INTO field.work_orders VALUES (?,?,?,?,?,?,?,?,?,?,?)',(r['work_order_id'],r['case_id'],r['equipment_id'],r['technician_id'],r['status'].lower(),utc(r['completed_at']),component(r['component']),r['floor'],r['parent_work_order_id'],None,r['action_taken']))
    return {name:len(rows) for name,rows in tables.items()}
