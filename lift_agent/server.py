import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from .notifications import drain
from .router import QUESTIONS, SOURCES
from .service import Service
from .voice import VoiceAgent, xml_response
from .speech import prepare_twiml, audio_path

LOG=logging.getLogger('liftline')
STATIC_DIR=Path(__file__).parent/'static'


def valid_twilio_signature(token,url,params,signature):
    message=url+''.join(key+params[key] for key in sorted(params))
    expected=base64.b64encode(hmac.new(token.encode(),message.encode(),hashlib.sha1).digest()).decode()
    return bool(token) and hmac.compare_digest(expected,signature)


def handler_for(store,config):
    agent=VoiceAgent(store,config)

    class Handler(BaseHTTPRequestHandler):
        server_version='LiftLine/1.0'

        def log_message(self,*args):
            pass  # Never log webhook bodies, PINs, credentials, or caller numbers.

        def respond(self,status,payload,kind='application/json'):
            body=(json.dumps(payload) if kind=='application/json' else payload).encode()
            self.send_response(status)
            self.send_header('Content-Type',kind+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            if status==401:
                self.send_header('WWW-Authenticate','Basic realm="LiftLine"')
            self.end_headers()
            self.wfile.write(body)

        def is_admin(self):
            token=self.headers.get('Authorization','')
            return bool(config.admin_key) and hmac.compare_digest(token,'Bearer '+config.admin_key)

        def do_GET(self):
            route=urlsplit(self.path).path
            audio=audio_path(config,route)
            if audio:
                body=audio.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','audio/mpeg')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers(); self.wfile.write(body)
                return
            if self.path=='/health':
                return self.respond(200,{'status':'ok','mode':config.mode,'notifications_enabled':config.send_notifications})
            if self.path=='/api/report' and self.is_admin():
                report=store.snapshot()
                report['legend']={'questions':{k:{'prompt':v[0],'source':v[1]} for k,v in QUESTIONS.items()},'sources':SOURCES}
                report['mode']=config.mode
                report['jev_enabled']=config.jev_enabled
                report['notifications_enabled']=config.send_notifications
                return self.respond(200,report)
            static=self.static_file(route)
            if static is not None:
                body,kind=static
                self.respond(200,body,kind)
                return
            return self.respond(401,{'error':'Unauthorized or unknown route'})

        def static_file(self,route):
            path=STATIC_DIR/('index.html' if route=='/' else route.lstrip('/'))
            try:
                resolved=path.resolve()
                resolved.relative_to(STATIC_DIR.resolve())
            except (OSError,ValueError):
                return None
            if not resolved.is_file():
                return None
            kind=mimetypes.guess_type(resolved.name)[0] or 'application/octet-stream'
            return resolved.read_text(),kind

        def do_POST(self):
            path=urlsplit(self.path)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=16384:
                    return self.respond(413,{'error':'Body must be between 1 and 16384 bytes'})
                raw=self.rfile.read(size).decode()
                if path.path.startswith('/voice'):
                    if not config.voice_enabled:
                        return self.respond(503,{'error':'Phone webhooks are disabled in demo mode; use the CLI demo'})
                    if not self.headers.get('Content-Type','').startswith('application/x-www-form-urlencoded'):
                        return self.respond(415,{'error':'Expected form data'})
                    multi=parse_qs(raw,keep_blank_values=True)
                    if any(len(v)!=1 for v in multi.values()):
                        return self.respond(400,{'error':'Duplicate form fields are not accepted'})
                    params={k:v[0] for k,v in multi.items()}
                    # Canonical configured origin; never trust Host/X-Forwarded-Host.
                    if config.auth_token:
                        if not valid_twilio_signature(config.auth_token,config.base_url+self.path,params,self.headers.get('X-Twilio-Signature','')):
                            return self.respond(403,{'error':'Invalid Twilio signature'})
                    elif config.mode=='demo' and config.webhook_password:
                        expected='Basic '+base64.b64encode(('liftline:'+config.webhook_password).encode()).decode()
                        if not hmac.compare_digest(expected,self.headers.get('Authorization','')):
                            return self.respond(401,{'error':'Webhook authentication required'})
                    else:
                        return self.respond(403,{'error':'Webhook authentication unavailable'})
                    if params.get('AccountSid')!=config.account_sid:
                        return self.respond(403,{'error':'Wrong account'})
                    if path.path=='/voice/transfer-result':
                        status=params.get('DialCallStatus')
                        text=('Your dispatcher call has ended.' if status=='completed' else
                              'The dispatcher could not be reached. If anyone is trapped, injured, or in immediate danger, call your local emergency number now. Do not attempt a rescue.')
                        return self.respond(200,xml_response(text),'application/xml')
                    if path.path!='/voice':
                        return self.respond(404,{'error':'Unknown voice route'})
                    step=int(parse_qs(path.query).get('step',['0'])[0])
                    try:
                        result=agent.handle(params['CallSid'],params.get('From','unknown'),step,params)
                    except Exception:
                        LOG.error('Voice processing failed; transferring to dispatcher (details redacted)')
                        result=xml_response('I cannot complete the automated check. I am connecting you to the dispatcher.',dial=config.dispatcher_phone)
                    return self.respond(200,prepare_twiml(result,config),'application/xml')
                if not self.is_admin():
                    return self.respond(401,{'error':'Unauthorized'})
                data=json.loads(raw)
                if path.path=='/api/dispatch/accept':
                    return self.respond(200,Service(store,config).accept(data['case_id'],data['eta_minutes']))
                if path.path=='/api/notifications/drain':
                    return self.respond(200,drain(store,config))
                return self.respond(404,{'error':'Unknown route'})
            except (ValueError,KeyError,TypeError):
                return self.respond(400,{'error':'Invalid request'})
            except Exception:
                LOG.error('API processing failed (details redacted)')
                return self.respond(500,{'error':'Request failed; operator review required'})
    return Handler


def serve(store,config,host='127.0.0.1',port=8080):
    config.validate()
    with store.connect() as db:
        if config.mode=='live' and db.execute("SELECT 1 FROM metadata WHERE key='synthetic' AND value='true'").fetchone():
            raise ValueError('Live mode cannot use synthetic seed data. Use a separate provisioned DATA_DIR.')
    server=ThreadingHTTPServer((host,port),handler_for(store,config))
    stopped=threading.Event()
    def worker():
        while not stopped.is_set():
            try:
                Service(store,config).accept_demo_pending()
                drain(store,config)
            except Exception:
                LOG.error('Notification worker failed; operator review required (details redacted)')
            stopped.wait(2)
    if config.send_notifications or (config.mode=='demo' and config.auto_accept_demo):
        threading.Thread(target=worker,daemon=True).start()
    print(f'LiftLine service: http://{host}:{port} | mode={config.mode}',flush=True)
    try:
        server.serve_forever()
    finally:
        stopped.set()
        server.server_close()
