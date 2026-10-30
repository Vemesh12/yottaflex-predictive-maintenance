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
