-- Source schemas. Each section is a separate SQLite database.
-- crm.sqlite

CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sites(id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, name TEXT NOT NULL, floors INTEGER, manager_phone TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contacts(id TEXT PRIMARY KEY, site_id TEXT NOT NULL, name TEXT NOT NULL, phone TEXT NOT NULL, authorized INTEGER NOT NULL, pin_salt TEXT NOT NULL, pin_digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS service_cases(id TEXT PRIMARY KEY, call_id TEXT UNIQUE, machine TEXT, site_id TEXT, status TEXT NOT NULL, safety_flag TEXT, is_repeat_fault INTEGER, sla_due_at TEXT, report TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_case ON service_cases(machine) WHERE status IN ('dispatch_requested','dispatched','awaiting_approval','needs_dispatch');

-- sap.sqlite

CREATE TABLE IF NOT EXISTS equipment(machine TEXT PRIMARY KEY, site_id TEXT NOT NULL, car TEXT NOT NULL, controller TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS warranties(id TEXT PRIMARY KEY, machine TEXT NOT NULL, component TEXT, floor INTEGER, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, covers_labor INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS service_contracts(id TEXT PRIMARY KEY, site_id TEXT NOT NULL, tier TEXT NOT NULL, callback_window_days INTEGER NOT NULL, response_sla_hours INTEGER NOT NULL, starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, callout_cents INTEGER NOT NULL, currency TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS rates(id TEXT PRIMARY KEY, callout_cents INTEGER NOT NULL, currency TEXT NOT NULL);

-- iot.sqlite

CREATE TABLE IF NOT EXISTS error_codes(code TEXT PRIMARY KEY, description TEXT NOT NULL, component TEXT);
CREATE TABLE IF NOT EXISTS error_events(id TEXT PRIMARY KEY, machine TEXT NOT NULL, code TEXT NOT NULL, occurred_at TEXT NOT NULL, floor INTEGER, car_position REAL, follow_up_event_id TEXT);
CREATE INDEX IF NOT EXISTS events_by_machine_time ON error_events(machine, occurred_at);
CREATE TABLE IF NOT EXISTS device_health(machine TEXT PRIMARY KEY, last_seen_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS monitoring_alerts(id TEXT PRIMARY KEY, machine TEXT NOT NULL, description TEXT NOT NULL, case_created INTEGER NOT NULL);

-- field.sqlite

CREATE TABLE IF NOT EXISTS technicians(id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, controller TEXT NOT NULL, available INTEGER NOT NULL, travel_minutes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS work_orders(id TEXT PRIMARY KEY, case_id TEXT UNIQUE, machine TEXT NOT NULL, technician_id TEXT, status TEXT NOT NULL, completed_at TEXT, component_replaced TEXT, floor INTEGER, parent_work_order_id TEXT, estimated_arrival_at TEXT, notes TEXT);
