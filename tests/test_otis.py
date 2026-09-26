import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from lift_agent.config import Config,load_env
from lift_agent.notifications import drain
from lift_agent.otis_import import import_otis
from lift_agent.router import Router
from lift_agent.store import Store
from lift_agent.voice import VoiceAgent

SOURCE=Path(__file__).resolve().parents[1]/'seed/otis/otis_hackathon.db'


@unittest.skipUnless(SOURCE.exists(),'Generate the Otis fixture first')
class OtisTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        import_otis(SOURCE,self.temp.name)
        self.store=Store(self.temp.name)
        self.config=Config(data_dir=self.temp.name,demo_recipient='+16315388940',auto_accept_demo=True)
        self.agent=VoiceAgent(self.store,self.config,Router())

    def tearDown(self): self.temp.cleanup()

    def intake(self,machine='30002',caller=None,symptom='The elevator keeps stopping suddenly between floors.'):
        caller=caller or self.config.demo_recipient
        inputs=[{}, {'Digits':'2'}, {'Digits':machine}, {'Digits':'1'}, {'Digits':'246810'}, {'SpeechResult':symptom}]
        for step,params in enumerate(inputs):
            result=self.agent.handle('OTIS_TEST',caller,step,params)
        return result

    def report(self):
        with self.store.connect() as db:
            return json.loads(db.execute("SELECT report FROM crm.service_cases WHERE call_id='OTIS_TEST'").fetchone()[0])

    def test_actual_seed_repeat_fault_and_demo_acceptance(self):
        self.intake()
        r=self.report()
        self.assertEqual(r['caller_name'],'Sarah Miller')
        self.assertEqual(r['event_count'],14)
        self.assertEqual(r['follow_up_count'],14)
        self.assertEqual(r['previous_work_order_id'],'WO-700037')
        self.assertEqual(r['technician']['name'],'Mike Johnson')
        self.assertEqual(r['technician']['travel_minutes'],20)
        self.assertTrue(r['component_warranty_active'])
        self.agent.handle('OTIS_TEST',self.config.demo_recipient,6,{'Digits':'1'})
        self.agent.service.accept_demo_pending()
        self.assertTrue(self.report()['simulated_acceptance'])
        self.assertEqual(self.report()['status'],'dispatched')

    def test_rooftop_reads_access_control_and_programming_history(self):
        self.intake('30001','+14155550171',"Our badges won't let us reach the rooftop on floor 18.")
        r=self.report()
        self.assertEqual(r['previous_work_order_id'],'WO-700038')
        self.assertEqual(r['suspect_component'],'floor_security_table')
        self.assertGreater(r['access_rejections'],0)
        self.assertTrue(r['covered'])
        with self.store.connect() as db:
            self.assertIsNotNone(db.execute("SELECT 1 FROM audit WHERE system='access'").fetchone())

    def test_supplied_billable_story_quotes_395(self):
        result=self.intake('30004','+15105550177','The hydraulic elevator keeps re-leveling.')
        self.assertIn('395.00',result)
        self.assertEqual(self.report()['status'],'awaiting_approval')

    def test_supplied_obstruction_story_uses_events(self):
        self.intake('30006','+19255550164','Doors keep reopening.')
        self.assertEqual(self.report()['door_protection_events'],64)
        self.assertIn('obstruction',self.report()['finding'])

    def test_critical_telemetry_escalates_after_caller_says_no_emergency(self):
        result=self.intake('30009','+14085550133','The elevator stopped between floors.')
        self.assertIn('critical telemetry',result)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT safety_flag FROM crm.service_cases WHERE call_id='OTIS_TEST'").fetchone()[0],'critical_telemetry')

    def test_inactive_contact_cannot_get_account_data(self):
        result=self.intake('30002','+14155550199')
        self.assertIn('report has been logged',result)
        self.assertNotIn('covered',result)

    def test_real_delivery_uses_only_demo_recipient(self):
        self.intake()
        self.config.send_notifications=True
        sent=[]
        def send(config,recipient,body):
            sent.append((recipient,body)); return 'test-message'
        drain(self.store,self.config,send)
        self.assertEqual(len(sent),2)
        self.assertTrue(all(recipient==self.config.demo_recipient for recipient,_ in sent))
        self.assertTrue(all(body.startswith('[LIFTLINE DEMO') for _,body in sent))


class EnvTest(unittest.TestCase):
    def test_last_file_value_wins_but_exported_environment_wins_over_file(self):
        with tempfile.NamedTemporaryFile(mode='w') as f:
            f.write('LIFTLINE_TEST_KEY=old\nLIFTLINE_TEST_KEY=new\n'); f.flush()
            with patch.dict('os.environ',{},clear=True):
                load_env(f.name)
                import os
                self.assertEqual(os.environ['LIFTLINE_TEST_KEY'],'new')
