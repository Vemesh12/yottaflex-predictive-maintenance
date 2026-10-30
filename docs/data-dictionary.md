# Data Dictionary

All data is synthetic. Timestamps are ISO 8601 with the plant's UTC offset (`+05:30`, Asia/Kolkata).
`PK` = primary key, `FK` = foreign key. "Unique" means unique across the whole table.
The enforced version of this dictionary is [`pipeline/sql/schema.sql`](../pipeline/sql/schema.sql):
loading the data into DuckDB fails if any row breaks a PK, FK, NOT NULL or CHECK rule.

All 10 core entities, 2 bridge tables and 2 history tables are generated. Ground truth and
the deliberate bad-data records are kept in separate folders (described at the end).

## Entity relationships

```
Plant 1──N ProductionLine 1──N Machine 1──N Sensor 1──N TelemetryEvent
  │                               │                   └──0..N MaintenanceWorkOrder (SENSOR_REPLACEMENT)
  ├──1──N OperatingShift          ├──1──N MachineStateHistory N──1 OperatingShift
  │                               │            └──N──0..1 MaintenanceWorkOrder (FAILED / MAINTENANCE rows)
  ├──1──N Technician              ├──1──N MaintenanceWorkOrder ──N:M── Part        (via WorkOrderPart)
                                  │            │               ──N:M── Technician  (via WorkOrderTechnician)
                                  │            └──1──N WorkOrderStatusHistory
                                  └──1──N FailureEvent 1──1 MaintenanceWorkOrder (CORRECTIVE)
```

| Relationship | Cardinality | Optional? | Notes |
|---|---|---|---|
| Plant → ProductionLine | 1:N | No | 4 lines per plant at full scale |
| ProductionLine → Machine | 1:N | No | 8–9 machines per line (100 spread over 12) |
| Machine → Sensor | 1:N | No | Exactly 5 sensors per machine (TEMP, VIB, PRES, RPM, CURR) |
| Sensor → TelemetryEvent | 1:N | No | One reading per sensor every 30 min |
| Plant → OperatingShift | 1:N | No | 3 shifts per day |
| Plant → Technician | 1:N | No | Technicians work at one plant |
| Machine → MachineStateHistory | 1:N | No | Every state change is a new row; history never overwritten |
| OperatingShift → MachineStateHistory | 1:N | No | The shift in which the state began |
| Machine → MaintenanceWorkOrder | 1:N | Yes | Preventive, corrective and sensor-replacement |
| Sensor → MaintenanceWorkOrder | 1:N | Yes | Only SENSOR_REPLACEMENT work orders reference a sensor |
| MaintenanceWorkOrder → MachineStateHistory | 1:N | Yes | Every FAILED / MAINTENANCE state row links to its WO (and only those) |
| MaintenanceWorkOrder ↔ Part | N:M | Yes | Bridge table `work_order_part`; cancelled WOs use no parts |
| MaintenanceWorkOrder ↔ Technician | N:M | Yes | Bridge table `work_order_technician`; every COMPLETED WO has ≥ 1, cancelled WOs none |
| MaintenanceWorkOrder → WorkOrderStatusHistory | 1:N | No | OPEN → ASSIGNED → IN_PROGRESS → COMPLETED, or OPEN/ASSIGNED → CANCELLED |
| Machine → FailureEvent | 1:N | Yes | 92 of 100 machines fail at least once at full scale |
| FailureEvent → MaintenanceWorkOrder | 1:1 | No | Every failure opens exactly one CORRECTIVE WO (`work_order.failure_id` is UNIQUE) |

---

## Plant ✅ (`plants.csv`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| plant_id | VARCHAR | Yes | `PLT-NNN` | PK | Matches pattern, immutable |
| plant_name | VARCHAR | Yes | text | | Non-empty |
| city, state, country | VARCHAR | Yes | text | | Non-empty |
| timezone | VARCHAR | Yes | IANA zone, e.g. `Asia/Kolkata` | | Valid zone |
| commissioned_date | DATE | Yes | | | Before simulation start |
| status | VARCHAR | Yes | ACTIVE, INACTIVE, CLOSED | | Enum |

## ProductionLine ✅ (`production_lines.csv`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| line_id | VARCHAR | Yes | `LINE-<plant_id>-NNN` | PK | Embeds its plant_id |
| plant_id | VARCHAR | Yes | | FK → plant | Must exist |
| line_name | VARCHAR | Yes | text | | Non-empty |
| product_family | VARCHAR | Yes | Fluid handling, Air systems, Metal forming, Precision machining | | Enum |
| commissioned_date | DATE | Yes | | | ≥ plant.commissioned_date |
| status | VARCHAR | Yes | ACTIVE, INACTIVE, DECOMMISSIONED | | Enum |

## Machine ✅ (`machines.csv`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| machine_id | VARCHAR | Yes | `MCH-<line_id>-NNN` | PK | Embeds its line_id |
| line_id | VARCHAR | Yes | | FK → production_line | Must exist |
| machine_name | VARCHAR | Yes | text | | Non-empty |
| machine_type | VARCHAR | Yes | PUMP, COMPRESSOR, HYDRAULIC_PRESS, CNC_SPINDLE | | Enum |
| manufacturer, model | VARCHAR | Yes | text | | Non-empty |
| install_date | DATE | Yes | | | ≥ line.commissioned_date and < simulation start |
| criticality | VARCHAR | Yes | A (line stops), B, C | | Enum |
| pm_interval_days | INTEGER | Yes | days; A=30, B=45, C=60 | | Derived from criticality |
| status | VARCHAR | Yes | ACTIVE, INACTIVE, RETIRED | | Enum (lifecycle) |

## Sensor ✅ (`sensors.csv`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| sensor_id | VARCHAR | Yes | `SNS-<machine_id>-<TYPE>-NN` | PK | Embeds machine_id and sensor_type |
| machine_id | VARCHAR | Yes | | FK → machine | Must exist |
| sensor_type | VARCHAR | Yes | TEMP, VIB, PRES, RPM, CURR | (machine_id, sensor_type, NN) | Enum |
| unit | VARCHAR | Yes | TEMP=degC, VIB=mm/s, PRES=bar, RPM=rpm, CURR=A | | Must match sensor_type |
| range_min, range_max | DOUBLE | Yes | sensor unit | | Instrument range; min < max. Outside = **impossible** reading |
| nominal_value | DOUBLE | Yes | sensor unit | | Expected value when RUNNING at nominal load |
| normal_min, normal_max | DOUBLE | Yes | sensor unit | | Normal envelope; range_min ≤ normal_min < normal_max ≤ range_max. Outside = **warning** |
| sampling_interval_min | INTEGER | Yes | minutes (30) | | > 0 |
| install_date | DATE | Yes | | | ≥ machine.install_date |
| status | VARCHAR | Yes | ACTIVE, FAULTY, REPLACED, RETIRED | | Enum (lifecycle) |

## TelemetryEvent ✅ (`telemetry/<plant_id>.parquet`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| telemetry_id | VARCHAR | Yes | `TEL-<sensor_id>-<YYYYMMDDTHHMMSS>` (plant local time) | PK | Embeds sensor_id and timestamp |
| sensor_id | VARCHAR | Yes | | FK → sensor | Must exist (unknown sensor → quarantine) |
| machine_id | VARCHAR | Yes | | FK → machine | Must equal the sensor's machine |
| ts | TIMESTAMPTZ | Yes | | (sensor_id, ts) | On the 30-min grid, inside the simulation window |
| value | DOUBLE | Yes* | sensor unit | | Within sensor range. *NULL allowed only for a real missing reading, never 0 as a placeholder |
| unit | VARCHAR | Yes | | | Must equal sensor.unit |

## OperatingShift ✅ (`operating_shifts.csv`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| shift_id | VARCHAR | Yes | `SHF-<plant_id>-<YYYYMMDD>-<A/B/C>` | PK | |
| plant_id | VARCHAR | Yes | | FK → plant | Must exist |
| shift_date | DATE | Yes | | (plant_id, shift_date, shift_code) | Date on which the shift starts |
| shift_code | VARCHAR | Yes | A 06–14, B 14–22, C 22–06 | | Enum |
| start_ts, end_ts | TIMESTAMPTZ | Yes | | | end_ts > start_ts; 8 hours |
| planned_status | VARCHAR | Yes | PRODUCTION, NON_PRODUCTION, PLANNED_SHUTDOWN | | Enum; Sat C and all of Sunday are NON_PRODUCTION |
| planned_production_hours | INTEGER | Yes | hours | | 8 if PRODUCTION else 0 (derived) |

## MachineStateHistory ✅ (`machine_state_history.csv`): event history for machine state
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| state_event_id | VARCHAR | Yes | `MSE-NNNNNNN` | PK | |
| machine_id | VARCHAR | Yes | | FK → machine | |
| state | VARCHAR | Yes | RUNNING, IDLE, SHUTDOWN, MAINTENANCE, FAILED | | Enum |
| previous_state | VARCHAR | No | same enum | | NULL only for a machine's first record; equals the state of the previous record |
| reason | VARCHAR | Yes | PRODUCTION, MICRO_STOP, NON_PRODUCTION_SHIFT, PLANNED_PLANT_SHUTDOWN, PREVENTIVE_MAINTENANCE, BREAKDOWN, CORRECTIVE_REPAIR | | Enum |
| start_ts, end_ts | TIMESTAMPTZ | Yes | | | end > start; records of one machine are contiguous, no gaps or overlaps |
| duration_min | INTEGER | Yes | minutes | | = end_ts − start_ts (derived) |
| shift_id | VARCHAR | Yes | | FK → operating_shift | Shift containing start_ts |
| work_order_id | VARCHAR | No | | FK → maintenance_work_order | Set if and only if state is FAILED or MAINTENANCE |

## Technician ✅ (`technicians.csv`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| technician_id | VARCHAR | Yes | `TECH-<plant_id>-NNN` | PK | |
| plant_id | VARCHAR | Yes | | FK → plant | |
| technician_name | VARCHAR | Yes | synthetic display name | | Not a real person |
| specialization | VARCHAR | Yes | MECHANICAL, ELECTRICAL, INSTRUMENTATION, HYDRAULICS | | Enum; every plant has all four |
| skill_level | INTEGER | Yes | 1–3 | | |
| hourly_rate_inr | INTEGER | Yes | INR/hour; 1=450, 2=650, 3=900 | | Derived from skill_level |
| hire_date | DATE | Yes | | | Before simulation start |
| status | VARCHAR | Yes | ACTIVE, INACTIVE | | Enum |

## Part ✅ (`parts.csv`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| part_id | VARCHAR | Yes | `PART-NNNN` | PK | |
| part_name | VARCHAR | Yes | text | | |
| category | VARCHAR | Yes | BEARING, SEAL, VALVE, COOLING, SENSOR, … | | |
| compatible_machine_type | VARCHAR | Yes | machine_type or ALL | | Parts used on a WO must be compatible with its machine |
| unit_cost_inr | INTEGER | Yes | INR | | > 0 |
| lead_time_days | INTEGER | Yes | days | | ≥ 0 |
| failure_mode_addressed | VARCHAR | Yes | BEARING_WEAR, OVERHEATING, PRESSURE_LOSS, IMBALANCE, ELECTRICAL_FAULT, SENSOR_FAULT, PREVENTIVE | | Enum |

---

## FailureEvent ✅ (`failure_events.csv`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| failure_id | VARCHAR | Yes | `FLR-NNNNNN` (numbered in time order) | PK | |
| machine_id | VARCHAR | Yes | | FK → machine | |
| failure_ts | TIMESTAMPTZ | Yes | | | Inside the window; a FAILED state row starts exactly here |
| failure_mode | VARCHAR | Yes | BEARING_WEAR, OVERHEATING, PRESSURE_LOSS, IMBALANCE, ELECTRICAL_FAULT | | Enum; only modes the machine type can have |
| first_symptom_ts | TIMESTAMPTZ | Conditional | | | When a symptom was **recorded** (operator log / RCA). Required and < failure_ts for gradual modes; may be NULL for ELECTRICAL_FAULT (sudden). Violation = edge case |
| severity | VARCHAR | Yes | MINOR, MAJOR, CRITICAL | | Derived: CRITICAL if machine criticality A, MAJOR if downtime ≥ 600 min, else MINOR |
| downtime_min | INTEGER | Yes | minutes | | Derived: = its corrective WO's downtime |

The true start of degradation (`onset`) is **not** in this table. It is only in ground truth.

## MaintenanceWorkOrder ✅ (`maintenance_work_orders.csv`)
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| work_order_id | VARCHAR | Yes | `WO-2026-NNNNNN` | PK | Numbered in order of created_ts |
| machine_id | VARCHAR | Yes | | FK → machine | |
| work_order_type | VARCHAR | Yes | PREVENTIVE, CORRECTIVE, SENSOR_REPLACEMENT | | Enum |
| priority | VARCHAR | Yes | LOW (PM), MEDIUM (sensor), CORRECTIVE by criticality A=EMERGENCY, B=HIGH, C=MEDIUM | | Derived |
| status | VARCHAR | Yes | OPEN, ASSIGNED, IN_PROGRESS, COMPLETED, CANCELLED | | = last row of status history |
| failure_id | VARCHAR | Conditional | | FK → failure_event, UNIQUE | Set if and only if type = CORRECTIVE |
| sensor_id | VARCHAR | Conditional | | FK → sensor | Set if and only if type = SENSOR_REPLACEMENT |
| created_ts | TIMESTAMPTZ | Yes | | | PM: 7 days before due; corrective: at failure; sensor: when reported |
| start_ts, end_ts | TIMESTAMPTZ | Only if COMPLETED | | | created ≤ start < end. **End before start = edge case** |
| labor_hours | DOUBLE | Yes | hours | | Derived: Σ technician hours |
| labor_cost_inr | INTEGER | Yes | INR | | Derived: Σ round(hours × technician.hourly_rate_inr) |
| parts_cost_inr | INTEGER | Yes | INR | | Derived: Σ work_order_part.line_cost_inr |
| total_cost_inr | INTEGER | Yes | INR | | Derived: labor + parts |
| downtime_min | INTEGER | Yes | minutes | | Derived: Σ duration of linked state rows (0 for sensor replacement) |
| description | VARCHAR | Yes | text | | |

## WorkOrderPart ✅ bridge, N:M (`work_order_parts.csv`)
| Field | Type | Req | Validation |
|---|---|---|---|
| work_order_id | VARCHAR | Yes | FK → maintenance_work_order; PK part 1 |
| part_id | VARCHAR | Yes | FK → part; PK part 2; part must be compatible with the machine type |
| quantity | INTEGER | Yes | > 0 |
| unit_cost_inr | INTEGER | Yes | = part.unit_cost_inr (price at time of use) |
| line_cost_inr | INTEGER | Yes | Derived: quantity × unit_cost_inr |

## WorkOrderTechnician ✅ bridge, N:M (`work_order_technicians.csv`)
| Field | Type | Req | Validation |
|---|---|---|---|
| work_order_id | VARCHAR | Yes | FK → maintenance_work_order; PK part 1 |
| technician_id | VARCHAR | Yes | FK → technician; PK part 2; same plant as the machine |
| role | VARCHAR | Yes | LEAD (specialisation matches the job) or ASSIST |
| hours | DOUBLE | Yes | > 0; = work-order end − start |

## WorkOrderStatusHistory ✅ (`work_order_status_history.csv`)
| Field | Type | Req | Validation |
|---|---|---|---|
| status_event_id | VARCHAR | Yes | `WSE-NNNNNNN`, PK |
| work_order_id | VARCHAR | Yes | FK → maintenance_work_order |
| from_status | VARCHAR | No | NULL only on the first row (OPEN); equals the previous row's to_status |
| to_status | VARCHAR | Yes | Allowed: NULL→OPEN, OPEN→ASSIGNED, ASSIGNED→IN_PROGRESS, IN_PROGRESS→COMPLETED, OPEN/ASSIGNED→CANCELLED |
| changed_ts | TIMESTAMPTZ | Yes | Non-decreasing per work order |

---

## Outside the clean data

### Exceptions (`exceptions/`): the 5 deliberate bad-data scenarios
Same columns as the table they belong to, and **no label column**. A record whose ID exists in the
clean data replaces it in the validator's "received" view; a new ID is added.

| File | Scenario(s) |
|---|---|
| `telemetry_exceptions.csv` | UNKNOWN_SENSOR (new IDs), IMPOSSIBLE_VALUE, IMPOSSIBLE_UNIT, ZERO_FILLED_GAP (replace clean rows) |
| `failure_event_exceptions.csv` | FAILURE_BEFORE_SYMPTOM (replaces clean failure rows) |
| `work_order_exceptions.csv` | MAINTENANCE_END_BEFORE_START (replaces clean WO rows) |

### Ground truth (`ground_truth/ground_truth.csv` and `.json`): never an input feature
| Field | Description |
|---|---|
| gt_id | `GT-NNNNNN`, PK |
| category | MACHINE_FAILURE, SENSOR_FAULT, INJECTED_ANOMALY |
| issue_type | failure mode / sensor fault type (STUCK, SPIKES, BIAS, DROPOUT) / edge-case name |
| entity, record_id | The record the label is about (failure_id, sensor_id, telemetry_id, work_order_id) |
| machine_id, sensor_id | For filtering |
| start_ts, end_ts | Failure: **true degradation onset** → failure. Sensor fault: fault window. Anomaly: the record's time |
| expected_decision | ELEVATED_RISK_BEFORE_FAILURE, SENSOR_FAULT_NOT_MACHINE_FAULT, QUARANTINE, REJECT_READING, TREAT_AS_MISSING, FLAG_FOR_REVIEW, REJECT_WORK_ORDER |
| related_id | Work order that resolved it (failures, sensor faults) |
| rule | The documented rule that produced the label |
