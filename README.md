# Predictive Maintenance: Equipment Failure-Risk Pipeline

Synthetic industrial data plus an explainable pipeline that uses telemetry, operating context and
maintenance history to flag equipment at elevated failure risk.

> **Status: work in progress (Day 1 of 3).** Master data, operating states, telemetry,
> reproducibility and the DuckDB schema are done. Failures, maintenance work orders, edge cases,
> validation, the risk engine and evaluation are next.

## Quick start

Requires Python 3.11+ (developed on 3.13, Windows 11). No database server is needed.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python -m pipeline generate --scale starter      # 10 machines, 14 days, ~1 second
python -m pipeline generate --scale full         # 100 machines, 90 days, 2.16M readings, ~6 seconds
python -m pipeline load --scale full             # load into DuckDB with PK/FK/CHECK constraints
pytest                                           # 29 tests, ~4 seconds
```

Options: `--seed` (default `20261022`), `--out <folder>`, `--machines N`, `--days N`.

## What gets generated

| Entity | Full scale | File |
|---|---:|---|
| Plant | 3 | `data/<scale>/plants.csv` |
| ProductionLine | 12 | `production_lines.csv` |
| Machine | 100 | `machines.csv` |
| Sensor | 500 | `sensors.csv` |
| TelemetryEvent | 2,160,000 | `telemetry/<plant_id>.parquet` |
| OperatingShift | 810 | `operating_shifts.csv` |
| Technician | 18 | `technicians.csv` |
| Part | 20 | `parts.csv` |
| MachineStateHistory | 15,890 | `machine_state_history.csv` |
| Manifest (row counts + SHA-256) | | `manifest.json` |

`data/starter/` is committed as a small sample. `data/full/` is not committed; regenerate it with
the command above.

## How it works

```
config (seed, scale) ──> master tables (plant → line → machine → sensor, shifts, technicians, parts)
                     ──> per machine: shift calendar + micro-stops + preventive maintenance
                           = operating-state timeline (stored as state-change events)
                     ──> telemetry driven by state + load + ambient temperature
                           (written machine by machine to Parquet)
                     ──> CSV / Parquet + manifest.json ──> DuckDB (schema enforces every key)
```

- **Deterministic IDs** follow the required conventions: `PLT-001`, `LINE-PLT-001-001`,
  `MCH-LINE-PLT-001-001-001`, `SNS-MCH-LINE-PLT-001-001-001-TEMP-01`, `TEL-<sensor-id>-<timestamp>`.
- **Operating context drives telemetry:** RUNNING gives normal readings, IDLE gives low readings,
  and SHUTDOWN/MAINTENANCE give readings that fall to ambient or zero. Temperature has thermal
  inertia; current and vibration follow load.
- **History is never overwritten:** every machine state change is a new `machine_state_history` row.

## Verifying it works

- `pytest` checks volumes, ID formats, PK uniqueness, every FK, date ordering, contiguous state
  history, telemetry-vs-state consistency, the shift calendar, and same-seed reproducibility.
- `python -m pipeline load` loads everything into DuckDB, which rejects any row breaking a
  PK/FK/CHECK constraint.
- Reproducibility: generating the full dataset twice with seed `20261022` gives identical SHA-256
  checksums for all 11 output files (compare the two `manifest.json` files).

## Documentation

- [Data dictionary](docs/data-dictionary.md): every field, type, allowed values, units, keys and cardinality
- [Assumptions and decisions](docs/assumptions.md)
- [Prompt history](prompts/prompt-history.md): AI prompts used during development
