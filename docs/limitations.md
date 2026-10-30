# Limitations

What this project does not do, or does only partly, grouped by area. Each item says why it matters
and what the next step would be. Design assumptions are in [assumptions.md](assumptions.md). The
risk engine's method and results are in [risk-engine.md](risk-engine.md).

## 1. Synthetic data realism

| Limitation | Impact | Next step |
|---|---|---|
| Sensor values and failure signatures are physics-*inspired* and designed by me, not calibrated against real machines | The risk engine is tested on patterns I designed, so results show the method works end to end, not field accuracy | Re-calibrate thresholds and signatures on real plant data |
| Healthy data is cleaner than a real plant's (no gradual sensor ageing, process changes or seasonal effects) | Precision (0.98) is likely optimistic | Add more realistic noise sources |
| 92 of 100 machines fail at least once in 90 days | Much higher than a real plant; it follows from the required 100–200 failures on 100 machines | None needed for the brief; documented in assumptions |
| One sensor of each type per machine, all sampled every 30 minutes | No redundant sensors to cross-check; no high-frequency vibration data | Add redundant sensors and per-sensor sampling rates |
| All plants are in one time zone (IST), with no daylight saving | Multi-time-zone handling is untested | Store UTC alongside local time |
| No external or public data is used | Distributions are not anchored to real datasets | Use public data for schema inspiration and to check ranges |

## 2. Maintenance and resources

| Limitation | Impact | Next step |
|---|---|---|
| **Technicians can be double-booked.** Availability is not modelled: at full scale, 73 pairs of work orders overlap in time for the same technician (9 technicians affected) | Labor schedules are not realistic; no validation check catches this | Assign only technicians who are free; add an overlap check to `validate` |
| **Sensors have no status history.** All sensors stay `ACTIVE`; a faulty sensor's replacement is recorded only as a SENSOR_REPLACEMENT work order | The sensor lifecycle (ACTIVE → FAULTY → REPLACED) is not kept as event history, unlike machine states and work-order statuses | Add a `sensor_status_history` table driven by sensor faults and replacements |
| **No spare-parts stock.** `part.lead_time_days` is stored but not used; parts are always available | Repairs are never delayed by missing parts | Model stock levels and delay repairs by lead time |
| Repairs start whatever the shift (on-call technicians assumed) | Night and weekend repairs may be faster than in reality | Respect shift calendars for non-critical repairs |
| No maintenance history before the 90-day window | For the first weeks, "days since last service" is counted from the start of the window, so the "maintenance overdue" rule rarely fires (that baseline catches 0/49 failures) | Generate a pre-window history, or seed the last service date per machine |
| Sensor replacements cause no downtime (hot-swap assumed) | Instrumentation work never affects availability | Make downtime depend on the sensor type |

## 3. Bad-data scenarios and validation

| Limitation | Impact | Next step |
|---|---|---|
| Only a few injected records per scenario (2–90) | Detection rates are exact for these cases but are small samples | Make the counts configurable per scale |
| Exceptions are validated with rules, not loaded into a quarantine table | There's no persistent quarantine store with review status | Add quarantine tables with a review workflow |
| Sensor-fault detection from one sensor: STUCK 9/9, DROPOUT 4/4, **SPIKES 5/8**, **BIAS not detectable** | Short spike bursts and calibration offsets slip through | Cross-sensor and redundant-sensor checks |
| Validation runs on files after generation, not on a live stream | No real-time ingestion checks | Apply the same rules at ingestion |

## 4. Risk engine

| Limitation | Impact | Next step |
|---|---|---|
| **Electrical faults are not caught (0/8 in test).** Their warning lasts only 1–3 days and the engine scores once a day | The fastest-developing failures get no warning | Score every shift (8 h) using the latest hours of data |
| **Calibration bias on one sensor can look like real drift.** It caused 2 of the 3 test false alarms | False alarms when a sensor drifts out of calibration | Cross-check physically linked sensors |
| One false alarm (machine `PLT-003-001-004`, day 75) has no injected cause | Genuine false positives exist even on clean data | Per-machine-type or per-plant thresholds |
| Thresholds are pooled across machine types and plants | A hotter plant or machine type is judged by the same limits | Per-type thresholds once there is enough data |
| The score is a ranked risk score, not a calibrated probability | "61.6" does not mean a 61.6% chance of failure | Probability calibration (e.g. isotonic) on validation data |
| Machine-day recall is about 0.40 | Early days of a warning window look normal (drift grows slowly), so they can't be caught | Inherent to the label; failure-level recall (80%) is the operational measure |
| Daily evaluation | Lead time has a resolution of about 1 day | Shift-level scoring |
| Rule-based, not machine learning | Weights are set by hand | Train a model on the same features and chronological split; use these results as the benchmark |
| `current_risk.csv` at day 90 is all LOW at full scale | The generator finishes every repair inside the window, so nothing is degrading on the last day | Use `risk_scores.csv` for history, or simulate failures that continue past the window |

## 5. Scale, exports and environment

| Limitation | Impact | Next step |
|---|---|---|
| The starter scale (10 machines, 30 days) is too small for meaningful metrics (2 failures) | Starter is for quick runs and tests only; reported metrics come from the full scale | Not needed |
| Telemetry is exported to JSON only as a 1,000-row sample | 2.16M readings as JSON would be ~400 MB; full telemetry is in Parquet and loaded by `seed.sql` | Not needed |
| `seed.sql` is DuckDB SQL (it reads Parquet) | Other databases need the telemetry step adapted | Provide a CSV-based telemetry load |
| Tested on Windows 11, Python 3.13 | Other platforms are untested | Run the tests in CI on Linux and macOS |
| No dashboard or API | Results are files (CSV/JSON/Markdown) | Small read-only UI over `risk/` outputs |
