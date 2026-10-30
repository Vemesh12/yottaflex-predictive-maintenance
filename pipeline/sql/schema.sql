-- Relational schema (DuckDB). Parents are created before children; every FK is declared,
-- so DuckDB itself rejects an orphan row at load time.
-- Only the clean baseline is loaded here. exceptions/ and ground_truth/ are never loaded:
-- the exceptions would (correctly) be rejected, and ground truth must stay out of model inputs.

CREATE TABLE plant (
    plant_id          VARCHAR PRIMARY KEY,
    plant_name        VARCHAR NOT NULL,
    city              VARCHAR NOT NULL,
    state             VARCHAR NOT NULL,
    country           VARCHAR NOT NULL,
    timezone          VARCHAR NOT NULL,
    commissioned_date DATE    NOT NULL,
    status            VARCHAR NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE', 'CLOSED'))
);

CREATE TABLE production_line (
    line_id           VARCHAR PRIMARY KEY,
    plant_id          VARCHAR NOT NULL REFERENCES plant (plant_id),
    line_name         VARCHAR NOT NULL,
    product_family    VARCHAR NOT NULL,
    commissioned_date DATE    NOT NULL,
    status            VARCHAR NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE', 'DECOMMISSIONED'))
);

CREATE TABLE machine (
    machine_id       VARCHAR PRIMARY KEY,
    line_id          VARCHAR NOT NULL REFERENCES production_line (line_id),
    machine_name     VARCHAR NOT NULL,
    machine_type     VARCHAR NOT NULL CHECK (machine_type IN ('PUMP', 'COMPRESSOR', 'HYDRAULIC_PRESS', 'CNC_SPINDLE')),
    manufacturer     VARCHAR NOT NULL,
    model            VARCHAR NOT NULL,
    install_date     DATE    NOT NULL,
    criticality      VARCHAR NOT NULL CHECK (criticality IN ('A', 'B', 'C')),
    pm_interval_days INTEGER NOT NULL CHECK (pm_interval_days > 0),
    status           VARCHAR NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE', 'RETIRED'))
);

CREATE TABLE sensor (
    sensor_id             VARCHAR PRIMARY KEY,
    machine_id            VARCHAR NOT NULL REFERENCES machine (machine_id),
    sensor_type           VARCHAR NOT NULL CHECK (sensor_type IN ('TEMP', 'VIB', 'PRES', 'RPM', 'CURR')),
    unit                  VARCHAR NOT NULL CHECK (unit IN ('degC', 'mm/s', 'bar', 'rpm', 'A')),
    range_min             DOUBLE  NOT NULL,
    range_max             DOUBLE  NOT NULL,
    nominal_value         DOUBLE  NOT NULL,
    normal_min            DOUBLE  NOT NULL,
    normal_max            DOUBLE  NOT NULL,
    sampling_interval_min INTEGER NOT NULL CHECK (sampling_interval_min > 0),
    install_date          DATE    NOT NULL,
    status                VARCHAR NOT NULL CHECK (status IN ('ACTIVE', 'FAULTY', 'REPLACED', 'RETIRED')),
    CHECK (range_min < range_max),
    CHECK (range_min <= normal_min AND normal_min < normal_max AND normal_max <= range_max)
);

CREATE TABLE operating_shift (
    shift_id                 VARCHAR PRIMARY KEY,
    plant_id                 VARCHAR NOT NULL REFERENCES plant (plant_id),
    shift_date               DATE    NOT NULL,
    shift_code               VARCHAR NOT NULL CHECK (shift_code IN ('A', 'B', 'C')),
    start_ts                 TIMESTAMPTZ NOT NULL,
    end_ts                   TIMESTAMPTZ NOT NULL,
    planned_status           VARCHAR NOT NULL CHECK (planned_status IN ('PRODUCTION', 'NON_PRODUCTION', 'PLANNED_SHUTDOWN')),
    planned_production_hours INTEGER NOT NULL,
    UNIQUE (plant_id, shift_date, shift_code),
    CHECK (end_ts > start_ts)
);

CREATE TABLE technician (
    technician_id   VARCHAR PRIMARY KEY,
    plant_id        VARCHAR NOT NULL REFERENCES plant (plant_id),
    technician_name VARCHAR NOT NULL,
    specialization  VARCHAR NOT NULL CHECK (specialization IN ('MECHANICAL', 'ELECTRICAL', 'INSTRUMENTATION', 'HYDRAULICS')),
    skill_level     INTEGER NOT NULL CHECK (skill_level BETWEEN 1 AND 3),
    hourly_rate_inr INTEGER NOT NULL CHECK (hourly_rate_inr > 0),
    hire_date       DATE    NOT NULL,
    status          VARCHAR NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE'))
);

CREATE TABLE part (
    part_id                 VARCHAR PRIMARY KEY,
    part_name               VARCHAR NOT NULL,
    category                VARCHAR NOT NULL,
    compatible_machine_type VARCHAR NOT NULL,
    unit_cost_inr           INTEGER NOT NULL CHECK (unit_cost_inr > 0),
    lead_time_days          INTEGER NOT NULL CHECK (lead_time_days >= 0),
    failure_mode_addressed  VARCHAR NOT NULL
);

CREATE TABLE failure_event (
    failure_id       VARCHAR PRIMARY KEY,
    machine_id       VARCHAR NOT NULL REFERENCES machine (machine_id),
    failure_ts       TIMESTAMPTZ NOT NULL,
    failure_mode     VARCHAR NOT NULL CHECK (failure_mode IN ('BEARING_WEAR', 'OVERHEATING', 'PRESSURE_LOSS', 'IMBALANCE', 'ELECTRICAL_FAULT')),
    first_symptom_ts TIMESTAMPTZ,
    severity         VARCHAR NOT NULL CHECK (severity IN ('MINOR', 'MAJOR', 'CRITICAL')),
    downtime_min     INTEGER NOT NULL CHECK (downtime_min > 0),
    CHECK (first_symptom_ts IS NULL OR first_symptom_ts < failure_ts),
    CHECK (first_symptom_ts IS NOT NULL OR failure_mode = 'ELECTRICAL_FAULT')
);

CREATE TABLE maintenance_work_order (
    work_order_id   VARCHAR PRIMARY KEY,
    machine_id      VARCHAR NOT NULL REFERENCES machine (machine_id),
    work_order_type VARCHAR NOT NULL CHECK (work_order_type IN ('PREVENTIVE', 'CORRECTIVE', 'SENSOR_REPLACEMENT')),
    priority        VARCHAR NOT NULL CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'EMERGENCY')),
    status          VARCHAR NOT NULL CHECK (status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    failure_id      VARCHAR UNIQUE REFERENCES failure_event (failure_id),
    sensor_id       VARCHAR REFERENCES sensor (sensor_id),
    created_ts      TIMESTAMPTZ NOT NULL,
    start_ts        TIMESTAMPTZ,
    end_ts          TIMESTAMPTZ,
    labor_hours     DOUBLE  NOT NULL CHECK (labor_hours >= 0),
    labor_cost_inr  INTEGER NOT NULL CHECK (labor_cost_inr >= 0),
    parts_cost_inr  INTEGER NOT NULL CHECK (parts_cost_inr >= 0),
    total_cost_inr  INTEGER NOT NULL,
    downtime_min    INTEGER NOT NULL CHECK (downtime_min >= 0),
    description     VARCHAR NOT NULL,
    CHECK (total_cost_inr = labor_cost_inr + parts_cost_inr),
    CHECK (end_ts IS NULL OR end_ts > start_ts),
    CHECK (start_ts IS NULL OR start_ts >= created_ts),
    CHECK ((work_order_type = 'CORRECTIVE') = (failure_id IS NOT NULL)),
    CHECK ((work_order_type = 'SENSOR_REPLACEMENT') = (sensor_id IS NOT NULL))
);

CREATE TABLE work_order_part (
    work_order_id VARCHAR NOT NULL REFERENCES maintenance_work_order (work_order_id),
    part_id       VARCHAR NOT NULL REFERENCES part (part_id),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost_inr INTEGER NOT NULL CHECK (unit_cost_inr > 0),
    line_cost_inr INTEGER NOT NULL,
    PRIMARY KEY (work_order_id, part_id),
    CHECK (line_cost_inr = quantity * unit_cost_inr)
);

CREATE TABLE work_order_technician (
    work_order_id VARCHAR NOT NULL REFERENCES maintenance_work_order (work_order_id),
    technician_id VARCHAR NOT NULL REFERENCES technician (technician_id),
    role          VARCHAR NOT NULL CHECK (role IN ('LEAD', 'ASSIST')),
    hours         DOUBLE  NOT NULL CHECK (hours > 0),
    PRIMARY KEY (work_order_id, technician_id)
);

CREATE TABLE work_order_status_history (
    status_event_id VARCHAR PRIMARY KEY,
    work_order_id   VARCHAR NOT NULL REFERENCES maintenance_work_order (work_order_id),
    from_status     VARCHAR,
    to_status       VARCHAR NOT NULL CHECK (to_status IN ('OPEN', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')),
    changed_ts      TIMESTAMPTZ NOT NULL
);

CREATE TABLE machine_state_history (
    state_event_id VARCHAR PRIMARY KEY,
    machine_id     VARCHAR NOT NULL REFERENCES machine (machine_id),
    state          VARCHAR NOT NULL CHECK (state IN ('RUNNING', 'IDLE', 'SHUTDOWN', 'MAINTENANCE', 'FAILED')),
    previous_state VARCHAR,
    reason         VARCHAR NOT NULL,
    start_ts       TIMESTAMPTZ NOT NULL,
    end_ts         TIMESTAMPTZ NOT NULL,
    duration_min   INTEGER NOT NULL,
    shift_id       VARCHAR NOT NULL REFERENCES operating_shift (shift_id),
    work_order_id  VARCHAR REFERENCES maintenance_work_order (work_order_id),
    CHECK (end_ts > start_ts),
    CHECK ((state IN ('FAILED', 'MAINTENANCE')) = (work_order_id IS NOT NULL))
);

CREATE TABLE telemetry_event (
    telemetry_id VARCHAR PRIMARY KEY,
    sensor_id    VARCHAR NOT NULL REFERENCES sensor (sensor_id),
    machine_id   VARCHAR NOT NULL REFERENCES machine (machine_id),
    ts           TIMESTAMPTZ NOT NULL,
    value        DOUBLE,
    unit         VARCHAR NOT NULL
);
