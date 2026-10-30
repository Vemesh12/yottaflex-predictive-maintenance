# Risk engine evaluation

Label: machine fails within 7 days after the evaluation time. Evaluation points: one per machine per day at 06:00.

| Split | Eval days | Points | Failures |
|---|---|---:|---:|
| train | 1-9 | 30 | 0 |
| validation | 10-19 | 40 | 1 |
| test | 20-29 | 39 | 1 |

Alert level chosen on validation: **CRITICAL or above**.

## Test results (chosen level)

| Metric | Value |
|---|---:|
| precision (machine-days) | None |
| recall (machine-days) | 0.0 |
| f1 (machine-days) | 0.0 |
| false positive rate (machine-days) | 0.0 |
| failures detected before they happened | 0 / 1 (0.0) |
| median lead time (hours) | None |
| mean lead time (hours) | None |

Confusion matrix (test machine-days):

| | predicted alert | predicted no alert |
|---|---:|---:|
| fails within 7 days | 0 | 3 |
| does not fail | 0 | 36 |

## Test results by alert level

| Level | Precision | Recall | F1 | FPR |
|---|---:|---:|---:|---:|
| MEDIUM+ | 1.0 | 1.0 | 1.0 | 0.0 |
| HIGH+ | None | 0.0 | 0.0 | 0.0 |
| CRITICAL+ | None | 0.0 | 0.0 | 0.0 |

## By failure mode (test)

| Mode | Failures | Detected | Median lead (h) |
|---|---:|---:|---:|
| IMBALANCE | 1 | 0 | None |

## Baselines (test)

| Approach | Precision | Recall | F1 | FPR | Failures detected |
|---|---:|---:|---:|---:|---:|
| **Risk engine** | None | 0.0 | 0.0 | 0.0 | 0 / 1 |
| maintenance_overdue_only | None | 0.0 | 0.0 | 0.0 | 0 / 1 |
| single_sensor_normal_band | 1.0 | 0.6667 | 0.8 | 0.0 | 1 / 1 |

## Sensor faults (all splits)

| Fault type | Faults | Eval points during fault | Sensor alert raised | Machine alert raised |
|---|---:|---:|---:|---:|
| DROPOUT | 1 | 1 | 0 | 0 |
| STUCK | 1 | 3 | 2 | 0 |
