import json
import uuid
from collections import Counter
from datetime import datetime, timedelta
from .store import Store, iso, now_utc
from .router import Router


class NeedsHuman(Exception):
    def __init__(self,message,safety_flag=None):
        super().__init__(message)
        self.safety_flag=safety_flag


def new_id(prefix):
    return prefix + '-' + uuid.uuid4().hex[:10].upper()


class Service:
    def __init__(self, store, config, clock=now_utc):
        self.store, self.config, self.clock = store, config, clock

    def investigate(self, db, call_id, data):
        now = self.clock()
        reference=db.execute("SELECT value FROM metadata WHERE key='demo_as_of'").fetchone()
        if self.config.mode=='demo' and reference:
            now=datetime.fromisoformat(reference[0])
        has_otis=bool(db.execute("SELECT 1 FROM metadata WHERE key='source' AND value='otis_hackathon_crm'").fetchone())
        plan = data['plan']
        def route(operation):
            Router.record(db, call_id, plan, operation, iso(now))
        route('equipment')
        equipment = db.execute('SELECT * FROM sap.equipment WHERE machine=? AND site_id=?',
                               (data['machine'],data['site_id'])).fetchone()
        if not equipment:
            raise NeedsHuman('Machine could not be verified for this site')
        route('telemetry')
        health = db.execute('SELECT last_seen_at FROM iot.device_health WHERE machine=?', (equipment['machine'],)).fetchone()
        if not health or not timedelta(0) <= now-datetime.fromisoformat(health[0]) <= timedelta(hours=24):
            raise NeedsHuman('Telemetry is missing or stale; dispatcher must review')
        if has_otis:
            critical=db.execute("SELECT 1 FROM iot.error_events WHERE machine=? AND code IN ('ENT-900','SAF-510') AND occurred_at>=? AND occurred_at<=?",(equipment['machine'],iso(now-timedelta(minutes=30)),iso(now))).fetchone()
            if critical:
                raise NeedsHuman('Recent critical telemetry indicates possible entrapment or a safety stop; immediate dispatcher review is required','critical_telemetry')
        events = db.execute('''SELECT e.*, c.description,c.component, f.code AS follow_up_code
            FROM iot.error_events e JOIN iot.error_codes c ON c.code=e.code
            LEFT JOIN iot.error_events f ON e.follow_up_event_id=f.id AND e.machine=f.machine
            WHERE e.machine=? AND e.occurred_at>=? AND e.occurred_at<=? AND c.component IS NOT NULL
            ORDER BY e.occurred_at DESC''', (equipment['machine'],iso(now-timedelta(days=7)),iso(now))).fetchall()
        component = Counter(e['component'] for e in events).most_common(1)[0][0] if events else None
        relevant = [e for e in events if e['component']==component]
        floor = Counter(e['floor'] for e in relevant).most_common(1)[0][0] if relevant else None
        route('history')
        previous = db.execute('''SELECT * FROM field.work_orders WHERE machine=? AND status='completed'
            AND component_replaced=? AND floor IS ? AND completed_at<=? ORDER BY completed_at DESC LIMIT 1''',
            (equipment['machine'],component,floor,iso(now))).fetchone() if component else None
        route('coverage')
        contract = db.execute('SELECT * FROM sap.service_contracts WHERE site_id=? AND starts_at<=? AND ends_at>=? ORDER BY ends_at DESC LIMIT 1',
                              (equipment['site_id'],iso(now),iso(now))).fetchone()
        warranties = db.execute('SELECT * FROM sap.warranties WHERE machine=? AND starts_at<=? AND ends_at>=?',
                                (equipment['machine'],iso(now),iso(now))).fetchall()
        applicable = [w for w in warranties if w['component'] is None or (w['component']==component and w['floor']==floor)]
        full_cover = bool(contract and contract['tier']=='comprehensive') or any(w['covers_labor'] for w in applicable)
        part_cover = bool(applicable)
        days_since_repair = (now-datetime.fromisoformat(previous['completed_at'])).days if previous else None
        repeat = bool(previous and days_since_repair <= (contract['callback_window_days'] if contract else 30))
        terms=db.execute('SELECT * FROM sap.contract_terms WHERE contract_id=?',(contract['id'],)).fetchone() if contract else None
        if terms:
            full_cover=bool(terms['parts_covered'] and terms['labor_covered']) or any(w['covers_labor'] for w in applicable)
        rate = db.execute("SELECT * FROM sap.rates WHERE id='standard'").fetchone()
        if not full_cover and not rate:
            raise NeedsHuman('No approved callout price is available')
        amount = 0 if full_cover else (contract['callout_cents'] if contract else rate['callout_cents'])
        currency = contract['currency'] if contract else (rate['currency'] if rate else 'USD')
        route('duplicate')
        existing = db.execute("SELECT * FROM crm.service_cases WHERE machine=? AND status IN ('dispatch_requested','dispatched','awaiting_approval','needs_dispatch')", (equipment['machine'],)).fetchone()
        if existing:
            # A second call must not silently approve or dispatch an existing billable case.
            return {'existing':True,'case_id':existing['id'],'status':existing['status'],
                    'summary':f"There is already an active case, {existing['id']}. I will connect you to the dispatcher for its status."}
        route('dispatch')
        technicians = [dict(t) for t in db.execute('SELECT * FROM field.technicians WHERE available=1 ORDER BY travel_minutes') if equipment['controller'] in t['controller'].split(',')]
        if has_otis:
            from .otis_import import travel_minutes
            site=db.execute('SELECT * FROM otis.sites WHERE site_id=?',(equipment['site_id'],)).fetchone()
            regional=[]
            for tech in technicians:
                source_tech=db.execute('SELECT * FROM otis.technicians WHERE technician_id=?',(tech['id'],)).fetchone()
                if source_tech and source_tech['service_region']==site['service_region']:
                    tech['travel_minutes']=travel_minutes(source_tech['current_lat'],source_tech['current_lon'],site['latitude'],site['longitude'])
                    regional.append(tech)
            technicians=sorted(regional,key=lambda t:t['travel_minutes'])
        original = previous['technician_id'] if previous else None
        sla_hours = contract['response_sla_hours'] if contract else None
        if repeat and terms:
            sla_hours=terms['repeat_sla_hours']
        eligible = [t for t in technicians if not sla_hours or t['travel_minutes'] <= sla_hours*60]
        technician = next((t for t in eligible if t['id']==original), eligible[0] if eligible else None)
        alert = db.execute('SELECT * FROM iot.monitoring_alerts WHERE machine=?', (equipment['machine'],)).fetchone()
        report = {'case_id':new_id('CS'),'machine':equipment['machine'],'car':equipment['car'],
                  'site_id':equipment['site_id'], 'caller_name':data['name'], 'caller_phone':data['caller'],
                  'symptom':data['symptom'], 'event_count':len(relevant),'floor':floor,'suspect_component':component,
                  'follow_up_count':sum(e['follow_up_code'] in ('RL01','REL-210') for e in relevant),
                  'event_ids':[e['id'] for e in relevant], 'previous_work_order_id':previous['id'] if previous else None,
                  'repair_date':previous['completed_at'][:10] if previous else None,'is_repeat_fault':repeat,
                  'unit_warranty_active':any(w['component'] is None for w in warranties),
                  'component_warranty_active':any(w['component'] is not None for w in applicable),
                  'contract_tier':contract['tier'] if contract else None,
                  'covered':full_cover,'parts_covered':part_cover,'callout_cents':amount,'currency':currency,
                  'sla_due_at':iso(self.clock()+timedelta(hours=sla_hours)) if sla_hours else None,
                  'technician':dict(technician) if technician else None,
                  'estimated_arrival_at':None, 'monitoring_flagged':bool(alert),
                  'status':'awaiting_approval' if not full_cover else 'ready',
                  'priority':'high' if events or 'stopp' in data['symptom'].lower() else 'normal'}
        if relevant:
            report['finding'] = (f"Car {equipment['car']} has {len(relevant)} matching fault events in the last seven days, "
                                 f"mostly near floor {floor}. {relevant[0]['description']}.")
            if previous:
                report['finding'] += f" This may relate to the component repaired on {report['repair_date']}; a technician must confirm the cause."
        else:
            report['finding'] = 'No matching fault events were found in current telemetry. This does not rule out a fault or establish its cause.'
            if has_otis:
                reversals=db.execute("SELECT COUNT(*) FROM iot.error_events WHERE machine=? AND code IN ('DPD-305','DPD-306') AND occurred_at>=? AND occurred_at<=?",(equipment['machine'],iso(now-timedelta(days=7)),iso(now))).fetchone()[0]
                if reversals:
                    report['finding']+=f' There are {reversals} door-reversal or nudging events. An obstruction or door sensor issue is possible; a visit is still needed.'
                    report['door_protection_events']=reversals
        if has_otis:
            report['data_as_of']=iso(now)
            report['eta_basis']='Demo estimate from source coordinates: 15-minute preparation plus distance at 25 km/h; not live traffic'
            route('compliance')
            inspection=db.execute('SELECT * FROM otis.inspections WHERE equipment_id=? ORDER BY inspection_date DESC LIMIT 1',(equipment['machine'],)).fetchone()
            report['inspection']=dict(inspection) if inspection else None
            if inspection and (inspection['result']=='Fail' or inspection['next_due_date']<now.date().isoformat()):
                report['inspection_requires_review']=True
            if any(word in data['symptom'].lower() for word in ('rooftop','roof top','badge','floor 18')):
                route('access')
                self.rooftop_evidence(db,report,equipment,now)
        report['billing'] = ('This visit is covered at no charge.' if full_cover else
            f"The callout is {currency} {amount/100:.2f}. Additional repairs require a separate estimate and approval."
            + (' An applicable parts warranty exists, but does not cover all visit costs.' if part_cover else ''))
        return report

    def rooftop_evidence(self,db,report,equipment,now):
        """Compare actual access rights, site-wide attempts and programming history."""
        from .otis_import import utc
        rights=db.execute("SELECT * FROM otis.access_credentials WHERE site_id=? AND status='Active'",(equipment['site_id'],)).fetchall()
        allowed=[r['credential_id'] for r in rights if '18' in r['authorized_floors'].split(',') or r['authorized_floors']=='ALL']
        attempted=db.execute("""SELECT e.* FROM otis.error_events e JOIN otis.equipment q USING(equipment_id)
            WHERE q.site_id=? AND e.floor=18 AND e.error_code IN ('SEC-960','SEC-961') ORDER BY event_ts""",(equipment['site_id'],)).fetchall()
        rejected=[r for r in attempted if r['error_code']=='SEC-960' and r['credential_id'] in allowed and utc(r['event_ts'])<=iso(now)]
        repairs=db.execute("""SELECT w.* FROM otis.work_orders w JOIN otis.equipment q USING(equipment_id)
            WHERE q.site_id=? AND w.work_type='Programming' AND w.status='Completed' ORDER BY w.completed_at DESC""",(equipment['site_id'],)).fetchall()
        repair=next((r for r in repairs if utc(r['completed_at'])<=iso(now)),None)
        if not rejected or not repair: return
        accepted_before=[r for r in attempted if r['error_code']=='SEC-961' and r['event_ts']<repair['completed_at']]
        rejected_after=[r for r in rejected if r['event_ts']>repair['completed_at']]
        accepted_after=[r for r in attempted if r['error_code']=='SEC-961' and repair['completed_at']<r['event_ts'] and utc(r['event_ts'])<=iso(now)]
        if not accepted_before or not rejected_after or accepted_after: return
        report.update(floor=18,suspect_component='floor_security_table',previous_work_order_id=repair['work_order_id'],
                      is_repeat_fault=True,repair_date=repair['completed_at'][:10],access_rejections=len(rejected_after),
                      access_authorized_badges=len(allowed),priority='high')
        report['finding']=(f"Floor 18 is secured. Authorized badges were accepted before the floor-security update on {repair['completed_at'][:10]}, "
            f"but {len(rejected_after)} subsequent attempts by authorized badge holders were rejected. This suggests a floor-security configuration issue related to work order {repair['work_order_id']}. "
            'A technician must verify the mapping. The building security desk may be able to arrange an authorized escort; I have not booked one.')
        manager=db.execute('SELECT manager_phone FROM crm.sites WHERE id=?',(equipment['site_id'],)).fetchone()
        report['manager_phone']=manager[0] if manager else None
        contract=db.execute('''SELECT c.*,t.repeat_sla_hours FROM sap.service_contracts c
            JOIN sap.contract_terms t ON t.contract_id=c.id WHERE c.site_id=? AND c.starts_at<=? AND c.ends_at>=?''',
            (equipment['site_id'],iso(now),iso(now))).fetchone()
        if contract:
            report['is_repeat_fault']=(now-datetime.fromisoformat(utc(repair['completed_at']))).days<=contract['callback_window_days']
            hours=contract['repeat_sla_hours'] if report['is_repeat_fault'] else contract['response_sla_hours']
            report['sla_due_at']=iso(self.clock()+timedelta(hours=hours))

    def save_and_dispatch(self, db, call_id, report, approved=False):
        now = self.clock()
        if report.get('existing'):
            return report
        if not report['covered'] and not approved:
            status = 'awaiting_approval'
        else:
            status = 'dispatch_requested' if report['technician'] else 'needs_dispatch'
        report['status'] = status
        report['summary'] = report['finding'] + ' ' + report['billing']
        if status == 'dispatch_requested':
            tech = report['technician']
            # Claim technician inside the same transaction as case/WO/outbox creation.
            if not db.execute('UPDATE field.technicians SET available=0 WHERE id=? AND available=1', (tech['id'],)).rowcount:
                report['technician'] = None
                report['status'] = status = 'needs_dispatch'
            else:
                report['estimated_arrival_at'] = iso(now+timedelta(minutes=tech['travel_minutes']))
                report['summary'] += (f" I have requested {tech['name']}. The provisional travel estimate is {tech['travel_minutes']} minutes "
                                      'after acceptance. The dispatcher must confirm the arrival time.')
        if status == 'needs_dispatch':
            report['summary'] += ' The dispatcher must assign a technician and confirm the arrival time.'
        if status != 'awaiting_approval':
            report['summary'] += f" Your case number is {report['case_id']}. I cannot confirm this elevator is safe to use; please follow your building's safety procedure and speak with the dispatcher."
        db.execute('''INSERT INTO crm.service_cases VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET status=excluded.status, report=excluded.report''',
            (report['case_id'],call_id,report['machine'],report['site_id'],status,None,int(report['is_repeat_fault']),
             report['sla_due_at'],json.dumps(report),iso(now)))
        if status != 'awaiting_approval':
            db.execute('INSERT OR IGNORE INTO field.work_orders VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (new_id('WO'),report['case_id'],report['machine'],report['technician']['id'] if report['technician'] else None,
                 status,None,None,report['floor'],report['previous_work_order_id'],report['estimated_arrival_at'],
                 f"Suspect component: {report['suspect_component']}. {report['finding']}"))
            body = f"{report['priority'].upper()} {report['case_id']} | Machine {report['machine']} | {report['summary']}"
            Store.notify(db,report['case_id']+':dispatcher',self.config.dispatcher_phone or 'DEMO_DISPATCHER',body,now)
            if report['technician']:
                Store.notify(db,report['case_id']+':technician',report['technician']['phone'],body,now)
            if report.get('manager_phone'):
                Store.notify(db,report['case_id']+':manager',report['manager_phone'],body,now)
        return report

    def accept(self, case_id, eta_minutes):
        if type(eta_minutes) is not int or not 1 <= eta_minutes <= 1440:
            raise ValueError('eta_minutes must be an integer between 1 and 1440')
        now = self.clock()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM crm.service_cases WHERE id=?',(case_id,)).fetchone()
            if not row:
                raise ValueError('Unknown case')
            report = json.loads(row['report'])
            if row['status']=='dispatched':
                return report
            if row['status']!='dispatch_requested':
                raise ValueError('Case has no requested technician assignment')
            report['status']='dispatched'
            report['simulated_acceptance']=self.config.mode=='demo'
            report['estimated_arrival_at']=iso(now+timedelta(minutes=eta_minutes))
            report['summary'] = (f"Case {case_id}: {report['technician']['name']} has accepted the visit for machine {report['machine']}. "
                                 f"Estimated arrival in {eta_minutes} minutes. This is an estimate; we will notify you if it changes.")
            db.execute("UPDATE crm.service_cases SET status='dispatched',report=? WHERE id=?",(json.dumps(report),case_id))
            db.execute("UPDATE field.work_orders SET status='dispatched',estimated_arrival_at=? WHERE case_id=?",(report['estimated_arrival_at'],case_id))
            call = db.execute('SELECT data FROM calls WHERE id=?',(row['call_id'],)).fetchone()
            if call and json.loads(call[0]).get('notification_consent'):
                Store.notify(db,case_id+':confirmed_eta',report['caller_phone'],report['summary'],now)
            return report

    def accept_demo_pending(self):
        """Explicitly simulate Ravi's acceptance only for finished demo calls."""
        if self.config.mode!='demo' or not self.config.auto_accept_demo:
            return
        with self.store.connect() as db:
            synthetic=db.execute("SELECT 1 FROM metadata WHERE key='synthetic' AND value='true'").fetchone()
            if not synthetic:
                return
            rows=db.execute("""SELECT c.id,c.report FROM crm.service_cases c JOIN calls ON calls.id=c.call_id
                WHERE c.status='dispatch_requested' AND calls.state='done' AND c.safety_flag IS NULL""").fetchall()
        for row in rows:
            report=json.loads(row['report'])
            self.accept(row['id'],report['technician']['travel_minutes'])
