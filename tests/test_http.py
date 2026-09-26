"""Local HTTP contract tests; never contact a phone or external provider."""
import base64
import hashlib
import hmac
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from lift_agent.config import Config
from lift_agent.server import handler_for
from lift_agent.store import Store


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.store=Store(cls.temp.name)
        cls.store.initialize()
        cls.config=Config(mode='live',base_url='https://voice.example',admin_key='test-admin',
                          auth_token='test-token',account_sid='AC_TEST',dispatcher_phone='+14155550100')
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(cls.store,cls.config))
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(); cls.temp.cleanup()

    def request(self,path,params=None,valid=True,admin=False):
        headers={}
        body=None
        if params is not None:
            body=urllib.parse.urlencode(params).encode()
            material=self.config.base_url+path+''.join(k+params[k] for k in sorted(params))
            signature=base64.b64encode(hmac.new(b'test-token',material.encode(),hashlib.sha1).digest()).decode()
            headers={'Content-Type':'application/x-www-form-urlencoded','X-Twilio-Signature':signature if valid else 'invalid'}
        if admin: headers['Authorization']='Bearer test-admin'
        req=urllib.request.Request(self.base+path,data=body,headers=headers)
        try:
            with urllib.request.urlopen(req,timeout=2) as response:
                return response.status,response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code,exc.read().decode()

    def test_health_and_admin_authentication(self):
        self.assertEqual(self.request('/health')[0],200)
        self.assertEqual(self.request('/api/report')[0],401)
        status,body=self.request('/api/report',admin=True)
        self.assertEqual(status,200)
        self.assertIn('cases',json.loads(body))

    def test_signed_call_and_immediate_transfer(self):
        params={'AccountSid':'AC_TEST','CallSid':'CA_HTTP','From':'+14155550200'}
        status,body=self.request('/voice',params)
        self.assertEqual(status,200)
        self.assertIn('trapped',body)
        status,body=self.request('/voice?step=1',{**params,'Digits':'1'})
        self.assertEqual(status,200)
        self.assertIn('<Dial',body)
        self.assertIn('+14155550100',body)
        self.assertEqual(self.store.snapshot()['routing_trace'],[])

    def test_invalid_signature_rejected(self):
        status,_=self.request('/voice',{'AccountSid':'AC_TEST','CallSid':'CA_BAD'},valid=False)
        self.assertEqual(status,403)

    def test_failed_transfer_response(self):
        status,body=self.request('/voice/transfer-result',{'AccountSid':'AC_TEST','DialCallStatus':'no-answer'})
        self.assertEqual(status,200)
        self.assertIn('local emergency number',body)
