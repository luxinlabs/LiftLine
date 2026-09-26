import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from xml.etree.ElementTree import fromstring
from .config import Config
from .notifications import drain
from .router import Router
from .server import serve
from .store import Store
from .voice import VoiceAgent


def run_demo(scenario='repeat', live_jev=False):
    now=datetime(2026,9,26,21,10,tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory(prefix='liftline-') as directory:
        store=Store(directory)
        store.initialize()
        store.seed(now)
        config=Config(data_dir=directory)
        with store.connect() as db:
            if scenario=='billable':
                db.execute('DELETE FROM sap.service_contracts')
                db.execute('DELETE FROM sap.warranties WHERE component IS NOT NULL')
            if scenario=='clean':
                db.execute('DELETE FROM iot.error_events')
        agent=VoiceAgent(store,config,Router(live=live_jev),clock=lambda:now)
        caller='+15550100999' if scenario=='unauthorized' else '+15550100100'
        inputs=[{}, {'Digits':'1' if scenario=='entrapment' else '2'}, {'Digits':'1002'}, {'Digits':'1'},
                {'Digits':'0' if scenario=='unauthorized' else '246810'},
                {'SpeechResult':'The elevator keeps stopping suddenly between floors, then cycles its doors.'}]
        if scenario=='billable':
            inputs.append({'Digits':'1'})
        inputs.append({'Digits':'1'})
        for step,params in enumerate(inputs):
            response=agent.handle('DEMO_CALL',caller,step,params)
            root=fromstring(response)
            for say in root.iter('Say'):
                print('AGENT:',say.text)
            if root.find('Hangup') is not None or root.find('Dial') is not None:
                break
        snapshot=store.snapshot()
        print('\nROUTING TRACE')
        for item in snapshot['routing_trace']:
            print(f"  {item['operation']:18} → {item['system']:6} | {item['reason']}")
        print(f"\nCases: {len(snapshot['cases'])}; queued notifications: {len(snapshot['notifications'])}; no messages sent.")
        return snapshot


def main():
    parser=argparse.ArgumentParser(description='LiftLine phone intake, investigation and dispatch')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('seed',help='Initialize the original small synthetic fixture')
    sub.add_parser('init',help='Create empty databases for provisioning real data')
    sub.add_parser('serve',help='Run voice webhook and protected operator API')
    demo=sub.add_parser('demo',help='Run a complete offline call')
    demo.add_argument('--scenario',choices=['repeat','entrapment','billable','clean','unauthorized'],default='repeat')
    demo.add_argument('--live-jev',action='store_true',help='Use the real Jev API; does not send messages or place calls')
    sub.add_parser('report',help='Print cases, work orders, outbox, and routing trace')
    sub.add_parser('notify',help='Process notification outbox; requires configured live mode')
    imported=sub.add_parser('import-otis',help='Import the supplied Otis SQLite fixture into an empty DATA_DIR')
    imported.add_argument('--source',default='seed/otis/otis_hackathon.db')
    exp=sub.add_parser('export-data',help='Write a Markdown report of every table in DATA_DIR')
    exp.add_argument('--out',default='docs/demo-data-report.md')
    sub.add_parser('configure-phone',help='Connect the configured Twilio number to this service; saves previous settings')
    sub.add_parser('discover-phone',help='Discover Twilio numbers using API-key credentials')
    sub.add_parser('configure-photon',help='Register the chosen test recipient with Photon and name the profile LiftLine')
    sub.add_parser('reset-demo',help='Archive generated demo cases and release their technicians; preserve history')
    args=parser.parse_args()
    config=Config.from_env()
    if args.command=='configure-photon':
        from .photon_setup import configure
        print(json.dumps(configure(config)))
        return
    if args.command in ('configure-phone','discover-phone'):
        from .twilio_setup import configure_number,discover
        print(json.dumps((configure_number if args.command=='configure-phone' else discover)(config)))
        return
    if args.command=='import-otis':
        from .otis_import import import_otis
        print(json.dumps(import_otis(args.source,config.data_dir),indent=2))
        return
    if args.command=='export-data':
        from .export import export_markdown
        print(export_markdown(config.data_dir,args.out))
        return
    if args.command=='demo':
        run_demo(args.scenario,args.live_jev)
        return
    store=Store(config.data_dir)
    store.initialize()
    if args.command=='reset-demo':
        from .demo_tools import reset_demo
        if config.mode!='demo': raise ValueError('Reset requires demo mode')
        print(json.dumps(reset_demo(store)))
        return
    if args.command=='seed':
        store.seed()
        print('Synthetic databases ready. Machines: 1001 / 1002 / 1003. Demo Priya PIN: 246810.')
    elif args.command=='init':
        print('Empty schemas initialized. Provision real site data before live use.')
    elif args.command=='serve':
        serve(store,config,os.getenv('HOST','127.0.0.1'),int(os.getenv('PORT','8080')))
    elif args.command=='report':
        print(json.dumps(store.snapshot(),indent=2))
    elif args.command=='notify':
        config.validate()
        print(json.dumps(drain(store,config)))


if __name__=='__main__':
    main()
