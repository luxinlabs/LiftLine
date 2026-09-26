"""Twilio discovery/configuration. Never print credential material."""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def save_env(updates,path='.env'):
    file=Path(path)
    lines=file.read_text().splitlines() if file.exists() else []
    result=[]
    seen=set()
    for line in lines:
        key=line.split('=',1)[0].strip() if '=' in line and not line.lstrip().startswith('#') else None
        if key in updates:
            if key not in seen:
                result.append(key+'='+str(updates[key])); seen.add(key)
        else:
            result.append(line)
    for key,value in updates.items():
        if key not in seen: result.append(key+'='+str(value))
    file.write_text('\n'.join(result)+'\n'); file.chmod(0o600)


def request(config,path,values=None):
    username,password=config.rest_credentials
    if not username or not password:
        raise ValueError('Twilio REST credentials are missing')
    auth=base64.b64encode(f'{username}:{password}'.encode()).decode()
    req=urllib.request.Request('https://api.twilio.com/2010-04-01'+path,
        data=urllib.parse.urlencode(values).encode() if values is not None else None,
        headers={'Authorization':'Basic '+auth})
    with urllib.request.urlopen(req,timeout=15) as response:
        return json.load(response)


def webhook_url(config,path='/voice'):
    if config.mode=='demo' and not config.auth_token and config.webhook_password:
        parsed=urllib.parse.urlsplit(config.base_url)
        credentials='liftline:'+urllib.parse.quote(config.webhook_password,safe='')+'@'
        return urllib.parse.urlunsplit((parsed.scheme,credentials+parsed.netloc,path.split('?')[0],path.split('?',1)[1] if '?' in path else '',''))
    return config.base_url+path


def configure_number(config):
    if not config.voice_enabled:
        raise ValueError('Public HTTPS URL and webhook authentication are required')
    base=f'/Accounts/{config.account_sid}/IncomingPhoneNumbers'
    numbers=request(config,base+'.json?PhoneNumber='+urllib.parse.quote(config.twilio_phone,safe=''))['incoming_phone_numbers']
    if len(numbers)!=1:
        raise ValueError('Configured number was not found in Twilio account')
    number=numbers[0]
    backup=Path(config.data_dir)/'twilio-webhook-backup.json'
    backup.parent.mkdir(parents=True,exist_ok=True)
    if not backup.exists():
        backup.write_text(json.dumps({k:number.get(k) for k in ('sid','voice_url','voice_method','voice_fallback_url','voice_fallback_method','status_callback','status_callback_method')},indent=2))
        backup.chmod(0o600)
    request(config,base+'/'+number['sid']+'.json',{'VoiceUrl':webhook_url(config),'VoiceMethod':'POST'})
    return {'configured':True,'phone_number':number['phone_number'],'origin':config.base_url}


def discover(config):
    base=f'/Accounts/{config.account_sid}'
    result={}
    try:
        numbers=request(config,base+'/IncomingPhoneNumbers.json?PageSize=100')['incoming_phone_numbers']
        eligible=[n for n in numbers if n.get('capabilities',{}).get('voice')]
        result['voice_numbers']=[{'sid':n['sid'],'phone_number':n['phone_number'],
                                 'has_voice_webhook':bool(n.get('voice_url'))} for n in eligible]
        if not config.twilio_phone and len(eligible)==1:
            save_env({'TWILIO_PHONE_NUMBER':eligible[0]['phone_number']})
            result['number_saved']=True
    except urllib.error.HTTPError as exc:
        result['numbers_error']=exc.code
    if not config.auth_token:
        try:
            account=request(config,base+'.json')
            if account.get('auth_token'):
                save_env({'TWILIO_AUTH_TOKEN':account['auth_token']})
                result['signature_token_saved']=True
        except urllib.error.HTTPError as exc:
            result['account_fetch_status']=exc.code
    return result
