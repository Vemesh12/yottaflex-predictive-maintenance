-- Relational schema (DuckDB). Parents are created before children; every FK is declared,
-- so DuckDB itself rejects an orphan row at load time.
-- Day 2 adds: maintenance_work_order, work_order_part, work_order_technician,
--             work_order_status_history, failure_event, plus quarantine/ground-truth tables.

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
    work_order_id  VARCHAR,
    CHECK (end_ts > start_ts)
);

CREATE TABLE telemetry_event (
    telemetry_id VARCHAR PRIMARY KEY,
    sensor_id    VARCHAR NOT NULL REFERENCES sensor (sensor_id),
    machine_id   VARCHAR NOT NULL REFERENCES machine (machine_id),
    ts           TIMESTAMPTZ NOT NULL,
    value        DOUBLE,
    unit         VARCHAR NOT NULL
);
