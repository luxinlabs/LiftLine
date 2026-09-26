"""Jev chooses data sources; application policy bounds what may execute."""
import json
import math
import os
import urllib.request

SOURCES = {
    'crm': 'Verified site contacts, caller authorization, and open service cases',
    'sap': 'Customers, sites, equipment identity, controller model, contracts, rates and component warranties',
    'iot': 'Time-stamped machine faults, floors, follow-up events and device health',
    'field': 'Completed repairs, work orders, technician certifications and availability',
    'access': 'Building badge credentials and authorized floors',
    'compliance': 'Elevator inspections, certificates, results and next inspection dates',
    'human': 'No suitable source or insufficient information; ask a dispatcher',
}
QUESTIONS = {
    'identity': ('Where can I verify the caller and their authority for this site?', 'crm'),
    'equipment': ('Where can I resolve a machine number to a car and controller?', 'sap'),
    'telemetry': ('Where can I find recent fault events and whether telemetry is current?', 'iot'),
    'history': ('Where can I check which component was repaired previously?', 'field'),
    'coverage': ('Where can I check component warranty, maintenance coverage and response SLA?', 'sap'),
    'duplicate': ('Where can I check whether an active customer service case already exists?', 'crm'),
    'dispatch': ('Where can I find a certified, available technician and travel estimate?', 'field'),
    'access': ('Where can I verify which floors a building badge is authorized to access?', 'access'),
    'compliance': ('Where can I check the most recent inspection result and next due date?', 'compliance'),
}


class RoutingUnavailable(Exception):
    pass


class Router:
    def __init__(self, live=False, transport=None):
        self.live = live
        self.transport = transport or self._post

    @staticmethod
    def _post(payload):
        key = os.getenv('TYPESAFE_API_KEY', '')
        if not key:
            raise RoutingUnavailable('TypeSafe API key is missing')
        request = urllib.request.Request('https://api.typesafe.ai/v1/systemone',
            data=json.dumps(payload).encode(), headers={'Content-Type':'application/json', 'Authorization':f'Bearer {key}'})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)

    def plan(self):
        # Only the schema catalog and workflow are sent. No PINs, phone numbers or caller PII.
        if not self.live:
            return {k:{'source':v[1], 'decision':'demo policy; Jev not called'} for k,v in QUESTIONS.items()}
        payload = {'model':os.getenv('JEV_MODEL','jev-latest'),
                   'state':{'workflow':'Elevator fault intake after safety triage', 'catalog':SOURCES},
                   'questions':{k:{'type':'choice','instructions':v[0],'criteria':SOURCES} for k,v in QUESTIONS.items()}}
        try:
            response = self.transport(payload)
            plan = {}
            for key, (_, expected) in QUESTIONS.items():
                answer = response['answers'][key]
                confidence = answer['confidence']
                probabilities = answer['probabilities']
                if (answer['type'] != 'choice' or answer['choice'] != expected
                    or type(confidence) not in (float,int) or not math.isfinite(confidence)
                    or not .8 <= confidence <= 1
                    or set(probabilities) != set(SOURCES)
                    or any(type(p) not in (float,int) or not math.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values())
                    or abs(sum(probabilities.values())-1) > .01
                    or probabilities[expected] < max(probabilities.values())):
                    raise RoutingUnavailable('Jev decision needs human review')
                plan[key] = {'source':answer['choice'], 'decision':f"Jev {response.get('model','unknown')}; confidence {confidence:.3f}"}
            return plan
        except RoutingUnavailable:
            raise
        except Exception as exc:
            raise RoutingUnavailable('Jev unavailable or invalid response') from exc

    @staticmethod
    def record(db, call_id, plan, operation, timestamp):
        item = plan[operation]
        if item['source'] != QUESTIONS[operation][1]:
            raise RoutingUnavailable('Source does not own the required data')
        db.execute('INSERT INTO audit(call_id,system,operation,reason,created_at) VALUES (?,?,?,?,?)',
                   (call_id,item['source'],operation,item['decision'],timestamp))
