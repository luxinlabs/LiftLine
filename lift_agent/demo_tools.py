"""Archive generated demo runs while retaining their reports and delivery audit."""
import json


def reset_demo(store,only_e2e=False):
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute("SELECT 1 FROM metadata WHERE key='synthetic' AND value='true'").fetchone():
            raise ValueError('Demo reset is only available for synthetic databases')
        query="SELECT id,report FROM crm.service_cases WHERE call_id IS NOT NULL AND status NOT IN ('closed','demo_archived')"
        if only_e2e: query+=" AND call_id LIKE 'E2E_%'"
        rows=db.execute(query).fetchall()
        for row in rows:
            db.execute("UPDATE crm.service_cases SET status='demo_archived' WHERE id=?",(row['id'],))
            db.execute("UPDATE field.work_orders SET status='demo_archived' WHERE case_id=?",(row['id'],))
            db.execute("UPDATE outbox SET status='demo_archived' WHERE dedupe_key LIKE ? AND status='pending'",(row['id']+':%',))
            report=json.loads(row['report']); tech=report.get('technician')
            if tech:
                active=db.execute("SELECT 1 FROM field.work_orders WHERE technician_id=? AND status IN ('dispatch_requested','dispatched')",(tech['id'],)).fetchone()
                if not active: db.execute('UPDATE field.technicians SET available=1 WHERE id=?',(tech['id'],))
        return {'archived_demo_cases':len(rows),'source_records_preserved':True}
