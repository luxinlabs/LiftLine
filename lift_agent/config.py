import os
from dataclasses import dataclass
from pathlib import Path


def load_env(path='.env'):
    if Path(path).exists():
        values = {}
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('\"').strip("'")
        for key,value in values.items():
            os.environ.setdefault(key,value)


@dataclass
class Config:
    data_dir: str = 'data'
    mode: str = 'demo'
    base_url: str = ''
    admin_key: str = ''
    account_sid: str = ''
    auth_token: str = ''
    twilio_phone: str = ''
    dispatcher_phone: str = ''
    send_notifications: bool = False
    provider: str = 'twilio'
    photon_url: str = 'http://127.0.0.1:8081/send'
    photon_token: str = ''
    api_key_sid: str = ''
    api_key_secret: str = ''
    webhook_password: str = ''
    demo_recipient: str = ''
    auto_accept_demo: bool = False
    jev_enabled: bool = False

    @classmethod
    def from_env(cls):
        load_env()
        config = cls(os.getenv('DATA_DIR', 'data'), os.getenv('MODE', 'demo'),
                   os.getenv('PUBLIC_BASE_URL', '').rstrip('/'), os.getenv('ADMIN_API_KEY', ''),
                   os.getenv('TWILIO_ACCOUNT_SID', ''), os.getenv('TWILIO_AUTH_TOKEN', ''),
                   os.getenv('TWILIO_PHONE_NUMBER', ''), os.getenv('DISPATCHER_PHONE', ''),
                   os.getenv('SEND_NOTIFICATIONS', 'false').lower() == 'true',
                   os.getenv('NOTIFICATION_PROVIDER', 'twilio'),
                   os.getenv('PHOTON_BRIDGE_URL', 'http://127.0.0.1:8081/send'),
                   os.getenv('PHOTON_BRIDGE_TOKEN', ''))
        config.api_key_sid=os.getenv('TWILIO_API_KEY_SID','')
        config.api_key_secret=os.getenv('TWILIO_API_KEY_SECRET','')
        config.webhook_password=os.getenv('TWILIO_WEBHOOK_PASSWORD','')
        config.demo_recipient=os.getenv('DEMO_RECIPIENT_PHONE','')
        config.auto_accept_demo=os.getenv('DEMO_AUTO_ACCEPT','false').lower()=='true'
        config.jev_enabled=os.getenv('JEV_ENABLED','false').lower()=='true'
        return config

    def validate(self):
        if self.mode not in ('demo', 'live'):
            raise ValueError('MODE must be demo or live')
        if self.mode == 'live':
            required = (self.base_url.startswith('https://'), self.admin_key,
                        self.account_sid, self.auth_token, self.twilio_phone, self.dispatcher_phone)
            if not all(required):
                raise ValueError('Live mode requires HTTPS PUBLIC_BASE_URL, ADMIN_API_KEY and all Twilio/dispatcher settings')
        if self.send_notifications and self.mode == 'demo' and not self.demo_recipient:
            raise ValueError('Demo notifications require DEMO_RECIPIENT_PHONE')

    @property
    def voice_enabled(self):
        return bool(self.base_url.startswith('https://') and self.account_sid and (self.auth_token or self.webhook_password))

    @property
    def rest_credentials(self):
        if self.api_key_sid and self.api_key_secret:
            return self.api_key_sid,self.api_key_secret
        return self.account_sid,self.auth_token
