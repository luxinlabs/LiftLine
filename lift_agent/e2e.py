"""Exercise the deployed webhook with a synthetic call; optional real demo messages.

Uses the same authenticated HTTP endpoints as Twilio, not a direct service shortcut.
The stored call ID starts E2E so this cannot be mistaken for a provider phone call.
"""
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from xml.etree.ElementTree import fromstring
from .config import Config
from .store import Store
from .demo_tools import reset_demo


def run():
    config=Config.from_env()
    if config.mode!='demo': raise ValueError('E2E harness only runs in demo mode')
    reset_demo(Store(config.data_dir),only_e2e=True)
    call_id='E2E_'+uuid.uuid4().hex
    inputs=[{}, {'Digits':'2'}, {'Digits':'30002'}, {'Digits':'1'}, {'Digits':'246810'},
            {'SpeechResult':'Our elevator keeps stopping suddenly between floors, then moves to a floor and cycles the doors.'}, {'Digits':'1'}]
    evidence={'call_id':call_id,'transport':'authenticated HTTP simulation; not a PSTN call','steps':[]}
    for step,values in enumerate(inputs):
        path='/voice'+(f'?step={step}' if step else '')
        params={'AccountSid':config.account_sid,'CallSid':call_id,'From':config.demo_recipient,'To':config.twilio_phone,**values}
        headers={'Content-Type':'application/x-www-form-urlencoded','ngrok-skip-browser-warning':'true'}
        if config.auth_token:
            material=config.base_url+path+''.join(k+params[k] for k in sorted(params))
            headers['X-Twilio-Signature']=base64.b64encode(hmac.new(config.auth_token.encode(),material.encode(),hashlib.sha1).digest()).decode()
        else:
            headers['Authorization']='Basic '+base64.b64encode(('liftline:'+config.webhook_password).encode()).decode()
        request=urllib.request.Request(config.base_url+path,data=urllib.parse.urlencode(params).encode(),headers=headers)
        with urllib.request.urlopen(request,timeout=30) as response:
            root=fromstring(response.read())
        audio=list(root.iter('Play'))
        for play in audio:
            req=urllib.request.Request(play.text,headers={'ngrok-skip-browser-warning':'true'})
            with urllib.request.urlopen(req,timeout=15) as response:
                if response.headers.get_content_type()!='audio/mpeg' or len(response.read())<100:
                    raise ValueError('Speech audio is not playable')
        evidence['steps'].append({'step':step,'elevenlabs_audio':bool(audio),'status':'ok'})
        print(f'Step {step}: HTTP OK; ElevenLabs audio={bool(audio)}',flush=True)
        if step<len(inputs)-1 and root.find('Gather') is None:
            raise ValueError('Call ended before the workflow completed')
    for _ in range(20):
        request=urllib.request.Request('http://127.0.0.1:8080/api/report',headers={'Authorization':'Bearer '+config.admin_key})
        with urllib.request.urlopen(request,timeout=5) as response: snapshot=json.load(response)
        case=next(c for c in snapshot['cases'] if c['call_id']==call_id)
        notifications=[n for n in snapshot['notifications'] if n['dedupe_key'].startswith(case['id']+':')]
        if case['status']=='dispatched' and len(notifications)>=4 and all(n['status'] in ('accepted','needs_review') for n in notifications):
            break
        time.sleep(2)
    evidence.update(case_id=case['id'],case_status=case['status'],report=json.loads(case['report']),
                    notifications=[{'role':n['dedupe_key'].split(':')[-1],'status':n['status'],'provider_id':n['provider_id'],'error':n['error']} for n in notifications])
    target=Path(config.data_dir)/'e2e-evidence.json'; target.write_text(json.dumps(evidence,indent=2))
    print(json.dumps({k:evidence[k] for k in ('case_id','case_status','notifications')},indent=2))
    if case['status']!='dispatched' or len(notifications)<4 or any(n['status']!='accepted' for n in notifications):
        raise SystemExit('Notification or simulated dispatch stage did not complete; inspect e2e-evidence.json')


if __name__=='__main__': run()
