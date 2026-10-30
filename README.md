# Predictive Maintenance: Equipment Failure-Risk Pipeline

Synthetic industrial data plus an explainable pipeline that uses telemetry, operating context and
maintenance history to flag equipment at elevated failure risk.

> **Status: Day 2 of 3 complete.** Done: master data, operating states, telemetry, failures with
> warning signs, maintenance work orders, sensor faults, the 5 bad-data scenarios, ground truth,
> validation, CSV/JSON/SQL exports and reproducibility. Next: risk engine and evaluation metrics.

## Quick start

Requires Python 3.11+ (developed on 3.13, Windows 11). No database server is needed.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python -m pipeline generate --scale full     # ~11 s: 100 machines, 90 days, 2.16M readings
python -m pipeline validate --scale full     # ~16 s: 83 checks + edge-case scoring, exits 1 on failure
python -m pipeline load --scale full         # ~19 s: DuckDB with PK/FK/CHECK constraints
pytest                                       # 60 tests, ~20 s
```

Use `--scale starter` (10 machines, 30 days, ~1 s) for a quick try. Options: `--seed` (default
`20261022`), `--out <folder>`, `--machines N`, `--days N`.

## What gets generated (full scale, seed 20261022)

| Data | Rows | File |
|---|---:|---|
| Plant / ProductionLine / Machine / Sensor | 3 / 12 / 100 / 500 | `plants.csv`, `production_lines.csv`, `machines.csv`, `sensors.csv` |
| TelemetryEvent | 2,160,000 | `telemetry/<plant_id>.parquet` |
| OperatingShift / Technician / Part | 810 / 18 / 20 | `operating_shifts.csv`, `technicians.csv`, `parts.csv` |
| MachineStateHistory | 16,183 | `machine_state_history.csv` |
| FailureEvent | 160 | `failure_events.csv` |
| MaintenanceWorkOrder | 396 (160 corrective, 209 preventive incl. 21 cancelled, 27 sensor) | `maintenance_work_orders.csv` |
| WorkOrderPart / WorkOrderTechnician (bridges) | 540 / 448 | `work_order_parts.csv`, `work_order_technicians.csv` |
| WorkOrderStatusHistory | 1,563 | `work_order_status_history.csv` |
| Bad-data scenarios (kept apart) | 118 | `exceptions/*.csv` |
| Ground truth (kept apart) | 305 | `ground_truth/ground_truth.csv` and `.json` |
| Exports | | `export/json/*.json`, `export/sql/seed.sql` |
| Manifest: row counts + SHA-256 of every file | | `manifest.json` |

`data/starter/` is committed as a small sample. `data/full/` is not committed; regenerate it.

## How it works

```
config (seed, scale)
  └─> master tables: plant → line → machine → sensor, shifts, technicians, parts
  └─> per machine:
        shift calendar + micro-stops + preventive maintenance        (states.py)
        failures from a hazard rule (age, wear since last service)   (failures.py)
        sensor faults on single sensors                              (faults.py)
        final state timeline → telemetry with pre-failure drift and sensor faults → Parquet
  └─> work orders, parts, technicians, status history; costs and downtime derived  (maintenance.py)
  └─> clean CSVs
  └─> 5 bad-data scenarios → exceptions/ ;  labels → ground_truth/                 (anomalies.py)
  └─> JSON + SQL exports, manifest
validate: 83 rule checks on clean data, then on clean + exceptions; scored against ground truth
```

- **Failures are rule-based, not random labels.** Daily hazard rises with machine age and time
  since the last service. Before each failure, the mode's sensors drift for 3–10 days (e.g.
  bearing wear: vibration up to ~2.6×), then the machine is FAILED, then repaired.
- **Sensor faults are not machine faults:** they hit one sensor, don't change the machine's
  state, and are fixed by a sensor-replacement work order with no downtime.
- **History is never overwritten:** state changes and work-order status changes are rows.
- **Derived values come from source records:** costs from parts and technician hours, downtime from
  state history, severity from criticality and downtime, status from status history.
- **Ground truth never reaches the data:** clean and exception files carry no label columns.

## Verifying it works

`python -m pipeline validate --scale full` writes `validation/validation_report.json` and
`validation_summary.md`. Current result:

- **Clean data:** 83 / 83 integrity checks pass (PKs, FKs, allowed values, date order, lifecycle
  transitions, cost/downtime reconciliation, telemetry grid/units/ranges, duplicates).
- **Edge cases:** all 118 injected records detected, 0 false positives, 0 missed:

  | Scenario | Records | Detected |
  |---|---:|---:|
  | Telemetry from unknown sensor | 12 | 12 |
  | Impossible value (outside sensor range) | 8 | 8 |
  | Impossible unit | 2 | 2 |
  | Failure before recorded symptom | 3 | 3 |
  | Maintenance end before start | 3 | 3 |
  | Sensor gap hidden as zero | 90 | 90 |

- **Sensor faults** (data quality): STUCK 9/9 and DROPOUT 4/4 detected by single-sensor rules,
  SPIKES 5/8 (short faults have too few spikes), BIAS 0/6 is not detectable from one sensor; this
  is left for the risk engine.
- A test corrupts a copy of the clean data in ways the ground truth doesn't know about and checks
  that validation fails, so the results are computed rather than hardcoded.
- **Reproducibility:** generating twice with the same seed gives identical SHA-256 for all 37 output
  files (compare the two `manifest.json` files).

## Documentation

- [Data dictionary](docs/data-dictionary.md): every field, type, allowed values, units, keys and cardinality
- [Assumptions and decisions](docs/assumptions.md)
- [Prompt history](prompts/prompt-history.md): AI prompts used during development
