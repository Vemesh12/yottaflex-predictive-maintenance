"""Generator entry point: master tables -> operating states -> telemetry -> files + manifest.

Telemetry is generated one machine at a time and appended to one Parquet file per plant, so
memory use stays flat even at 2+ million readings.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from .. import config as C
from ..io import sha256, write_csv, write_json
from . import master, states, telemetry

TABLE_FILES = {
    "plants": "plants.csv",
    "production_lines": "production_lines.csv",
    "machines": "machines.csv",
    "sensors": "sensors.csv",
    "operating_shifts": "operating_shifts.csv",
    "technicians": "technicians.csv",
    "parts": "parts.csv",
    "machine_state_history": "machine_state_history.csv",
}


def generate(scale: C.Scale, seed: int, out_dir: Path, log=print) -> dict:
    t0 = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    tel_dir = out_dir / "telemetry"
    if tel_dir.exists():
        shutil.rmtree(tel_dir)  # never mix files from an older run
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

    # 2. Operating states + telemetry, machine by machine.
    grid = telemetry.TimeGrid(scale)
    plant_of_line = dict(zip(lines["line_id"], lines["plant_id"]))
    plant_index = {p: i for i, p in enumerate(plants["plant_id"])}
    shifts_by_plant = {p: g.sort_values("start_ts").reset_index(drop=True)
                       for p, g in shifts.groupby("plant_id")}
    sensors_by_machine = {m: g for m, g in sensors.groupby("machine_id", sort=False)}

    writers: dict[str, pq.ParquetWriter] = {}
    state_rows: list[dict] = []
    pm_windows: list[dict] = []
    readings = 0
    try:
        for m in machines.itertuples():
            plant = plant_of_line[m.line_id]
            plant_shifts = shifts_by_plant[plant]
            st, rs, pm = states.plan_machine_states(m, plant_shifts, scale, seed)
            state_rows.extend(states.to_state_events(m.machine_id, st, rs, plant_shifts, scale))
            pm_windows.extend(pm)

            table = telemetry.machine_telemetry(m, sensors_by_machine[m.machine_id], st, grid,
                                                plant_index[plant], seed)
            if plant not in writers:
                writers[plant] = pq.ParquetWriter(tel_dir / f"{plant}.parquet", telemetry.SCHEMA,
                                                  compression="zstd")
            writers[plant].write_table(table)
            readings += table.num_rows
    finally:
        for w in writers.values():
            w.close()
    log(f"telemetry: {readings:,} readings over {scale.days} days")

    # 3. State history gets a sequential ID in a stable order (machine, time).
    state_history = pd.DataFrame(state_rows)
    state_history["start_ts"] = pd.to_datetime(state_history["start_ts"])
    state_history["end_ts"] = pd.to_datetime(state_history["end_ts"])
    state_history.insert(0, "state_event_id",
                         [f"MSE-{i:07d}" for i in range(1, len(state_history) + 1)])

    tables = {
        "plants": plants, "production_lines": lines, "machines": machines, "sensors": sensors,
        "operating_shifts": shifts, "technicians": technicians, "parts": parts,
        "machine_state_history": state_history,
    }
    for name, df in tables.items():
        write_csv(df, out_dir / TABLE_FILES[name])

    # 4. Manifest: row counts + checksums. No wall-clock time in it, so it is reproducible.
    files = {}
    for name, df in tables.items():
        path = out_dir / TABLE_FILES[name]
        files[TABLE_FILES[name]] = {"rows": len(df), "sha256": sha256(path)}
    for path in sorted(tel_dir.glob("*.parquet")):
        files[f"telemetry/{path.name}"] = {"rows": pq.ParquetFile(path).metadata.num_rows,
                                           "sha256": sha256(path)}
    manifest = {
        "generator_version": C.GENERATOR_VERSION,
        "seed": seed,
        "scale": scale.__dict__,
        "simulation_start": C.SIM_START.isoformat(),
        "source": "100% synthetic; no external data used",
        "files": files,
        "planned_preventive_maintenance_windows": len(pm_windows),
    }
    write_json(manifest, out_dir / "manifest.json")
    log(f"done in {time.perf_counter() - t0:.1f}s -> {out_dir}")
    return manifest
