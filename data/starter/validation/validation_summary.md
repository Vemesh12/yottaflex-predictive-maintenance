# Validation summary: data/starter

**Overall: PASS**

## 1. Clean baseline (integrity)

83 / 83 checks passed, 0 with unexpected issues.

## 2. Injected edge cases (received data)

| Issue | Expected | Detected | True pos. | False pos. | Missed |
|---|---:|---:|---:|---:|---:|
| FAILURE_BEFORE_SYMPTOM | 2 | 2 | 2 | 0 | 0 |
| IMPOSSIBLE_UNIT | 2 | 2 | 2 | 0 | 0 |
| IMPOSSIBLE_VALUE | 8 | 8 | 8 | 0 | 0 |
| MAINTENANCE_END_BEFORE_START | 3 | 3 | 3 | 0 | 0 |
| UNKNOWN_SENSOR | 12 | 12 | 12 | 0 | 0 |
| ZERO_FILLED_GAP | 90 | 90 | 90 | 0 | 0 |

Other checks that fired on the received data:

- reconcile:technician_hours_match_work_duration: 3 (all on injected records)

## 3. Data quality (expected, informational)

- Telemetry completeness: 99.964% (26 missing of 72,000)

| Sensor fault type | Faults in ground truth | Detected by single-sensor rules | Flagged without a fault |
|---|---:|---:|---:|
| STUCK | 1 | 1 | 0 |
| SPIKES | 0 | 0 | 0 |
| BIAS | 0 | n/a: not detectable from one sensor alone; needs cross-sensor model | - |
| DROPOUT | 1 | 1 | 0 |
