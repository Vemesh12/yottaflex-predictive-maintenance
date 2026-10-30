"""Telemetry readings for one machine, driven by its operating-state timeline.

Physics-inspired (not physics-accurate) model, per 30-minute slot:
  load      AR(1) around 0.85 while RUNNING, 0 otherwise.
  ambient   28 degC +/- 4 degC daily cycle (peak 15:00) + per-plant offset.
  TEMP      moves 40% of the way towards a target each slot (thermal inertia):
            RUNNING -> ambient + rise * load/0.85, IDLE -> ambient + 25% rise, else ambient.
  VIB       proportional to load when RUNNING, small residual when IDLE, ~0 when stopped.
  PRES      nominal when RUNNING, 15% residual when IDLE, ~0 when stopped.
  RPM       nominal when RUNNING, exactly 0 otherwise.
  CURR      proportional to load when RUNNING, 5% standby when IDLE, exactly 0 when stopped.

So a genuine 0 RPM / 0 A only ever appears outside RUNNING, which is what lets the validator
tell a real stop from a missing reading that was filled with 0 (Day 2 edge case).
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pyarrow as pa

from .. import config as C
from ..ids import TS_ID_FORMAT
from ..rng import stream

S = C.STATE_CODE
DECIMALS = {"TEMP": 2, "VIB": 3, "PRES": 3, "RPM": 1, "CURR": 2}
PLANT_AMBIENT_OFFSET = [0.0, -2.0, 2.0]  # Hyderabad, Pune (cooler), Chennai (hotter)

SCHEMA = pa.schema([
    ("telemetry_id", pa.string()),
    ("sensor_id", pa.string()),
    ("machine_id", pa.string()),
    ("ts", pa.timestamp("s", tz="Asia/Kolkata")),
    ("value", pa.float64()),
    ("unit", pa.string()),
])


class TimeGrid:
    """Slot timestamps shared by every machine (computed once)."""

    def __init__(self, scale: C.Scale):
        self.n = scale.slots
        times = [C.SIM_START + timedelta(minutes=i * scale.interval_min) for i in range(self.n)]
        self.epoch_s = np.array([int(t.timestamp()) for t in times], dtype=np.int64)
        self.ts_id = [t.strftime(TS_ID_FORMAT) for t in times]
        hours = np.array([t.hour + t.minute / 60 for t in times])
        self.ambient_cycle = C.AMBIENT_DAILY_AMP_C * np.sin(2 * np.pi * (hours - 9) / 24)


def machine_telemetry(machine, sensors: pd.DataFrame, state: np.ndarray, grid: TimeGrid,
                      plant_index: int, seed: int) -> pa.Table:
    rng = stream(seed, "telemetry", machine.machine_id)
    n = grid.n
    running = state == S["RUNNING"]
    idle = state == S["IDLE"]

    # Load: AR(1) process so load drifts smoothly instead of jumping every slot.
    eps = rng.normal(0, 0.03, n)
    load = np.empty(n)
    x = C.NOMINAL_LOAD
    for i in range(n):
        x = C.NOMINAL_LOAD + 0.9 * (x - C.NOMINAL_LOAD) + eps[i]
        load[i] = x
    load = np.clip(load, 0.55, 1.0) * running
    rel = load / C.NOMINAL_LOAD

    ambient = C.AMBIENT_MEAN_C + PLANT_AMBIENT_OFFSET[plant_index % 3] + grid.ambient_cycle

    columns = {}
    for sensor in sensors.itertuples():
        stype = sensor.sensor_type
        nom = float(sensor.nominal_value)
        noise = rng.normal(0, C.NOISE[stype] * nom, n)

        if stype == "TEMP":
            rise = nom - C.AMBIENT_MEAN_C
            target = np.where(running, ambient + rise * rel,
                              np.where(idle, ambient + 0.25 * rise, ambient))
            temp = np.empty(n)
            t = ambient[0]
            for i in range(n):
                t += C.THERMAL_ALPHA * (target[i] - t)
                temp[i] = t
            value = temp + noise
        elif stype == "VIB":
            jitter = np.exp(rng.normal(0, 0.08, n))
            value = np.where(running, nom * (0.85 + 0.15 * rel) * jitter,
                             np.where(idle, 0.08 * nom * jitter, 0.02 * nom * jitter)) + noise * running
        elif stype == "PRES":
            value = np.where(running, nom * (0.95 + 0.05 * rel) + noise,
                             np.where(idle, 0.15 * nom + noise * 0.5, np.abs(noise) * 0.1))
        elif stype == "RPM":
            value = np.where(running, nom + noise, 0.0)
        else:  # CURR
            value = np.where(running, nom * rel + noise, np.where(idle, 0.05 * nom + noise * 0.2, 0.0))

        value = np.clip(value, sensor.range_min, sensor.range_max)
        columns[sensor.sensor_id] = (np.round(value, DECIMALS[stype]), sensor.unit)

    sensor_ids, tel_ids, values, units = [], [], [], []
    for sid, (vals, unit) in columns.items():
        sensor_ids.extend([sid] * n)
        tel_ids.extend(f"TEL-{sid}-{t}" for t in grid.ts_id)
        values.append(vals)
        units.extend([unit] * n)

    k = len(columns)
    return pa.table({
        "telemetry_id": pa.array(tel_ids, pa.string()),
        "sensor_id": pa.array(sensor_ids, pa.string()),
        "machine_id": pa.array([machine.machine_id] * (n * k), pa.string()),
        "ts": pa.array(np.tile(grid.epoch_s, k), SCHEMA.field("ts").type),
        "value": pa.array(np.concatenate(values), pa.float64()),
        "unit": pa.array(units, pa.string()),
    }, schema=SCHEMA)
