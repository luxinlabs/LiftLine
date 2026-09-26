import json
import re
from datetime import timedelta
from xml.etree.ElementTree import Element, SubElement, tostring
from .router import Router, RoutingUnavailable
from .service import Service, NeedsHuman, new_id
from .store import Store, iso, now_utc, verify_pin

PROMPTS = {
    'safety':'You are speaking with LiftLine, an automated service assistant. Is anyone trapped, injured, or in immediate danger? Press 1 for yes, 2 for no, or 3 if you are unsure.',
    'machine':'Please say the machine number, or enter it on your keypad followed by pound. If you do not know it, press 0 for a dispatcher.',
    'pin':'Please enter your six digit service contact PIN. If you are not an authorized contact, press 0 to log a report.',
    'symptom':'Please describe what the elevator is doing.',
    'consent':'May we send your case report and arrival updates to this registered phone number using Photon messaging? Press 1 for yes, or 2 for no.',
}


def xml_response(message, step=None, input_kind='dtmf', dial=None, hints=None):
    root = Element('Response')
    if step is not None:
        attrs=dict(input=input_kind,action=f'/voice?step={step}',method='POST',
                   timeout='7',speechTimeout='auto',actionOnEmptyResult='true',finishOnKey='#')
        if hints:
            attrs['hints']=hints
        gather = SubElement(root,'Gather',**attrs)
        SubElement(gather,'Say').text = message
    else:
        SubElement(root,'Say').text = message
        if dial:
            transfer = SubElement(root,'Dial',timeout='25',action='/voice/transfer-result',method='POST')
            SubElement(transfer,'Number').text = dial
        else:
            SubElement(root,'Hangup')
    return tostring(root,encoding='unicode')


class VoiceAgent:
    def __init__(self, store, config, router=None, clock=now_utc):
        self.store, self.config, self.clock = store, config, clock
        self.router = router or Router(live=config.mode=='live' or config.jev_enabled)
        self.service = Service(store,config,clock)

    def handle(self, call_id, caller, step, params):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', call_id):
            raise ValueError('Invalid call identifier')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cached = db.execute('SELECT response FROM webhook_replies WHERE call_id=? AND step=?',(call_id,str(step))).fetchone()
            row = db.execute('SELECT * FROM calls WHERE id=?',(call_id,)).fetchone()
            if row and row['caller'] != caller:
                raise ValueError('Caller does not match session')
            if cached:
                return cached[0]
            if not row:
                if step != 0:
                    raise ValueError('Unknown call session')
                data={'next_step':1,'caller':caller}
                db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?)',(call_id,caller,'safety',json.dumps(data),0,iso(self.clock())))
                prefix='This is an elevator service demonstration using sample data. ' if self.config.mode=='demo' else ''
                result=xml_response(prefix+PROMPTS['safety'],1)
            else:
                data=json.loads(row['data'])
                if step != data['next_step']:
                    raise ValueError('Out of sequence call step')
                data['next_step'] += 1
                result=self.advance(db,row,data,params)
            db.execute('INSERT INTO webhook_replies VALUES (?,?,?)',(call_id,str(step),result))
            return result

    def advance(self,db,row,data,params):
        call_id,state=row['id'],row['state']
        digits=params.get('Digits','').strip()
        speech=params.get('SpeechResult','').strip()[:2000]
        now=self.clock()

        def save(new_state, retries=0):
            db.execute('UPDATE calls SET state=?, data=?, retries=? WHERE id=?',(new_state,json.dumps(data),retries,call_id))

        def ask(new_state, message=None, retry=False):
            retries=row['retries']+1 if retry else 0
            if retries>=3:
                return handoff('I could not confirm the information. A dispatcher will help you.', 'uncertain')
            save(new_state,retries)
            kind='speech dtmf' if new_state in ('machine','confirm_machine','symptom') else 'dtmf'
            hints='zero,one,two,three,four,five,six,seven,eight,nine,E,Q,dash' if new_state=='machine' else None
            return xml_response(message or PROMPTS[new_state],data['next_step'],kind,hints=hints)

        def handoff(message, flag=None):
            existing=db.execute('SELECT id FROM crm.service_cases WHERE call_id=?',(call_id,)).fetchone()
            case_id=existing[0] if existing else new_id('CS')
            if existing:
                db.execute('UPDATE crm.service_cases SET safety_flag=COALESCE(?,safety_flag) WHERE id=?',(flag,case_id))
            else:
                db.execute('INSERT INTO crm.service_cases VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (case_id,call_id,data.get('machine'),data.get('site_id'),'human_review',flag,0,None,
                     json.dumps({'reason':message,'caller':row['caller'],'symptom':data.get('symptom')}),iso(now)))
            Store.notify(db,case_id+':handoff',self.config.dispatcher_phone or 'DEMO_DISPATCHER',
                         f"{case_id}: {message} Caller {row['caller']}. Machine {data.get('machine','unknown')}.",now)
            save('done')
            if self.config.dispatcher_phone and self.config.mode=='live':
                return xml_response(message+' I am connecting you to a human dispatcher now.',dial=self.config.dispatcher_phone)
            return xml_response(message+' Demo handoff recorded. A live dispatcher number is not configured.')

        # Any danger language after triage interrupts lookup. Conservative, including ambiguous negation.
        if state != 'safety' and re.search(r'\b(trapped|injur\w*|hurt|fire|smoke|emergency|stuck inside|cannot get out|can.t get out)\b',speech,re.I):
            return handoff('There may be an immediate safety concern. Do not attempt a rescue or force the doors.','possible_emergency')
        if state=='safety':
            if digits in ('1','3'):
                return handoff('Safety comes first. Do not attempt a rescue or force the doors.','entrapment_or_injury' if digits=='1' else 'uncertain')
            if digits!='2':
                return ask('safety',retry=True)
            data['safety_cleared']=True
            return ask('machine')
        if state=='machine':
            if digits=='0':
                return handoff('A dispatcher will help identify the machine.')
            candidate=(digits or re.sub(r'[\s-]','',speech)).upper()
            if not re.fullmatch(r'(?:EQ|E)?\d{1,12}',candidate):
                return ask('machine','Please enter the numeric machine number on the keypad, followed by pound.',True)
            alias=db.execute('SELECT machine FROM sap.machine_aliases WHERE alias=?',(candidate,)).fetchone()
            if alias: candidate=alias[0]
            data['machine']=candidate
            return ask('confirm_machine',f'I heard machine {" ".join(candidate)}. Press 1 to confirm, or 2 to try again.')
        if state=='confirm_machine':
            if digits=='2':
                return ask('machine')
            if digits!='1':
                return ask('confirm_machine','Press 1 to confirm the machine number, or 2 to try again.',True)
            return ask('pin')
        if state=='pin':
            try:
                if 'plan' not in data:
                    data['plan']=self.router.plan()
                Router.record(db,call_id,data['plan'],'identity',iso(now))
            except RoutingUnavailable:
                return handoff('The database routing decision needs a dispatcher to review it.')
            # Persistent failed attempts across calls prevent resetting the per-call limit.
            failures=db.execute("SELECT COUNT(*) FROM audit WHERE system='auth' AND reason=? AND created_at>=?",
                                (row['caller'],iso(now-timedelta(hours=1)))).fetchone()[0]
            if failures>=5:
                return handoff('Contact verification is locked temporarily. A dispatcher will verify your authority.')
            contact_phone=row['caller']
            if (self.config.mode=='demo' and row['caller']==self.config.demo_recipient
                and db.execute("SELECT 1 FROM metadata WHERE key='synthetic' AND value='true'").fetchone()):
                mapped=db.execute("SELECT value FROM metadata WHERE key='demo_contact_phone'").fetchone()
                contact_phone=mapped[0] if mapped else '+15550100100'
            contacts=db.execute('SELECT * FROM crm.contacts WHERE phone=? AND authorized=1',(contact_phone,)).fetchall()
            contact=next((c for c in contacts if len(digits)==6 and verify_pin(digits,c['pin_salt'],c['pin_digest'])),None)
            if not contact:
                if digits!='0':
                    db.execute('INSERT INTO audit(call_id,system,operation,reason,created_at) VALUES (?,?,?,?,?)',
                               (call_id,'auth','failed_pin',row['caller'],iso(now)))
                if digits!='0' and contacts and row['retries']<2:
                    return ask('pin','The contact details could not be verified. Please re-enter your six digit PIN, or press 0 to log a report.',True)
                # Unverified callers can report symptoms but cannot read contract/site data.
                data['unverified']=True
                return ask('symptom','I can log your report, but cannot share account or contract information. Please describe the problem.')
            data.update(site_id=contact['site_id'],name=contact['name'])
            return ask('symptom')
        if state=='symptom':
            if not speech:
                return ask('symptom',retry=True)
            data['symptom']=speech
            if data.get('unverified'):
                equipment=db.execute('SELECT site_id FROM sap.equipment WHERE machine=?',(data['machine'],)).fetchone()
                if equipment:
                    site=db.execute('SELECT manager_phone FROM crm.sites WHERE id=?',(equipment[0],)).fetchone()
                    if site:
                        Store.notify(db,call_id+':manager',site[0],f"Unverified caller reported a fault on machine {data['machine']}: {speech}. Please contact the dispatcher.",now)
                return handoff('Your report has been logged for review and a building manager alert has been queued where the site is known.')
            try:
                report=self.service.investigate(db,call_id,data)
            except NeedsHuman as exc:
                return handoff(str(exc)+'.',getattr(exc,'safety_flag',None))
            if report.get('existing'):
                # Record the new call in session; do not create a duplicate incident.
                data['report']=report
                save('done')
                return xml_response(report['summary'],dial=self.config.dispatcher_phone if self.config.mode=='live' else None)
            report=self.service.save_and_dispatch(db,call_id,report)
            data['report']=report
            if report['status']=='awaiting_approval':
                return ask('approval',report['summary']+' Press 1 to approve this callout charge, or 2 to request a dispatcher without approving.')
            return ask('consent',report['summary']+' '+PROMPTS['consent'])
        if state=='approval':
            if digits=='2':
                data['report']['status']='approval_declined'
                db.execute("UPDATE crm.service_cases SET status='approval_declined',report=? WHERE id=?",(json.dumps(data['report']),data['report']['case_id']))
                Store.notify(db,call_id+':declined',self.config.dispatcher_phone or 'DEMO_DISPATCHER',
                             f"{data['report']['case_id']}: caller declined callout quote; contact caller to discuss options.",now)
                save('done')
                return xml_response('No charge was approved. The dispatcher has been notified to discuss your options.',dial=self.config.dispatcher_phone if self.config.mode=='live' else None)
            if digits!='1':
                return ask('approval','Press 1 to approve the quoted callout charge, or 2 to speak with the dispatcher.',True)
            db.execute('INSERT INTO audit(call_id,system,operation,reason,created_at) VALUES (?,?,?,?,?)',
                       (call_id,'policy','billing_approved',f"{data['report']['currency']} {data['report']['callout_cents']} cents",iso(now)))
            data['report']=self.service.save_and_dispatch(db,call_id,data['report'],approved=True)
            return ask('consent',data['report']['summary']+' '+PROMPTS['consent'])
        if state=='consent':
            if digits not in ('1','2'):
                return ask('consent',retry=True)
            data['notification_consent']=digits=='1'
            if digits=='1':
                Store.notify(db,data['report']['case_id']+':caller',row['caller'],data['report']['summary'],now)
            save('done')
            return xml_response('Thank you. Your report is recorded. '+('Your message is queued for delivery.' if digits=='1' else 'No messages will be sent to you.'))
        raise ValueError('Call is already complete')
