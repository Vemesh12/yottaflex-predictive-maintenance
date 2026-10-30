"""Sensor faults: one sensor reports wrong data while the machine itself is healthy.

This is what makes sensor faults distinguishable from machine faults:
  - a fault touches exactly ONE sensor; the machine's other 4 sensors stay normal,
  - it never changes the operating state (no downtime),
  - it never overlaps a machine failure's warning window or repair on the same machine,
  - it ends when an instrumentation technician replaces the sensor (SENSOR_REPLACEMENT WO).

Fault types:
  STUCK    the reading freezes at the value it had when the fault started
  SPIKES   ~15% of readings jump to 2.5-4x the true value
  BIAS     constant calibration offset (+12 degC, +50% vibration, +15% pressure)
  DROPOUT  no value is delivered (stored as NULL, never as 0)
"""
from __future__ import annotations

import numpy as np

from .. import config as C
from ..rng import stream


def plan_sensor_faults(sensors, failures: list[dict], scale: C.Scale, seed: int) -> list[dict]:
    days, n = scale.days, scale.slots
    spd = 24 * 60 // scale.interval_min
    lo, hi = C.SENSOR_FAULT_SLOTS
    faults = []
    for sensor in sensors.itertuples():
        if sensor.sensor_type not in C.FAULT_SENSOR_TYPES:
            continue
        rng = stream(seed, "sensor_faults", sensor.sensor_id)
        u = rng.random(days)
        blocked = 0
        for d in range(days):
            if u[d] >= C.SENSOR_FAULT_DAILY_HAZARD:
                continue
            ftype = str(rng.choice(C.SENSOR_FAULT_TYPES, p=C.SENSOR_FAULT_WEIGHTS))
            start = d * spd + int(rng.integers(0, spd))
            end = start + int(rng.integers(lo, hi + 1))
            if start < blocked or end >= n:
                continue
            if any(f["onset_slot"] < end and f["end_slot"] > start for f in failures):
                continue
            faults.append({"machine_id": sensor.machine_id, "sensor_id": sensor.sensor_id,
                           "sensor_type": sensor.sensor_type, "fault_type": ftype,
                           "start_slot": start, "end_slot": end})
            blocked = end + spd
    return faults


def apply_fault(values: np.ndarray, fault: dict, nominal: float, seed: int) -> np.ndarray:
    """Return a copy of one sensor's readings with the fault applied to [start, end)."""
    v = values.copy()
    s, e = fault["start_slot"], fault["end_slot"]
    kind, stype = fault["fault_type"], fault["sensor_type"]
    if kind == "STUCK":
        v[s:e] = v[s]
    elif kind == "SPIKES":
        rng = stream(seed, "spikes", fault["sensor_id"], s)  # own stream: other sensors unaffected
        hit = rng.random(e - s) < 0.15
        v[s:e] = np.where(hit, v[s:e] * rng.uniform(2.5, 4.0, e - s), v[s:e])
    elif kind == "BIAS":
        v[s:e] += C.SENSOR_BIAS[stype] if stype == "TEMP" else C.SENSOR_BIAS[stype] * nominal
    elif kind == "DROPOUT":
        v[s:e] = np.nan
    return v
