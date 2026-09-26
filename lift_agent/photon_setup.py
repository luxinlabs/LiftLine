"""Configure LiftLine's profile and explicitly selected demo recipient."""
import base64
import json
import os
import urllib.request


def configure(config):
    project=os.environ['SPECTRUM_PROJECT_ID']
    secret=os.environ['SPECTRUM_PROJECT_SECRET']
    auth='Basic '+base64.b64encode(f'{project}:{secret}'.encode()).decode()
    def call(path,method='GET',body=None):
        req=urllib.request.Request(f'https://spectrum.photon.codes/projects/{project}'+path,
            method=method,data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization':auth,'Content-Type':'application/json',
                     'User-Agent':'LiftLine/1.0 (+https://github.com/luxinlabs/LiftLine)','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=15) as response:
            return json.load(response)['data']
    users=call('/users/')
    if isinstance(users,dict): users=users.get('users',users.get('items',[]))
    existing=next((u for u in users if u.get('phoneNumber')==config.demo_recipient),None)
    if not existing:
        call('/users/','POST',{'type':'shared','phoneNumber':config.demo_recipient,'firstName':'LiftLine','lastName':'Demo'})
    call('/profile','PATCH',{'firstName':'LiftLine','lastName':''})
    return {'demo_recipient_registered':True,'profile_name':'LiftLine'}
