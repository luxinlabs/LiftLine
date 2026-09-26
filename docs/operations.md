# Operating LiftLine

## Provisioning

The demo is executable immediately. Live telephony needs operational data and credentials; no actual company systems were provided.

Set `DATA_DIR=data-live`, then run `python3 -m lift_agent init` to create empty databases. Populate the schemas in `lift_agent/store.py` through your import process. Never promote the synthetic fixtures into production: demo numbers, PINs, coverage, locations and travel times are deliberately artificial.

Contacts need E.164 telephone numbers and unique service PINs. Generate a random salt with `os.urandom(16).hex()` and a digest using `lift_agent.store.pin_hash(pin, salt)`. Store only the digest and salt. PIN entry is keypad-only; this service does not retain the PIN or record call audio. Configure provider-side log retention separately.

Machine identifiers currently support 1–12 digits; these are keyed exactly to `sap.equipment.machine`. Each machine belongs to a site; callers may access only equipment at their verified site. A site has an owner and building-manager telephone number. Unverified reporters cannot read billing, contract, or telemetry data.

Keep device heartbeats and fault timestamps in UTC ISO-8601 with a timezone, and ingest current data before live calls. The freshness threshold is 24 hours for this prototype. For an actual operational deployment, define an appropriate per-device freshness threshold, active-fault lifecycle, data-quality checks, and telemetry ingestion adapter with the service operator.

Technician rows have controller certification, availability and a supplied travel estimate. This is not a maps/location integration. The dispatcher must confirm the technician's acceptance and current ETA. A requested technician is reserved until the work is completed or an operator explicitly releases the reservation in the field-service system.

## Service deployment

Run the backend behind an HTTPS reverse proxy, with a supervisor that restarts it on failure. `PUBLIC_BASE_URL` must exactly match Twilio's webhook origin, with no trailing slash or path prefix. Configure the incoming call webhook to POST `/voice` and use the same HTTPS origin for subsequent Gather callbacks. Twilio signatures are checked against this configured origin; arbitrary forwarded host headers are ignored.

The standard-library HTTP server is suitable for a hackathon/prototype. Before high-volume production, put the application behind a hardened application server or port the handler to your service framework, add network-level rate limits, identity-based operator access, central monitoring, backup/retention policies, and real enterprise adapters. The current operator credential is a shared administrative bearer token.

For Photon:

```sh
cd integrations/photon
npm ci
npm start
```

Use the project credentials in `.env` and provision the managed iMessage line in Photon. The bridge is private on `127.0.0.1:8081`; only the backend should call it. It uses the official SDK to resolve a recipient, create a DM, and send the report. No credential values are logged by application code. `.env` includes a generated private bridge token and admin token.

When live sending is enabled, the server processes pending notifications every two seconds. You can also run `python3 -m lift_agent notify` or call the protected drain API. The webhooks create outbox entries and return promptly; they do not wait for a message to be delivered. Provider acceptance is stored as `accepted`, not `delivered`. Configure provider delivery receipts before promising confirmed delivery.

Outbox rows transition `pending → sending → accepted` or `needs_review`. A crash can leave `sending`; investigate provider history before resetting it to `pending`. Automatic retry of an ambiguous timeout is intentionally avoided to prevent duplicate texts. The outbox's unique keys prevent duplicate creation on repeated webhooks or acceptance requests.

## Operator API

`GET /health` is public and returns basic liveness.

All `/api/*` requests require `Authorization: Bearer <ADMIN_API_KEY>`.

| Endpoint | Method | Body / behavior |
|---|---|---|
| `/api/report` | GET | Cases, work orders, outbox and routing audit |
| `/api/dispatch/accept` | POST | `{"case_id":"CS-…","eta_minutes":20}`; confirms the existing requested assignment and queues the ETA update if caller consented |
| `/api/notifications/drain` | POST | `{}`; attempts pending deliveries when live sending is enabled |

Use this Python snippet from the project root to inspect records without putting tokens in shell history:

```python
import json, urllib.request
from lift_agent.config import Config
c = Config.from_env()
req = urllib.request.Request('http://127.0.0.1:8080/api/report',
    headers={'Authorization': 'Bearer ' + c.admin_key})
with urllib.request.urlopen(req) as response:
    report = json.load(response)
print(json.dumps(report, indent=2))
```

To accept an assignment, POST the documented JSON to `/api/dispatch/accept` with the same authorization header. This endpoint is for the dispatcher acting on actual technician acceptance; merely submitting a dispatch request does not confirm a visit.

## Safety and business-policy boundaries

- Safety triage is deterministic and precedes Jev and business-data queries. A model cannot override that gate.
- Unknown or uncertain safety answers get three collection attempts, then handoff. Explicit uncertainty immediately hands off.
- A failed dispatcher transfer tells the caller to contact the local emergency number for immediate danger. Configure Twilio's own fallback URL/number for total service outages as well.
- Reports distinguish an observed fault pattern from a possible repair callback. They never assert that a malfunctioning elevator is safe or that clean telemetry proves an obstruction.
- A parts warranty alone does not waive labor. A comprehensive contract or applicable labor-inclusive warranty covers the visit; otherwise the caller must approve the configured callout amount. Additional repairs need a separate estimate.
- The contract's response deadline is stored in `sla_due_at`; this prototype does not implement continuous SLA-breach escalation. Operators should monitor that deadline.
- Active cases prevent duplicate dispatch. Calls about existing cases go to the dispatcher for current status.
- Cases with no available certified technician use `needs_dispatch` and no fabricated ETA. Assignment/reassignment, cancellation, completion and rescheduling are operator responsibilities in this prototype.

## Replacing the local source systems

The four source databases deliberately expose the complete example schema. Jev picks a source for each required question; the code executes only parameterized, allowlisted operations on that source. The caller cannot submit SQL or choose table names.

For SAP/CRM/field-service APIs, replace the reads in `Service.investigate` and the identity lookup with authenticated source adapters. Add per-source timeout, data-age checks, normalized units/timezones and version identifiers. Replace the local cross-file SQLite transaction with durable workflow/saga state and idempotency keys for external mutations. The current SQLite implementation uses rollback journals and a disk-backed primary database so case, work-order and outbox writes commit together.

Jev currently routes against a fixed catalog; it cannot authenticate the source, guarantee data accuracy or infer facts absent from those sources. The routing decisions are confidence-gated and recorded in `audit`. Missing or inconsistent sources require human review.
