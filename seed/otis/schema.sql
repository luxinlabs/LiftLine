-- Otis Hackathon: AI Customer Service Agent - reference schema
-- Portable DDL: runs as-is on SQLite and PostgreSQL.
-- Timestamps are site-local time (all demo sites are America/Los_Angeles).
--
-- Source-of-record for each table (simulated enterprise landscape):
--   SAP ERP (CS/PM/SD)     : customers, sites, equipment, service_contracts, warranties, parts
--   CRM (e.g. Salesforce)  : contacts, service_cases
--   Field Service (FSM)    : technicians, work_orders, work_order_parts
--   IoT / Remote Monitoring: error_code_catalog, error_events
--   Building access control: access_credentials
--   Regulatory / Compliance: inspections

-- ---------------------------------------------------------------- SAP ERP
CREATE TABLE customers (
    customer_id        VARCHAR(12) PRIMARY KEY,
    sap_customer_no    VARCHAR(12) NOT NULL UNIQUE,
    crm_account_id     VARCHAR(18) NOT NULL UNIQUE,
    name               VARCHAR(120) NOT NULL,
    segment            VARCHAR(40),          -- Commercial Office, Residential, Healthcare, ...
    account_tier       VARCHAR(20),          -- Strategic, Key, Standard
    billing_city       VARCHAR(60),
    billing_state      VARCHAR(4),
    country            VARCHAR(4),
    created_at         DATE
);

CREATE TABLE sites (
    site_id                 VARCHAR(12) PRIMARY KEY,
    customer_id             VARCHAR(12) NOT NULL REFERENCES customers(customer_id),
    sap_functional_location VARCHAR(30) NOT NULL UNIQUE,
    name                    VARCHAR(120) NOT NULL,
    address                 VARCHAR(160),
    city                    VARCHAR(60),
    state                   VARCHAR(4),
    postal_code             VARCHAR(10),
    building_type           VARCHAR(40),
    floors                  INTEGER,
    service_region          VARCHAR(40),
    timezone                VARCHAR(40),
    latitude                REAL,
    longitude               REAL
);

CREATE TABLE equipment (
    equipment_id              VARCHAR(12) PRIMARY KEY,
    sap_equipment_no          VARCHAR(12) NOT NULL UNIQUE,
    site_id                   VARCHAR(12) NOT NULL REFERENCES sites(site_id),
    car_label                 VARCHAR(20) NOT NULL,   -- how the customer names it: "Car B"
    equipment_type            VARCHAR(20),            -- Elevator, Escalator
    product_line              VARCHAR(30),
    controller_model          VARCHAR(20),
    drive_type                VARCHAR(30),
    floors_served             INTEGER,
    capacity_kg               INTEGER,
    speed_mps                 REAL,
    install_date              DATE,
    iot_device_id             VARCHAR(20) UNIQUE,
    remote_monitoring_enabled BOOLEAN,
    operational_status        VARCHAR(20),            -- In Service, Out of Service, Under Repair
    lowest_floor_served       VARCHAR(4),             -- e.g. L
    highest_floor_served      VARCHAR(4),             -- e.g. 12
    service_notes             VARCHAR(240),
    secured_floors            VARCHAR(40)             -- floors needing a badge in the car, e.g. 18
);

CREATE TABLE service_contracts (
    contract_id               VARCHAR(12) PRIMARY KEY,
    sap_contract_no           VARCHAR(12) NOT NULL UNIQUE,
    customer_id               VARCHAR(12) NOT NULL REFERENCES customers(customer_id),
    site_id                   VARCHAR(12) NOT NULL REFERENCES sites(site_id),
    tier                      VARCHAR(20),            -- Basic, Standard, Comprehensive
    start_date                DATE,
    end_date                  DATE,
    status                    VARCHAR(12),            -- Active, Expired
    parts_covered             BOOLEAN,
    labor_covered             BOOLEAN,
    after_hours_covered       BOOLEAN,
    response_sla_hours        INTEGER,                -- standard breakdown response
    repeat_fault_sla_hours    INTEGER,                -- callback on a recent repair
    callback_window_days      INTEGER,                -- repeat within N days = no-charge callback
    non_contract_callout_usd  REAL,                   -- rate quoted if not covered
    annual_value_usd          REAL
);

CREATE TABLE parts (
    part_no                VARCHAR(20) PRIMARY KEY,
    description            VARCHAR(120),
    component_category     VARCHAR(40),
    unit_price_usd         REAL,
    part_warranty_days     INTEGER,
    compatible_controllers VARCHAR(80)
);

CREATE TABLE warranties (
    warranty_id     VARCHAR(12) PRIMARY KEY,
    equipment_id    VARCHAR(12) NOT NULL REFERENCES equipment(equipment_id),
    coverage_level  VARCHAR(12) NOT NULL,   -- Unit (new install) or Component (replaced part)
    part_no         VARCHAR(20) REFERENCES parts(part_no),
    work_order_id   VARCHAR(12),            -- repair that created a component warranty
    component       VARCHAR(80),
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    terms           VARCHAR(200)
);

-- ---------------------------------------------------------------- CRM
CREATE TABLE contacts (
    contact_id                 VARCHAR(12) PRIMARY KEY,
    customer_id                VARCHAR(12) NOT NULL REFERENCES customers(customer_id),
    site_id                    VARCHAR(12) REFERENCES sites(site_id),
    first_name                 VARCHAR(40),
    last_name                  VARCHAR(40),
    role                       VARCHAR(60),
    company                    VARCHAR(80),  -- tenant company if not the customer itself
    phone                      VARCHAR(20),
    email                      VARCHAR(120),
    is_authorized_for_service  BOOLEAN,     -- may raise cases / discuss contract
    preferred_channel          VARCHAR(12), -- Phone, SMS, Email
    status                     VARCHAR(10)  -- Active, Inactive
);

-- ---------------------------------------------------------------- IoT / Remote Monitoring
CREATE TABLE error_code_catalog (
    error_code                     VARCHAR(10) PRIMARY KEY,
    category                       VARCHAR(30),
    description                    VARCHAR(160),
    severity                       VARCHAR(10),   -- Info, Low, Medium, High, Critical
    is_safety_related              BOOLEAN,
    likely_causes                  VARCHAR(240),
    recommended_action             VARCHAR(240),
    customer_friendly_explanation  VARCHAR(240),
    auto_case_threshold_7d         INTEGER        -- raise an IoT case after N events in 7 days (NULL = never)
);

CREATE TABLE error_events (
    event_id          VARCHAR(14) PRIMARY KEY,
    equipment_id      VARCHAR(12) NOT NULL REFERENCES equipment(equipment_id),
    iot_device_id     VARCHAR(20),
    error_code        VARCHAR(10) NOT NULL REFERENCES error_code_catalog(error_code),
    event_ts          TIMESTAMP NOT NULL,
    floor             INTEGER,          -- nearest / landing floor
    car_position      VARCHAR(20),      -- At Landing, Between Floors
    direction         VARCHAR(6),       -- Up, Down, Idle
    load_pct          INTEGER,
    door_state        VARCHAR(10),      -- Open, Closed, Opening, Closing
    related_event_id  VARCHAR(14),      -- e.g. re-level event that followed a fault
    credential_id     VARCHAR(14),      -- badge used for a secured-floor call (SEC-* codes)
    acknowledged      BOOLEAN
);

-- ---------------------------------------------------------------- Building access control
-- Usually a third-party security system owned by the building, integrated with the
-- elevator controller's floor-security table. Included so the agent can compare
-- "badge should work" (this table) with "elevator rejected it" (error_events).
CREATE TABLE access_credentials (
    credential_id     VARCHAR(14) PRIMARY KEY,
    site_id           VARCHAR(12) NOT NULL REFERENCES sites(site_id),
    contact_id        VARCHAR(12) REFERENCES contacts(contact_id),
    holder_name       VARCHAR(80),
    company           VARCHAR(80),
    badge_no          VARCHAR(12),
    authorized_floors VARCHAR(80),     -- comma separated, e.g. L,15,18
    status            VARCHAR(10),     -- Active, Suspended, Expired
    updated_at        TIMESTAMP
);

-- ---------------------------------------------------------------- Field Service
CREATE TABLE technicians (
    technician_id   VARCHAR(10) PRIMARY KEY,
    full_name       VARCHAR(80),
    service_region  VARCHAR(40),
    home_base_city  VARCHAR(60),
    certifications  VARCHAR(120),   -- controller models certified on, comma separated
    skill_level     VARCHAR(12),    -- Apprentice, Mechanic, Senior, Specialist
    phone           VARCHAR(20),
    shift_status    VARCHAR(12),    -- Available, On Job, Off Shift
    current_lat     REAL,
    current_lon     REAL
);

-- ---------------------------------------------------------------- CRM (cases)
CREATE TABLE service_cases (
    case_id             VARCHAR(12) PRIMARY KEY,
    crm_case_id         VARCHAR(18) UNIQUE,
    customer_id         VARCHAR(12) NOT NULL REFERENCES customers(customer_id),
    site_id             VARCHAR(12) REFERENCES sites(site_id),
    equipment_id        VARCHAR(12) REFERENCES equipment(equipment_id),
    contact_id          VARCHAR(12) REFERENCES contacts(contact_id),
    opened_at           TIMESTAMP NOT NULL,
    channel             VARCHAR(12),    -- Phone, Email, Portal, IoT Auto, AI Agent
    category            VARCHAR(30),    -- Breakdown, Entrapment, Door Issue, Noise, Billing, ...
    subject             VARCHAR(160),
    description         VARCHAR(600),
    priority            VARCHAR(4),     -- P1 (entrapment/injury) .. P4
    safety_flag         BOOLEAN,
    is_repeat_fault     BOOLEAN,
    related_case_id     VARCHAR(12),
    status              VARCHAR(12),    -- Open, In Progress, Resolved, Closed
    sla_due_at          TIMESTAMP,
    resolved_at         TIMESTAMP,
    resolution_summary  VARCHAR(400)
);

-- ---------------------------------------------------------------- Field Service (work)
CREATE TABLE work_orders (
    work_order_id         VARCHAR(12) PRIMARY KEY,
    fsm_work_order_no     VARCHAR(14) UNIQUE,
    case_id               VARCHAR(12) REFERENCES service_cases(case_id),
    equipment_id          VARCHAR(12) NOT NULL REFERENCES equipment(equipment_id),
    parent_work_order_id  VARCHAR(12) REFERENCES work_orders(work_order_id),
    work_type             VARCHAR(24),   -- Preventive Maintenance, Repair, Callback, Inspection Support
    technician_id         VARCHAR(10) REFERENCES technicians(technician_id),
    scheduled_at          TIMESTAMP,
    started_at            TIMESTAMP,
    completed_at          TIMESTAMP,
    floor                 INTEGER,
    component             VARCHAR(80),
    component_replaced    BOOLEAN,
    findings              VARCHAR(400),
    action_taken          VARCHAR(400),
    labor_hours           REAL,
    billable              BOOLEAN,
    status                VARCHAR(12)    -- Scheduled, Dispatched, In Progress, Completed
);

CREATE TABLE work_order_parts (
    work_order_id  VARCHAR(12) NOT NULL REFERENCES work_orders(work_order_id),
    part_no        VARCHAR(20) NOT NULL REFERENCES parts(part_no),
    quantity       INTEGER NOT NULL,
    PRIMARY KEY (work_order_id, part_no)
);

-- ---------------------------------------------------------------- Compliance
CREATE TABLE inspections (
    inspection_id        VARCHAR(12) PRIMARY KEY,
    equipment_id         VARCHAR(12) NOT NULL REFERENCES equipment(equipment_id),
    inspection_date      DATE,
    authority            VARCHAR(80),
    result               VARCHAR(20),   -- Pass, Pass with Notes, Fail
    notes                VARCHAR(240),
    certificate_no       VARCHAR(20),
    next_due_date        DATE
);

CREATE INDEX ix_equipment_site        ON equipment(site_id);
CREATE INDEX ix_events_equipment_ts   ON error_events(equipment_id, event_ts);
CREATE INDEX ix_wo_equipment          ON work_orders(equipment_id, completed_at);
CREATE INDEX ix_cases_equipment       ON service_cases(equipment_id, status);
CREATE INDEX ix_events_credential     ON error_events(credential_id);
CREATE INDEX ix_contacts_phone        ON contacts(phone);
CREATE INDEX ix_warranty_equipment    ON warranties(equipment_id);
