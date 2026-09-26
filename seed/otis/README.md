# Otis Hackathon – AI Customer Service Agent: demo data

Demo "now" is **2026-09-26 10:15** (site-local time, America/Los_Angeles). All data is synthetic.
Error codes, controller models (OTC-200/400/600) and part numbers are illustrative, not real Otis codes.

## Files
| File | What |
|---|---|
| `schema.sql` | DDL for 15 tables (runs on SQLite and PostgreSQL) |
| `otis_hackathon.db` | SQLite database with sample data |
| `otis_hackathon_data.xlsx` | Same data, one sheet per table |
| `csv/` | Same data, one CSV per table |
| `demo_queries.sql` | The agent's lookup queries for the main call, step by step |
| `generate.py` | Rebuilds everything: `python3 generate.py` |

## Tables by source system
- **SAP ERP:** customers, sites, equipment, service_contracts, warranties, parts
- **CRM:** contacts, service_cases
- **Field service:** technicians, work_orders, work_order_parts
- **IoT / remote monitoring:** error_code_catalog, error_events
- **Building access control:** access_credentials
- **Compliance:** inspections

## Demo scenarios
| Scenario | Caller / site | What the data shows |
|---|---|---|
| **Story 1:** repeat door fault | Sarah Miller, Facilities Manager (+1-415-555-0142), Harbor Point Tower, **201 Spear St**, SF | Car B (EQ-30002): 14 × DLC-101 door-lock faults in 6 days, 11 at floor 7, each followed by REL-210 re-level/door cycle. Lock contact replaced on floor 7 on 7 Sep (WO-700037, Mike Johnson) → 90-day part warranty valid; Comprehensive contract, 30-day callback window, 4-hour repeat SLA. No open case. Cars A and C clean. |
| **Story 2:** can't reach the rooftop | Emily Clark (+1-415-555-0171) and Jack Wilson (+1-415-555-0172), CodeRabbit, 201 Spear St | Rooftop terrace is floor 18, a secured floor (badge on in-car reader). Both badges are authorised for 18 in `access_credentials`. Floor-18 calls were accepted (SEC-961) until 22 Sep; since the 23 Sep floor-security update for floors 14–16 (WO-700038, Luke Harris), **every** floor-18 call is rejected (SEC-960), for other tenants too. The elevators are mechanically fine: this is a programming error. Book a no-charge callback, notify Sarah, offer an escort. |
| Alt 1: entrapment | Kevin Hall, Bayview Plaza, San Jose | North Car: SAF-501 → ALM-910 → ENT-900 in the last 6 minutes. Agent must escalate to a human, P1. |
| Alt 2: not covered | Daniel Brooks, Maple Court Apartments, Oakland | Basic contract expired Jun 2025, unit warranty expired 2016. Re-leveling + low oil pressure events. Agent quotes $395 call-out and asks for approval. |
| Alt 3: obstruction | Mary Green, Lakeside Medical Center, Walnut Creek | Elevator 2: 64 door-reversal / nudging events, no fault codes. Likely obstruction; still book a visit. |
| Alt 4: unauthorised caller | Tom Baker (+1-415-555-0199) or any unknown number, Harbor Point | Tom is an **Inactive** former manager. Agent logs the report and notifies Sarah, doesn't discuss the contract. |
