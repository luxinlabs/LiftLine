import base64
import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from xml.etree.ElementTree import fromstring
from lift_agent.config import Config
from lift_agent.notifications import drain
from lift_agent.router import Router, QUESTIONS, SOURCES, RoutingUnavailable
from lift_agent.server import valid_twilio_signature
from lift_agent.store import Store, iso
from lift_agent.voice import VoiceAgent


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
        self.store.initialize()
        self.now=datetime(2026,9,26,21,10,tzinfo=timezone.utc)
        self.store.seed(self.now)
        self.config=Config(data_dir=self.temp.name)
        self.agent=VoiceAgent(self.store,self.config,clock=lambda:self.now)
        self.step=0
        self.call='CA_TEST'
        self.caller='+15550100100'

    def tearDown(self):
        self.temp.cleanup()

    def say(self, digits=None, speech=None):
        params={}
        if digits is not None: params['Digits']=digits
        if speech is not None: params['SpeechResult']=speech
        result=self.agent.handle(self.call,self.caller,self.step,params)
        fromstring(result)
        self.step+=1
        return result

    def intake(self,pin='246810',machine='1002'):
        self.say()
        self.say('2')
        self.say(machine)
        self.say('1')
        self.say(pin)
        return self.say(speech='The elevator keeps stopping between floors and cycles its doors.')

    def report(self):
        return json.loads(self.store.snapshot()['cases'][0]['report'])

    def test_repeat_fault_and_component_coverage(self):
        result=self.intake()
        report=self.report()
        self.assertEqual(report['event_count'],14)
        self.assertEqual(report['floor'],7)
        self.assertEqual(report['follow_up_count'],14)
        self.assertEqual(report['previous_work_order_id'],'WO-ORIGINAL')
        self.assertTrue(report['is_repeat_fault'])
        self.assertFalse(report['unit_warranty_active'])
        self.assertTrue(report['component_warranty_active'])
        self.assertTrue(report['covered'])
        self.assertEqual(report['technician']['name'],'Ravi')
        self.assertEqual(report['sla_due_at'],iso(self.now+timedelta(hours=4)))
        self.assertIn('cannot confirm',result)
        self.assertNotIn('safe to use.',result)
        self.say('1')
        self.assertEqual(len(self.store.snapshot()['notifications']),3)

    def test_entrapment_skips_every_lookup(self):
        self.say()
        result=self.say('1')
        snap=self.store.snapshot()
        self.assertEqual(snap['routing_trace'],[])
        self.assertEqual(len(snap['work_orders']),1)  # Only seeded historic repair.
        self.assertEqual(snap['cases'][0]['safety_flag'],'entrapment_or_injury')
        self.assertIn('handoff',result)

    def test_uncertain_safety_never_proceeds(self):
        self.say()
        self.say('3')
        self.assertEqual(self.store.snapshot()['routing_trace'],[])

    def test_emergency_mid_call_interrupts(self):
        self.say(); self.say('2'); self.say('1002'); self.say('1'); self.say('246810')
        self.say(speech='Someone is now trapped inside')
        self.assertEqual(self.store.snapshot()['cases'][0]['safety_flag'],'possible_emergency')
        self.assertEqual(len(self.store.snapshot()['work_orders']),1)

    def test_billable_requires_explicit_approval(self):
        with self.store.connect() as db:
            db.execute('DELETE FROM sap.service_contracts')
            db.execute('DELETE FROM sap.warranties')
        result=self.intake()
        self.assertIn('250.00',result)
        self.assertEqual(self.report()['status'],'awaiting_approval')
        self.assertEqual(len(self.store.snapshot()['work_orders']),1)
        self.say('1')
        self.assertEqual(self.report()['status'],'dispatch_requested')
        self.assertEqual(len(self.store.snapshot()['work_orders']),2)

    def test_declined_quote_does_not_dispatch(self):
        with self.store.connect() as db:
            db.execute('DELETE FROM sap.service_contracts')
        self.intake()
        self.say('2')
        self.assertEqual(len(self.store.snapshot()['work_orders']),1)
        self.assertEqual(self.store.snapshot()['cases'][0]['status'],'approval_declined')

    def test_parts_warranty_does_not_imply_free_labor(self):
        with self.store.connect() as db:
            db.execute('DELETE FROM sap.service_contracts')
        self.intake()
        self.assertTrue(self.report()['parts_covered'])
        self.assertFalse(self.report()['covered'])

    def test_clean_telemetry_does_not_invent_obstruction(self):
        with self.store.connect() as db:
            db.execute('DELETE FROM iot.error_events')
        result=self.intake()
        self.assertIn('does not rule out',result)
        self.assertEqual(self.report()['event_count'],0)
        self.assertFalse(self.report()['is_repeat_fault'])
        self.assertEqual(len(self.store.snapshot()['work_orders']),2)

    def test_unauthorized_caller_report_no_contract_disclosure(self):
        self.caller='+15550100999'
        result=self.intake(pin='0')
        self.assertNotIn('covered',result)
        self.assertNotIn('250',result)
        operations=[r['operation'] for r in self.store.snapshot()['routing_trace']]
        self.assertNotIn('coverage',operations)
        self.assertEqual(len(self.store.snapshot()['work_orders']),1)
        self.assertEqual(len(self.store.snapshot()['notifications']),2)

    def test_wrong_site_machine_fails_closed(self):
        result=self.intake(machine='9999')
        self.assertIn('could not be verified',result)
        self.assertEqual(len(self.store.snapshot()['work_orders']),1)

    def test_webhook_retry_is_idempotent(self):
        result=self.intake()
        again=self.agent.handle(self.call,self.caller,5,{'SpeechResult':'different body'})
        self.assertEqual(result,again)
        self.assertEqual(len(self.store.snapshot()['cases']),1)
        self.assertEqual(len(self.store.snapshot()['work_orders']),2)

    def test_second_call_reuses_existing_case(self):
        self.intake()
        self.call='CA_SECOND'; self.step=0
        result=self.intake()
        self.assertIn('already an active case',result)
        self.assertEqual(len(self.store.snapshot()['cases']),1)
        self.assertEqual(len(self.store.snapshot()['work_orders']),2)

    def test_stale_telemetry_handoff(self):
        with self.store.connect() as db:
            db.execute('UPDATE iot.device_health SET last_seen_at=?',(iso(self.now-timedelta(days=2)),))
        self.assertIn('stale',self.intake())
        self.assertEqual(len(self.store.snapshot()['work_orders']),1)

    def test_no_technician_no_invented_eta(self):
        with self.store.connect() as db:
            db.execute('UPDATE field.technicians SET available=0')
        self.intake()
        self.assertIsNone(self.report()['estimated_arrival_at'])
        self.assertEqual(self.report()['status'],'needs_dispatch')

    def test_acceptance_sends_eta_only_with_consent(self):
        self.intake(); self.say('1')
        report=self.agent.service.accept(self.report()['case_id'],25)
        self.assertEqual(report['status'],'dispatched')
        self.assertEqual(report['estimated_arrival_at'],iso(self.now+timedelta(minutes=25)))
        self.assertEqual(len(self.store.snapshot()['notifications']),4)
        self.agent.service.accept(report['case_id'],25)
        self.assertEqual(len(self.store.snapshot()['notifications']),4)

    def test_no_consent_no_caller_notifications(self):
        self.intake(); self.say('2')
        self.agent.service.accept(self.report()['case_id'],25)
        self.assertEqual(len(self.store.snapshot()['notifications']),2)

    def test_demo_cannot_send(self):
        self.intake()
        def forbidden(*args): raise AssertionError('Network send attempted')
        self.assertEqual(drain(self.store,self.config,forbidden)['sent'],0)
        self.config.mode='live'; self.config.send_notifications=True
        with self.assertRaises(ValueError): drain(self.store,self.config,forbidden)

    def test_exhausted_consent_retries_preserve_case(self):
        self.intake()
        self.say(); self.say(); self.say()
        self.assertEqual(len(self.store.snapshot()['cases']),1)

    def test_out_of_order_steps_rejected(self):
        self.say()
        with self.assertRaises(ValueError):
            self.agent.handle(self.call,self.caller,7,{})


class RouterTest(unittest.TestCase):
    def response(self):
        return {'model':'jev-test','answers':{k:{'type':'choice','choice':v[1],'confidence':.95,
            'probabilities':{s:1.0 if s==v[1] else 0.0 for s in SOURCES}} for k,v in QUESTIONS.items()}}

    def test_valid_real_wire_format(self):
        observed=[]
        def transport(payload): observed.append(payload); return self.response()
        result=Router(True,transport).plan()
        self.assertEqual(result['telemetry']['source'],'iot')
        self.assertEqual(len(observed),1)
        self.assertEqual(len(observed[0]['questions']),len(QUESTIONS))

    def test_low_confidence_fails_closed(self):
        response=self.response(); response['answers']['coverage']['confidence']=.2
        with self.assertRaises(RoutingUnavailable): Router(True,lambda _:response).plan()

    def test_wrong_source_fails_closed(self):
        response=self.response(); response['answers']['coverage']['choice']='iot'
        with self.assertRaises(RoutingUnavailable): Router(True,lambda _:response).plan()

    def test_invalid_response_fails_closed(self):
        with self.assertRaises(RoutingUnavailable): Router(True,lambda _:{}).plan()

    def test_signature_binds_url_and_parameters(self):
        params={'CallSid':'CA123','Digits':'2'}
        url='https://example.com/voice?step=1'
        signature=base64.b64encode(hmac.new(b'secret',(url+'CallSidCA123Digits2').encode(),hashlib.sha1).digest()).decode()
        self.assertTrue(valid_twilio_signature('secret',url,params,signature))
        self.assertFalse(valid_twilio_signature('secret',url,{**params,'Digits':'1'},signature))
        self.assertFalse(valid_twilio_signature('secret','https://evil.com',params,signature))


class NotificationTest(unittest.TestCase):
    def test_worker_acceptance_and_no_duplicate_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory); store.initialize()
            with store.connect() as db:
                store.notify(db,'case:caller','+14155550100','Test report',datetime.now(timezone.utc))
            config=Config(mode='live',send_notifications=True)
            sends=[]
            def transport(config,recipient,body):
                sends.append((recipient,body))
                return 'provider-id'
            self.assertEqual(drain(store,config,transport)['sent'],1)
            self.assertEqual(drain(store,config,transport)['sent'],0)
            self.assertEqual(len(sends),1)
            self.assertEqual(store.snapshot()['notifications'][0]['status'],'accepted')

    def test_ambiguous_failure_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory); store.initialize()
            with store.connect() as db:
                store.notify(db,'case:caller','+14155550100','Test report',datetime.now(timezone.utc))
            config=Config(mode='live',send_notifications=True)
            def transport(*args): raise TimeoutError('private response body')
            self.assertEqual(drain(store,config,transport)['sent'],0)
            notification=store.snapshot()['notifications'][0]
            self.assertEqual(notification['status'],'needs_review')
            self.assertEqual(notification['error'],'TimeoutError')


if __name__=='__main__':
    unittest.main()
