# Assumptions and Design Decisions

Requirements that were unclear, and how they were interpreted.

## Data model and IDs
- **Nested IDs are taken literally.** `LINE-<plant-id>-001` becomes `LINE-PLT-001-001`, a machine
  is `MCH-LINE-PLT-001-001-001`, and so on. The IDs are long, but you can read any ID's parents from
  it and they can never collide.
- **Telemetry ID timestamp** uses plant local time in compact form (`20260701T060000`). All plants
  are in India (IST, +05:30, no daylight saving), so local time is unambiguous.
- **Telemetry has `machine_id` as well as `sensor_id`.** This is technically redundant, but it
  keeps time-series queries simple. A test and an FK check make sure it always equals the sensor's
  machine.
- **State history is stored as segments** (state, start, end, previous_state, reason). A change of
  *reason* with the same state (e.g. a weekend shutdown running into a planned plant shutdown) is also
  recorded as a new event, so `previous_state` can equal `state`.

## Simulation
- **Window:** 90 days from 2026-07-01 06:00 IST (the start of shift A), so every shift lies fully
  inside the window. Readings every 30 minutes → 500 sensors × 4,320 slots = **2,160,000 readings**.
  The starter scale is 30 days (it was 14 on Day 1), because failures need up to 10 days of warning
  signs inside the window.
- **Shift calendar:** three 8-hour shifts (A 06–14, B 14–22, C 22–06). Production Mon–Fri all
  shifts, Saturday A and B. Saturday night and Sunday are non-production (machines SHUTDOWN). Each
  plant also has one 2-day planned shutdown (Tue–Thu start) in the middle third of the window.
- **Micro-stops:** while producing, each 30-min slot has a 2% chance of RUNNING→IDLE and a 50%
  chance of IDLE→RUNNING.
- **Preventive maintenance:** every 30/45/60 days by criticality A/B/C, 4–8 hours starting at
  shift A on a production day.
- **Sensor values are illustrative, not engineering limits.** They are chosen so that the
  behaviour is plausible: temperature has thermal inertia and a daily ambient cycle, current and
  vibration follow load, RPM and current are exactly 0 when stopped. All constants are in
  `pipeline/config.py`.
- **Real zeros only occur when a machine is stopped.** A RUNNING machine never reads 0 RPM or 0 A.
  This lets the next phase tell "sensor gap hidden as zero" apart from a genuine stop.

## Failures (documented rules, not random labels)
- **When a machine fails** comes from a daily hazard rule:
  `BASE[machine_type] × (1 + 0.04 × age_years) × (0.4 + wear²)`, where
  `wear = days since last service / PM interval` and service = preventive maintenance or a repair.
  Older machines and machines overdue for maintenance fail more often. One random number per
  machine-day is compared with the hazard.
- **Constraints on a failure:** it happens in a RUNNING slot. Its whole warning window and repair fit
  inside the 90 days. It does not overlap a preventive-maintenance window, on the reasoning that an
  inspection during the warning window would have caught the defect. The next warning window can only
  start 2 days after the previous repair.
- **Result:** 160 failures at full scale (144–185 across 8 seeds tested). 92 of 100 machines fail at
  least once. That is high for a real plant, but the brief requires 100–200 failures on 100 machines
  in 90 days.
- **Failure modes per machine type** are limited to modes for which a compatible spare part exists
  (e.g. hydraulic presses have no bearing failures).
- **Warning signs:** drift grows as `progress²` (slow at first, then accelerating) over 3–10 days
  (1–3 days for electrical faults). Each mode has its own signature, e.g. bearing wear makes
  vibration reach about 2.6× normal and adds +8 °C; pressure loss lowers pressure by 30%.
- **Two different "symptom" timestamps:** the *true onset* of degradation is in ground truth only.
  `failure_event.first_symptom_ts` is when someone *recorded* a symptom, at 30–80% of the way
  through the warning window. Gradual modes must have one before the failure. Electrical faults may
  be sudden, so it can be NULL for them; this is how "where prohibited" was interpreted.
- **After a failure:** FAILED until a technician arrives (0.5–4 h depending on criticality), then
  MAINTENANCE (CORRECTIVE_REPAIR) for the mode's repair time, then back to the normal schedule.
  Repairs are done whatever the shift (on-call technicians).
- **Cancelled preventive jobs:** a PM due within 3 days after a repair is cancelled, because the
  repair already covered it. 21 of 209 PM work orders at full scale.

## Sensor faults vs machine faults
- A sensor fault affects **one** sensor (TEMP, VIB or PRES), never changes the machine's state, and
  never overlaps a failure on the same machine. It is fixed by a SENSOR_REPLACEMENT work order with
  no downtime (sensors are hot-swapped).
- Types: STUCK (frozen value), SPIKES (15% of readings 2.5–4× too high), BIAS (calibration offset),
  DROPOUT (no value, stored as NULL). 27 faults at full scale.
- BIAS cannot be detected by looking at one sensor alone. Telling it apart from real drift needs a
  cross-sensor model (planned for the risk engine). The validator reports this rather than hiding it.

## Bad-data scenarios and validation
- The 5 required scenarios are written to `exceptions/` and never mixed into the clean files. The
  validator builds the "as received" dataset itself (exception rows replace the clean row with the
  same ID, or are added if the ID is new).
- The exception files have no label column. Labels exist only in `ground_truth/`, which the validator
  reads *after* running its checks, purely to score them.
- A wrong-unit reading (°F instead of °C) is reported as IMPOSSIBLE_UNIT only; its value is not
  range-checked, because a value in the wrong unit cannot be compared to the sensor's range.
- "Gaps hidden as zero" is detected as a reading of exactly 0 while the machine is RUNNING. This
  works because healthy telemetry never reads 0 while running (designed in Day 1).

## Exports
- Telemetry is exported as Parquet, plus a 1,000-row JSON sample. 2.16M readings as JSON would be
  about 400 MB. `seed.sql` loads telemetry from the Parquet files with one statement.

## Reproducibility
- Each part of the generator has its own random stream derived from `(seed, name)`, e.g.
  `(20261022, "telemetry", machine_id)`. Generating machines in a different order, or adding a new
  stream later, does not change existing numbers.
- The manifest contains no wall-clock time, so two runs with the same seed give identical
  `manifest.json` files and identical SHA-256 checksums for every file.

## Technology
- **DuckDB instead of PostgreSQL:** reviewers can run everything with `pip install` and no database
  server. DuckDB still enforces PK/FK/CHECK constraints and reads Parquet directly.
- **Parquet for telemetry:** 2.16M rows compress to about 12 MB; written one machine at a time so
  memory stays flat.
- **No external data.** 100% synthetic, so there are no licensing or privacy concerns.
