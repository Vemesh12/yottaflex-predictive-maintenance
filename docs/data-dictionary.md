# Data Dictionary

All data is synthetic. Timestamps are ISO 8601 with the plant's UTC offset (`+05:30`, Asia/Kolkata).
`PK` = primary key, `FK` = foreign key. "Unique" means unique across the whole table.
The enforced version of this dictionary is [`pipeline/sql/schema.sql`](../pipeline/sql/schema.sql):
loading the data into DuckDB fails if any row breaks a PK, FK, NOT NULL or CHECK rule.

Status: ✅ generated now · 🕓 designed, generated in the next phase (failures and maintenance).

## Entity relationships

```
Plant 1──N ProductionLine 1──N Machine 1──N Sensor 1──N TelemetryEvent
  │                               │
  ├──1──N OperatingShift          ├──1──N MachineStateHistory N──1 OperatingShift
  ├──1──N Technician              ├──1──N MaintenanceWorkOrder ──N:M── Part        (via WorkOrderPart)
                                  │            │               ──N:M── Technician  (via WorkOrderTechnician)
                                  │            └──1──N WorkOrderStatusHistory
                                  └──1──N FailureEvent 0..1──1 MaintenanceWorkOrder (corrective WO)
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
| Machine → MaintenanceWorkOrder 🕓 | 1:N | Yes | Preventive and corrective |
| MaintenanceWorkOrder ↔ Part 🕓 | N:M | Yes | Bridge table `work_order_part` (a WO may use no parts) |
| MaintenanceWorkOrder ↔ Technician 🕓 | N:M | No | Bridge table `work_order_technician` (at least 1 technician) |
| MaintenanceWorkOrder → WorkOrderStatusHistory 🕓 | 1:N | No | OPEN → ASSIGNED → IN_PROGRESS → COMPLETED / CANCELLED |
| Machine → FailureEvent 🕓 | 1:N | Yes | Most machines never fail in the window |
| FailureEvent → MaintenanceWorkOrder 🕓 | 1:1 | No | Every failure opens exactly one corrective WO |

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
| reason | VARCHAR | Yes | PRODUCTION, MICRO_STOP, NON_PRODUCTION_SHIFT, PLANNED_PLANT_SHUTDOWN, PREVENTIVE_MAINTENANCE (+ BREAKDOWN, REPAIR later) | | Enum |
| start_ts, end_ts | TIMESTAMPTZ | Yes | | | end > start; records of one machine are contiguous, no gaps or overlaps |
| duration_min | INTEGER | Yes | minutes | | = end_ts − start_ts (derived) |
| shift_id | VARCHAR | Yes | | FK → operating_shift | Shift containing start_ts |
| work_order_id | VARCHAR | No | | FK → maintenance_work_order 🕓 | Set for MAINTENANCE / FAILED states |

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
| compatible_machine_type | VARCHAR | Yes | machine_type or ALL | | Parts used on a WO must be compatible with its machine 🕓 |
| unit_cost_inr | INTEGER | Yes | INR | | > 0 |
| lead_time_days | INTEGER | Yes | days | | ≥ 0 |
| failure_mode_addressed | VARCHAR | Yes | BEARING_WEAR, OVERHEATING, PRESSURE_LOSS, IMBALANCE, ELECTRICAL_FAULT, SENSOR_FAULT, PREVENTIVE | | Enum |

---

## Designed for the next phase 🕓

### MaintenanceWorkOrder
| Field | Type | Req | Allowed values / unit | Unique | Validation |
|---|---|---|---|---|---|
| work_order_id | VARCHAR | Yes | `WO-2026-NNNNNN` | PK | Counter in creation order |
| machine_id | VARCHAR | Yes | | FK → machine | |
| failure_id | VARCHAR | No | | FK → failure_event | Required when type = CORRECTIVE, NULL for PREVENTIVE |
| work_order_type | VARCHAR | Yes | PREVENTIVE, CORRECTIVE, SENSOR_REPLACEMENT | | Enum |
| priority | VARCHAR | Yes | LOW, MEDIUM, HIGH, EMERGENCY | | |
| created_ts, start_ts, end_ts | TIMESTAMPTZ | Yes / No / No | | | created ≤ start < end (**end before start = rejected edge case**) |
| status | VARCHAR | Yes | OPEN, ASSIGNED, IN_PROGRESS, COMPLETED, CANCELLED | | Current value = last row of status history |
| downtime_min | INTEGER | No | minutes | | Derived from linked FAILED/MAINTENANCE state records |
| labor_cost_inr, parts_cost_inr, total_cost_inr | INTEGER | No | INR | | Derived; total = labor + parts (reconciliation check) |

### WorkOrderPart (bridge, N:M)
`work_order_id` FK, `part_id` FK, `quantity` INT > 0, `unit_cost_inr` (copied from part at time of use), `line_cost_inr` = quantity × unit cost. PK (work_order_id, part_id).

### WorkOrderTechnician (bridge, N:M)
`work_order_id` FK, `technician_id` FK (same plant as the machine), `role` (LEAD/ASSIST), `hours` > 0. PK (work_order_id, technician_id).

### WorkOrderStatusHistory
`status_event_id` PK, `work_order_id` FK, `from_status`, `to_status`, `changed_ts`. Only allowed transitions; timestamps increase.

### FailureEvent
`failure_id` PK (`FLR-NNNNNN`), `machine_id` FK, `failure_ts`, `failure_mode` (enum above), `severity`, `symptom_onset_ts` (when drift began), `downtime_min` (derived), `work_order_id` FK. Rule: symptom_onset_ts < failure_ts (violation = edge case).

### Ground truth (separate file, never joined into risk-model features)
`ground_truth.csv`: record_type, record_id, label / issue_type, expected_decision, rule that produced it.
