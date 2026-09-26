-- Agent "tool" queries. Story 1: Sarah Miller, Car B door fault. Story 2: CodeRabbit, rooftop (floor 18) access.
-- Demo "now" = 2026-09-26 10:15. Run:  sqlite3 otis_hackathon.db < demo_queries.sql

.headers on
.mode column

-- Step 1 (safety): any live entrapment / critical events at the caller's site in the last 30 min?
SELECT e.equipment_id, q.car_label, e.error_code, e.event_ts
FROM error_events e JOIN equipment q USING (equipment_id) JOIN sites s USING (site_id)
JOIN error_code_catalog c USING (error_code)
WHERE s.address = '201 Spear St' AND c.severity = 'Critical'
  AND e.event_ts >= datetime('2026-09-26 10:15', '-30 minutes');

-- Step 2 (identify caller): look up by phone; must be Active and authorized
SELECT c.contact_id, c.first_name, c.last_name, c.role, c.is_authorized_for_service, c.status,
       s.site_id, s.name AS site, s.address, cu.name AS customer
FROM contacts c JOIN customers cu USING (customer_id) LEFT JOIN sites s ON s.site_id = c.site_id
WHERE c.phone = '+1-415-555-0142';

-- Step 3 (which elevator?): units at the site
SELECT equipment_id, car_label, controller_model, lowest_floor_served, highest_floor_served, service_notes
FROM equipment WHERE site_id = 'ST-2001';

-- Step 4 (telemetry): fault counts by unit in the last 7 days, with severity
SELECT q.car_label, e.error_code, c.description, c.severity, COUNT(*) AS n,
       GROUP_CONCAT(DISTINCT e.floor) AS floors, MIN(e.event_ts) AS first_seen, MAX(e.event_ts) AS last_seen
FROM error_events e JOIN equipment q USING (equipment_id) JOIN error_code_catalog c USING (error_code)
WHERE q.site_id = 'ST-2001' AND e.event_ts >= datetime('2026-09-26 10:15', '-7 days')
GROUP BY q.car_label, e.error_code ORDER BY n DESC;

-- Step 5 (repeat?): recent repairs on the faulting unit
SELECT work_order_id, work_type, completed_at, floor, component, component_replaced, technician_id, findings
FROM work_orders WHERE equipment_id = 'EQ-30002' AND work_type <> 'Preventive Maintenance'
ORDER BY completed_at DESC LIMIT 5;

-- Step 6a (who pays?): warranties still valid today
SELECT coverage_level, component, part_no, start_date, end_date,
       CASE WHEN end_date >= '2026-09-26' THEN 'VALID' ELSE 'expired' END AS state
FROM warranties WHERE equipment_id = 'EQ-30002';

-- Step 6b: contract terms
SELECT contract_id, tier, status, end_date, parts_covered, labor_covered, response_sla_hours,
       repeat_fault_sla_hours, callback_window_days
FROM service_contracts WHERE site_id = 'ST-2001';

-- Step 7 (duplicates?): open cases for this unit
SELECT case_id, status, opened_at, subject FROM service_cases
WHERE equipment_id = 'EQ-30002' AND status IN ('Open', 'In Progress');

-- Step 8 (dispatch): available techs certified on the unit's controller, in region
SELECT t.technician_id, t.full_name, t.skill_level, t.shift_status, t.certifications,
       ROUND(((t.current_lat - 37.7913) * (t.current_lat - 37.7913)
            + (t.current_lon + 122.3931) * (t.current_lon + 122.3931)), 6) AS dist_sq,
       (SELECT COUNT(*) FROM work_orders w WHERE w.equipment_id = 'EQ-30002'
          AND w.technician_id = t.technician_id) AS prior_visits_on_unit
FROM technicians t
WHERE t.certifications LIKE '%OTC-600%' AND t.service_region = 'SF Bay - North'
ORDER BY (t.shift_status = 'Available') DESC, prior_visits_on_unit DESC, dist_sq;

-- Step 9 (act): the agent would then write, e.g.
-- INSERT INTO service_cases (...) VALUES ('CS-48213', ..., 'AI Agent', 'Door Issue', ..., 'P2', 0, 1, 'CS-47001', 'Open', ...);
-- INSERT INTO work_orders (...) VALUES (..., 'Callback', 'T-501', ..., parent_work_order_id = <prior repair WO>, ...);

-- =====================================================================
-- Story 2: Emily Clark (CodeRabbit, +1-415-555-0171) - "Jack and I can't get
-- the elevator to take us up to the rooftop on 18."
-- =====================================================================

-- R1 (identify caller): tenant contact at the site
SELECT contact_id, first_name, last_name, role, company, is_authorized_for_service, status
FROM contacts WHERE phone = '+1-415-555-0171';

-- R2 (is 18 a restricted floor?)
SELECT car_label, highest_floor_served, secured_floors, service_notes
FROM equipment WHERE site_id = 'ST-2001';

-- R3 (should their badges work?): building access-control record
SELECT credential_id, holder_name, company, authorized_floors, status
FROM access_credentials WHERE company = 'CodeRabbit';

-- R4 (what did the elevators do?): floor-18 badge attempts, before vs after
SELECT e.error_code, c.description, COUNT(*) AS n, MIN(e.event_ts) AS first_seen, MAX(e.event_ts) AS last_seen,
       GROUP_CONCAT(DISTINCT a.holder_name) AS badge_holders
FROM error_events e JOIN error_code_catalog c USING (error_code)
LEFT JOIN access_credentials a USING (credential_id)
JOIN equipment q USING (equipment_id)
WHERE q.site_id = 'ST-2001' AND e.floor = 18 AND e.error_code LIKE 'SEC-%'
GROUP BY e.error_code;

-- R5 (what changed?): any work on the site between the last success and the first rejection
SELECT work_order_id, work_type, technician_id, completed_at, component, action_taken
FROM work_orders w JOIN equipment q USING (equipment_id)
WHERE q.site_id = 'ST-2001' AND w.completed_at BETWEEN '2026-09-22 16:13' AND '2026-09-23 15:14';

-- Expected conclusion: the elevators work mechanically and the badges are valid, but since the
-- 23 Sep floor-security update (WO for floors 14-16), every floor-18 call is rejected for all
-- tenants -> programming error. Book a no-charge callback on that work order (the Comprehensive
-- contract covers it), tell Sarah Miller (building manager), and offer a security-desk escort in the meantime.
