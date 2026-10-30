# Risk Engine: Methodology, Results and Limitations

```bash
python -m pipeline score --scale full      # features + calibration + scores   (~10 s)
python -m pipeline evaluate --scale full   # chronological evaluation           (~2 s)
```

Outputs in `data/<scale>/risk/`:

| File | Content |
|---|---|
| `features.csv` | One row per machine per day: every feature the score is built from |
| `calibration.json` | Thresholds learned from the training period |
| `risk_scores.csv` | Score, level, reasons, recommended action, sensor alerts, point contributions |
| `current_risk.csv` / `.json` | Latest evaluation, ranked: the "which machines need attention now" list |
| `evaluation_report.json`, `evaluation_summary.md` | Metrics per split, baselines, sensor-fault analysis |
| `failure_detection.csv` | Per failure: detected or not, and lead time |
| `evaluation_points.csv` | Every evaluation point with its label and split (evaluation output only) |

## 1. Evaluation points

The engine scores every machine **once a day at 06:00** (start of shift A, a natural handover
point). 100 machines × 90 days = 9,000 points.

## 2. Features (`pipeline/risk/features.py`)

Built only from data that existed **before** the evaluation time.

| Feature | Meaning | Source |
|---|---|---|
| `vib_excess`, `curr_excess` | Latest day's mean ÷ the sensor's nominal value − 1 | telemetry (RUNNING readings) |
| `temp_excess_c` | Latest day's mean − nominal, in °C | telemetry |
| `pres_drop` | 1 − latest day's mean ÷ nominal | telemetry |
| `*_trend` | Mean of the last 3 days − mean of days t−10…t−4 (normalised) | telemetry |
| `*_quality` | OK / STUCK / DROPOUT / SPIKES / NO_DATA for the last 3 days | telemetry |
| `days_since_service`, `wear_ratio` | Time since the last completed PM or repair; ÷ PM interval | work orders |
| `run_hours_since_service` | Running hours since that service | state history |
| `age_years` | Machine age | master data |
| `failures_30d` | Failures in the previous 30 days | failure events |

- **Only RUNNING readings** are used, so a weekend shutdown never looks like a pressure drop.
- **Comparisons are per machine:** each sensor is compared with its own `nominal_value`, so a hot
  compressor and a cool CNC spindle are on the same scale.
- **History resets after maintenance:** only days after the last completed PM or repair count. A
  repaired machine starts clean instead of carrying old warning signs.
- **Missing days are skipped, not filled:** the latest day *with* running data in the last 3 days is
  used, so a Sunday doesn't create a fake drop.

## 3. Score (`pipeline/risk/engine.py`)

The score is the sum of named contributions, capped at 100:

| Evidence | Points |
|---|---:|
| Each sensor group (VIB, TEMP, PRES, CURR): level 25 + trend 15 | up to 40 each |
| Corroboration: 2 or more sensor groups abnormal at once | 10 |
| Preventive maintenance overdue | 3 |
| A failure in the last 30 days | 2 |

Each feature earns **50% of its points at the "moderate" threshold**, rising linearly to **100% at
the "strong" threshold**. One strongly abnormal sensor group reaches MEDIUM (40). A second abnormal
group plus corroboration reaches HIGH or CRITICAL.

**Levels and actions:**

| Score | Level | Action |
|---|---|---|
| 0–29 | LOW | Normal monitoring |
| 30–59 | MEDIUM | Monitor closely; inspect at next planned stop |
| 60–79 | HIGH | Schedule inspection within 24 hours |
| 80–100 | CRITICAL | Stop at next safe point and inspect within 4 hours |

The action adds what to check, based on the strongest evidence. For example, vibration gives
"check bearings, alignment and balance", and pressure gives "check seals, valves and for leaks".

**Sensor faults are kept out of machine risk.** If a sensor's quality flag is not OK, its readings
earn **no** risk points. Instead the row gets a sensor alert, e.g. "TEMP sensor STUCK:
instrumentation check, readings ignored".

**Real example** (machine `MCH-LINE-PLT-001-001-003`, bearing failure on 2 Sep at 10:00):

| Eval | Score | Level | Reasons |
|---|---:|---|---|
| 29 Aug | 2 | LOW | 1 failure in last 30 days |
| 30 Aug | 27 | LOW | Vibration +13% vs nominal |
| 1 Sep | 42 | MEDIUM | Vibration +74%; rising +42% vs previous week → *check bearings, alignment and balance* |
| 2 Sep 06:00 | 61.6 | HIGH | Vibration +116%; rising +91%; temperature rising +5 °C; 2 sensor groups abnormal → *inspect within 24 h* |
| 3 Sep | 2 | LOW | (repaired; history reset) |

## 4. Calibration: what is "abnormal"?

Thresholds are **learned from the training period only (days 1–29), without labels**:

```
centre   = median of the feature over all training machine-days (sensor quality OK)
spread   = 1.4826 × median absolute deviation        (a robust standard deviation)
moderate = centre + 3 × spread        strong = centre + 5 × spread
```

The median and MAD are robust: the few machines degrading in the training period barely move
them, so the engine learns "normal" without needing to know which machines failed. Learned
thresholds at full scale include: vibration +5.6% / +9.1%, temperature +7.6 °C / +12.7 °C,
current +15% / +26%, pressure −1.0% / −1.7%.

## 5. Evaluation (`pipeline/risk/evaluate.py`)

**Label:** a point is positive if that machine **fails within the next 7 days**. Points where the
machine is down (between a failure and the end of its repair) are excluded.

**Chronological split, no shuffling:**

| Split | Eval days | Used for |
|---|---|---|
| Train | 1–29 | Learning thresholds (no labels) |
| Validation | 30–59 | Choosing the alert level (MEDIUM / HIGH / CRITICAL) by F1 |
| Test | 60–89 | Reported once |

**Purging:** a point only counts in its split if its whole 7-day horizon ends inside that split.
So validation labels never depend on test-period failures, and the last 7 days (unknown future)
are never scored.

**How leakage is prevented, and tested:**
- Features never read ground truth. A test deletes the ground-truth folder and features still build.
- Features never read the future. A test multiplies all telemetry after day 15 by 10, deletes
  future work orders and failures, and corrupts future machine states. Features for days ≤ 15 must
  stay byte-identical, and they do.
- Calibration only sees training days. A test sets every later feature to 1,000,000 and the
  thresholds don't change.
- The alert level is chosen on validation only. A test deletes all post-validation failures from
  ground truth and the choice doesn't change.

## 6. Results (full scale, seed 20261022)

Alert level chosen on validation: **MEDIUM or above** (validation F1 0.53, vs 0.14 for HIGH+).

| Split | Precision | Recall | F1 | FPR | Failures detected | Median lead time |
|---|---:|---:|---:|---:|---:|---:|
| Train | 1.000 | 0.334 | 0.501 | 0.000 | 38 / 49 | 62 h |
| Validation | 0.992 | 0.366 | 0.535 | 0.0005 | 52 / 62 | 64 h |
| **Test** | **0.975** | **0.395** | **0.563** | **0.0014** | **39 / 49 (80%)** | **70.5 h** |

**Test confusion matrix (machine-days):**

| | Alert | No alert |
|---|---:|---:|
| Fails within 7 days | 119 | 182 |
| Does not fail | 3 | 2,071 |

**By failure mode (test):**

| Mode | Detected | Median lead |
|---|---:|---:|
| Bearing wear | 17 / 17 | 78.5 h |
| Pressure loss | 10 / 10 | 81.8 h |
| Imbalance | 4 / 4 | 74 h |
| Overheating | 8 / 10 | 14.8 h |
| Electrical fault | 0 / 8 | – |

**Compared with simple baselines (test):**

| Approach | Precision | Recall | F1 | FPR | Failures detected |
|---|---:|---:|---:|---:|---:|
| **Risk engine** | **0.975** | **0.395** | **0.563** | **0.0014** | 39 / 49 |
| Single sensor outside its normal band | 0.916 | 0.253 | 0.396 | 0.0034 | 40 / 49 |
| Preventive maintenance overdue | 0.000 | 0.000 | 0.000 | 0.0048 | 0 / 49 |

**Sensor faults (all splits):** the engine raised an instrumentation alert, and **no** machine alert,
on 23/24 spike days, 20/24 stuck days and 8/9 dropout days. Calibration-bias faults are not
detectable from one sensor. They caused machine alerts on 4 of 16 days, including 2 of the 3
test-period false alarms.

## 7. How to read these numbers

- **Machine-day recall (~0.40) is limited by design.** A point is positive for all 7 days before a
  failure, but warning signs only start 1–10 days before (often fewer than 7), and they grow as
  progress², so the first days are almost invisible. **Failure-level recall (80%) with ~3 days'
  warning is the more meaningful operational number.**
- **Precision is very high (0.98)** because the synthetic "normal" data is cleaner than a real
  plant's. Expect more false alarms on real data.
- Results are consistent across train, validation and test, so the thresholds are not overfitted.

## 8. Limitations and next steps

- **Electrical faults are missed (0/8).** Their warning lasts only 1–3 days and current rises late,
  so a once-a-day evaluation is too coarse. *Next step:* score every shift (8 h) using the latest
  hours of data.
- **Sensor bias looks like real drift on one sensor.** *Next step:* cross-check with physically
  linked sensors (e.g. temperature rising with no change in current or vibration), or compare
  with a redundant sensor.
- **One false alarm (machine `PLT-003-001-004`, day 75) has no injected cause:** it's a genuine
  false positive from temperature alone.
- **Thresholds are pooled across machine types.** Per-type thresholds would need more data per type.
- **The score is a ranked risk score, not a calibrated probability** of failure.
- **The evaluation is on synthetic data whose failure signatures I designed**, so it shows the
  method works end to end. It does not prove field accuracy; real data would need re-calibration.
- **Points are daily,** so lead time has a resolution of about 1 day.
- **The final day's ranking (`current_risk.csv`) is all LOW at full scale.** This is a result of the
  generator: every failure must be repaired inside the window, so nothing is degrading on day 90.
  `risk_scores.csv` holds the full history.
