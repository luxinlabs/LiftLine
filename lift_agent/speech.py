"""Optional ElevenLabs speech with cached audio and Twilio Say fallback."""
import hashlib
import hmac
import json
import os
import re
import urllib.request
from pathlib import Path
from xml.etree.ElementTree import SubElement, fromstring, tostring
from .twilio_setup import webhook_url


def synthesize(text,config):
    key=os.getenv('ELEVENLABS_API_KEY','')
    voice=os.getenv('ELEVENLABS_VOICE_ID','')
    if not key or not voice or not config.base_url:
        return None
    fingerprint=hmac.new(config.admin_key.encode(),(voice+text).encode(),hashlib.sha256).hexdigest()
    directory=Path(config.data_dir)/'audio'
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/(fingerprint+'.mp3')
    if not target.exists():
        req=urllib.request.Request(f'https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128',
            data=json.dumps({'text':text,'model_id':'eleven_flash_v2_5'}).encode(),
            headers={'xi-api-key':key,'Content-Type':'application/json','Accept':'audio/mpeg'})
        try:
            with urllib.request.urlopen(req,timeout=6) as response:
                audio=response.read()
            if not audio: return None
            temp=target.with_suffix('.tmp')
            temp.write_bytes(audio); temp.replace(target)
        except Exception:
            return None
    return config.base_url+'/audio/'+target.name


def prepare_twiml(xml,config):
    root=fromstring(xml)
    for element in root.iter():
        action=element.get('action')
        if action and action.startswith('/'):
            element.set('action',webhook_url(config,action))
    if os.getenv('ELEVENLABS_ENABLED','false').lower()=='true':
        for parent in list(root.iter()):
            for child in list(parent):
                if child.tag=='Say':
                    url=synthesize(child.text or '',config)
                    if url:
                        child.tag='Play'; child.attrib.clear(); child.text=url
    return tostring(root,encoding='unicode')


def audio_path(config,path):
    if not re.fullmatch(r'/audio/[a-f0-9]{64}\.mp3',path):
        return None
    result=Path(config.data_dir)/'audio'/path.split('/')[-1]
    return result if result.is_file() else None
