"""Generator entry point.

  1. master tables (parents first)
  2. per machine: shift calendar + micro-stops + PM -> failures -> sensor faults
                  -> final state timeline -> telemetry (with drift + faults) -> Parquet
  3. work orders, failure events, bridges and status history; downtime from state history
  4. clean CSVs
  5. deliberate bad-data scenarios -> exceptions/, labels -> ground_truth/
  6. JSON + SQL exports, then manifest (row counts + SHA-256 of every file)

Telemetry is generated one machine at a time and appended to one Parquet file per plant, so
memory use stays flat even at 2+ million readings.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .. import config as C
from ..export import export_all, write_json as write_json_records
from ..io import sha256, write_csv, write_json
from . import anomalies, failures, faults, maintenance, master, states, telemetry

TABLE_FILES = {
    "plants": "plants.csv",
    "production_lines": "production_lines.csv",
    "machines": "machines.csv",
    "sensors": "sensors.csv",
    "operating_shifts": "operating_shifts.csv",
    "technicians": "technicians.csv",
    "parts": "parts.csv",
    "machine_state_history": "machine_state_history.csv",
    "failure_events": "failure_events.csv",
    "maintenance_work_orders": "maintenance_work_orders.csv",
    "work_order_parts": "work_order_parts.csv",
    "work_order_technicians": "work_order_technicians.csv",
    "work_order_status_history": "work_order_status_history.csv",
}
GENERATED_DIRS = ["telemetry", "exceptions", "ground_truth", "export"]


def plan_machine(m, plant_shifts: pd.DataFrame, machine_sensors: pd.DataFrame, scale: C.Scale,
                 seed: int) -> dict:
    """Everything that happens to one machine, before any telemetry is produced."""
    st, rs, pm = states.plan_machine_states(m, plant_shifts, scale, seed)
    fails = failures.plan_failures(m, st, pm, scale, seed)
    sfaults = faults.plan_sensor_faults(machine_sensors, fails, scale, seed)

    # Work items for this machine; their list index is the per-slot work-order reference.
    items = ([{"kind": "PREVENTIVE", "pm": w} for w in pm]
             + [{"kind": "CORRECTIVE", "failure": f} for f in fails]
             + [{"kind": "SENSOR_REPLACEMENT", "fault": f} for f in sfaults])
    for ref, it in enumerate(items):
        it.update(machine_id=m.machine_id, ref=ref)
    wo_ref = np.full(scale.slots, -1, dtype=np.int32)
    failures.apply_to_timeline(st, rs, wo_ref, fails, list(range(len(pm), len(pm) + len(fails))),
                               pm, list(range(len(pm))), scale)
    return {"state": st, "reason": rs, "wo_ref": wo_ref, "pm": pm, "failures": fails,
            "sensor_faults": sfaults, "items": items}


def generate(scale: C.Scale, seed: int, out_dir: Path, log=print) -> dict:
    t0 = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    for d in GENERATED_DIRS:
        if (out_dir / d).exists():
            shutil.rmtree(out_dir / d)  # never mix files from an older run
    tel_dir = out_dir / "telemetry"
    tel_dir.mkdir()

    # 1. Parents first, then children.
    plants = master.build_plants(scale, seed)
    lines = master.build_lines(plants, scale, seed)
    machines = master.build_machines(lines, scale, seed)
    sensors = master.build_sensors(machines, scale, seed)
    shifts = master.build_shifts(plants, scale, seed)
    technicians = master.build_technicians(plants, scale, seed)
    parts = master.build_parts()
    log(f"master data: {len(plants)} plants, {len(lines)} lines, {len(machines)} machines, "
        f"{len(sensors)} sensors, {len(shifts)} shifts")

    # 2. Per machine: plan events, then telemetry.
    grid = telemetry.TimeGrid(scale)
    plant_of_line = dict(zip(lines["line_id"], lines["plant_id"]))
    plant_index = {p: i for i, p in enumerate(plants["plant_id"])}
    shifts_by_plant = {p: g.sort_values("start_ts").reset_index(drop=True)
                       for p, g in shifts.groupby("plant_id")}
    sensors_by_machine = {m: g for m, g in sensors.groupby("machine_id", sort=False)}

    writers: dict[str, pq.ParquetWriter] = {}
    state_rows, items, failure_plans, sensor_faults = [], [], [], []
    states_by_machine = {}
    pm_count = readings = 0
    try:
        for m in machines.itertuples():
            plant = plant_of_line[m.line_id]
            plant_shifts = shifts_by_plant[plant]
            plan = plan_machine(m, plant_shifts, sensors_by_machine[m.machine_id], scale, seed)
            state_rows.extend(states.to_state_events(m.machine_id, plan["state"], plan["reason"],
                                                     plant_shifts, scale, plan["wo_ref"]))
            items.extend(plan["items"])
            failure_plans.extend(plan["failures"])
            sensor_faults.extend(plan["sensor_faults"])
            states_by_machine[m.machine_id] = plan["state"]
            pm_count += len(plan["pm"])

            drift = failures.drift_profile(plan["failures"], scale.slots) if plan["failures"] else None
            table = telemetry.machine_telemetry(m, sensors_by_machine[m.machine_id], plan["state"],
                                                grid, plant_index[plant], seed, drift=drift,
                                                faults=plan["sensor_faults"])
            if plant not in writers:
                writers[plant] = pq.ParquetWriter(tel_dir / f"{plant}.parquet", telemetry.SCHEMA,
                                                  compression="zstd")
            writers[plant].write_table(table)
            readings += table.num_rows
    finally:
        for w in writers.values():
            w.close()
    log(f"telemetry: {readings:,} readings over {scale.days} days; "
        f"{len(failure_plans)} failures, {len(sensor_faults)} sensor faults")

    # 3. Work orders etc., then link state records to real WO IDs and derive downtime.
    mt = maintenance.build(machines, lines, technicians, parts, items, scale, seed)
    state_history = pd.DataFrame(state_rows)
    state_history["start_ts"] = pd.to_datetime(state_history["start_ts"])
    state_history["end_ts"] = pd.to_datetime(state_history["end_ts"])
    state_history["work_order_id"] = state_history["work_order_id"].map(mt["key_map"])
    state_history.insert(0, "state_event_id",
                         [f"MSE-{i:07d}" for i in range(1, len(state_history) + 1)])
    maintenance.finalize(mt, state_history, machines)
    log(f"maintenance: {len(mt['maintenance_work_orders'])} work orders, "
        f"{len(mt['failure_events'])} failure events")

    # 4. Clean baseline files.
    tables = {
        "plants": plants, "production_lines": lines, "machines": machines, "sensors": sensors,
        "operating_shifts": shifts, "technicians": technicians, "parts": parts,
        "machine_state_history": state_history,
        **{k: v for k, v in mt.items() if k != "key_map"},
    }
    rows = {}
    for name, df in tables.items():
        write_csv(df, out_dir / TABLE_FILES[name])
        rows[TABLE_FILES[name]] = len(df)
    for path in sorted(tel_dir.glob("*.parquet")):
        rows[f"telemetry/{path.name}"] = pq.ParquetFile(path).metadata.num_rows

    # 5. Bad-data scenarios (separate folder) and ground truth (separate folder).
    exceptions, ground_truth = anomalies.build(tables, states_by_machine, failure_plans,
                                               sensor_faults, scale, seed)
    (out_dir / "exceptions").mkdir()
    for name, df in exceptions.items():
        write_csv(df, out_dir / "exceptions" / f"{name}.csv")
        rows[f"exceptions/{name}.csv"] = len(df)
    (out_dir / "ground_truth").mkdir()
    write_csv(ground_truth, out_dir / "ground_truth" / "ground_truth.csv")
    write_json_records(ground_truth, out_dir / "ground_truth" / "ground_truth.json")
    rows["ground_truth/ground_truth.csv"] = rows["ground_truth/ground_truth.json"] = len(ground_truth)
    log(f"edge cases: {len(ground_truth[ground_truth['category'] == 'INJECTED_ANOMALY'])} injected "
        f"records; ground truth: {len(ground_truth)} labels")

    # 6. Exports, then manifest. No wall-clock time in the manifest, so it is reproducible.
    rows.update(export_all(out_dir, {TABLE_FILES[k]: v for k, v in tables.items()}, ground_truth))
    files = {rel: {"rows": n, "sha256": sha256(out_dir / rel)} for rel, n in rows.items()}
    manifest = {
        "generator_version": C.GENERATOR_VERSION,
        "seed": seed,
        "scale": scale.__dict__,
        "simulation_start": C.SIM_START.isoformat(),
        "source": "100% synthetic; no external data used",
        "generator_command": f"python -m pipeline generate --scale {scale.name} --seed {seed}",
        "files": files,
        "summary": {
            "telemetry_readings": readings,
            "failure_events": len(mt["failure_events"]),
            "sensor_faults": len(sensor_faults),
            "work_orders": mt["maintenance_work_orders"]["work_order_type"].value_counts().sort_index().to_dict(),
            "planned_preventive_maintenance_windows": pm_count,
            "injected_anomaly_records": int((ground_truth["category"] == "INJECTED_ANOMALY").sum()),
        },
    }
    write_json(manifest, out_dir / "manifest.json")
    log(f"done in {time.perf_counter() - t0:.1f}s -> {out_dir}")
    return manifest
