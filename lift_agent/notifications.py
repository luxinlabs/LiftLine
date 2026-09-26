import base64
import json
import re
import urllib.parse
import urllib.request
from .store import iso, now_utc


def send(config, recipient, body):
    if not re.fullmatch(r'\+[1-9]\d{7,14}',recipient):
        raise ValueError('Notification recipient must use E.164 format')
    if config.provider=='photon':
        if not config.photon_token:
            raise ValueError('Missing Photon bridge token')
        request=urllib.request.Request(config.photon_url,data=json.dumps({'recipient':recipient,'body':body}).encode(),
            headers={'Content-Type':'application/json','Authorization':f'Bearer {config.photon_token}'})
    elif config.provider=='twilio':
        username,password=config.rest_credentials
        auth=base64.b64encode(f'{username}:{password}'.encode()).decode()
        request=urllib.request.Request(f'https://api.twilio.com/2010-04-01/Accounts/{config.account_sid}/Messages.json',
            data=urllib.parse.urlencode({'To':recipient,'From':config.twilio_phone,'Body':body}).encode(),
            headers={'Authorization':'Basic '+auth})
    else:
        raise ValueError('Unknown notification provider')
    with urllib.request.urlopen(request,timeout=20) as response:
        payload=json.load(response)
    return payload.get('sid') or payload.get('id') or 'provider-accepted'


def drain(store,config,transport=send):
    """Claim once before I/O. Ambiguous sends require operator reconciliation.

    No automatic resend after a timeout/crash: providers may already have accepted it.
    """
    if not config.send_notifications:
        return {'sent':0,'status':'disabled; pending messages remain visible in outbox'}
    if config.mode=='demo' and not config.demo_recipient:
        raise ValueError('Demo delivery needs a test recipient')
    with store.connect() as db:
        if config.mode=='live' and db.execute("SELECT 1 FROM metadata WHERE key='synthetic' AND value='true'").fetchone():
            raise ValueError('Refusing to message from synthetic demo data; provision real contacts in a separate DATA_DIR')
    sent=0
    while True:
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM outbox WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
            if not row:
                break
            db.execute("UPDATE outbox SET status='sending' WHERE id=?",(row['id'],))
        try:
            recipient=config.demo_recipient if config.mode=='demo' else row['recipient']
            body=(f"[LIFTLINE DEMO | {row['dedupe_key'].split(':')[-1]}] No real technician is being dispatched.\n"+row['body']) if config.mode=='demo' else row['body']
            provider_id=transport(config,recipient,body)
            with store.connect() as db:
                db.execute("UPDATE outbox SET status='accepted',provider_id=? WHERE id=?",(provider_id,row['id']))
            sent+=1
        except Exception as exc:
            with store.connect() as db:
                db.execute("UPDATE outbox SET status='needs_review',error=? WHERE id=?",(type(exc).__name__,row['id']))
    return {'sent':sent,'status':'provider acceptance does not imply delivery'}
