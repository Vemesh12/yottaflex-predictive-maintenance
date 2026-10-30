# Predictive Maintenance: Equipment Failure-Risk Pipeline

Synthetic industrial data plus an explainable pipeline that uses telemetry, operating context and
maintenance history to flag equipment at elevated failure risk.

**Headline result** (held-out test period, full scale): the risk engine warned before **39 of 49
failures (80%)**, a median **70 hours** in advance, with precision 0.98 and a false-positive rate of
0.14%. It beats a single-sensor-threshold baseline on F1 (0.56 vs 0.40). Electrical faults (1–3 days
of warning) are not caught at daily resolution; see [limitations](docs/risk-engine.md#8-limitations-and-next-steps).

## Quick start

Requires Python 3.11+ (developed on 3.13, Windows 11). No database server is needed.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python -m pipeline generate --scale full     # ~11 s: 100 machines, 90 days, 2.16M readings
python -m pipeline validate --scale full     # ~16 s: 83 checks + edge-case scoring, exits 1 on failure
python -m pipeline score --scale full        # ~10 s: features + calibration + risk score per machine-day
python -m pipeline evaluate --scale full     # ~2 s: chronological train/validation/test evaluation
python -m pipeline load --scale full         # ~19 s: DuckDB with PK/FK/CHECK constraints (optional)
pytest                                       # 71 tests, ~22 s
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
score:    daily features (past data only) -> thresholds learned on days 1-29 -> score, level,
          reasons, action, sensor alerts per machine-day                              (risk/)
evaluate: labels from ground truth; alert level chosen on days 30-59; reported on days 60-89
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

## Risk engine

An explainable, rule-based score from 0 to 100 for every machine, every day at 06:00, built only
from data that existed at that moment:

- **Features:** 1-day level and 3-day trend of vibration, temperature, pressure and current
  (compared with each sensor's nominal value), time and running hours since last service, overdue
  maintenance, machine age, recent failures, and sensor-health flags.
- **Score:** a sum of named contributions (up to 40 per sensor group, +10 when 2+ groups agree,
  plus maintenance history). Levels: LOW / MEDIUM / HIGH / CRITICAL, each with reasons and a
  recommended action, e.g. *"HIGH: Vibration +116% vs nominal; rising +91% vs previous week;
  2 sensor groups abnormal → Schedule inspection within 24 hours: check bearings, alignment and
  balance"*.
- **Sensor faults** (stuck, dropout, spikes) give an instrumentation alert, not machine risk.
- **Calibration:** "normal" thresholds come from the training period with robust statistics
  (median + 3/5 × MAD), no labels needed.
- **Evaluation:** chronological train/validation/test split with purging. The alert level is chosen
  on validation; precision, recall, F1, FPR, confusion matrix and lead time are reported on test.

| Test period | Precision | Recall | F1 | FPR | Failures warned | Median lead |
|---|---:|---:|---:|---:|---:|---:|
| Risk engine | 0.975 | 0.395 | 0.563 | 0.0014 | 39 / 49 | 70.5 h |
| Baseline: one sensor outside normal band | 0.916 | 0.253 | 0.396 | 0.0034 | 40 / 49 | |

Tests prove there is no leakage. Corrupting all data after day 15 leaves day ≤ 15 features
identical. Deleting ground truth doesn't affect scoring. Deleting test-period failures doesn't
change the alert level chosen on validation. Full methodology, results and limitations:
[docs/risk-engine.md](docs/risk-engine.md).

## Documentation

- [Risk engine](docs/risk-engine.md): features, scoring, calibration, evaluation, results, limitations
- [Data dictionary](docs/data-dictionary.md): every field, type, allowed values, units, keys and cardinality
- [Assumptions and decisions](docs/assumptions.md)
- [Prompt history](prompts/prompt-history.md): AI prompts used during development
