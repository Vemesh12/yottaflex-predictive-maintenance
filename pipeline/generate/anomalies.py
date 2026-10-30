"""Deliberate bad-data scenarios (the 5 required edge cases) and the ground-truth file.

The clean baseline is never modified. Each scenario is written to exceptions/ as the record
"as it arrived" from the plant:
  - a record whose ID also exists in the clean data REPLACES it (a corrupted delivery),
  - a record with a new ID is ADDED (e.g. telemetry from a sensor that does not exist).
The validator builds this "received" view itself. The exception files carry NO label column:
what each record is wrong with is written only to ground_truth/, so the validator has to
find the problems on its own and ground truth is used afterwards only to score it.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from .. import config as C
from .. import ids
from ..rng import stream
from .states import S

GT_COLUMNS = ["gt_id", "category", "issue_type", "entity", "record_id", "machine_id", "sensor_id",
              "start_ts", "end_ts", "expected_decision", "related_id", "rule"]


def _ts(slot: int, scale: C.Scale):
    return C.SIM_START + timedelta(minutes=int(slot) * scale.interval_min)


def build(tables: dict, states_by_machine: dict, failure_plans: list[dict], sensor_faults: list[dict],
          scale: C.Scale, seed: int) -> tuple[dict, pd.DataFrame]:
    rng = stream(seed, "anomalies")
    sensors = tables["sensors"]
    machines = tables["machines"]
    machine_ids = machines["machine_id"].tolist()
    by_machine_type = {(r.machine_id, r.sensor_type): r for r in sensors.itertuples()}
    used: set[tuple[str, int]] = set()  # (machine_id, slot) already used by a scenario
    fault_windows = [(f["machine_id"], f["start_slot"], f["end_slot"]) for f in sensor_faults]

    def clean_running_window(machine_id: str, length: int) -> int:
        """Random start of `length` consecutive RUNNING slots, clear of faults and other picks."""
        run = (states_by_machine[machine_id] == S["RUNNING"]).astype(int)
        ok = np.convolve(run, np.ones(length, dtype=int), "valid") == length
        starts = [s for s in np.flatnonzero(ok)
                  if not any((machine_id, s + k) in used for k in range(length))
                  and not any(m == machine_id and a < s + length and b > s for m, a, b in fault_windows)]
        s = int(starts[int(rng.integers(0, len(starts)))])
        used.update((machine_id, s + k) for k in range(length))
        return s

    def reading(sensor_id, machine_id, slot, value, unit):
        return {"telemetry_id": f"TEL-{sensor_id}-{_ts(slot, scale).strftime(ids.TS_ID_FORMAT)}",
                "sensor_id": sensor_id, "machine_id": machine_id, "ts": _ts(slot, scale),
                "value": value, "unit": unit}

    tel, gt = [], []

    def label(issue, entity, record_id, machine_id, sensor_id, start, end, decision, rule):
        gt.append({"category": "INJECTED_ANOMALY", "issue_type": issue, "entity": entity,
                   "record_id": record_id, "machine_id": machine_id, "sensor_id": sensor_id,
                   "start_ts": start, "end_ts": end, "expected_decision": decision,
                   "related_id": None, "rule": rule})

    # 1. Telemetry from unknown sensors: a 2nd TEMP sensor that was never registered on a real
    #    machine, and a sensor on a machine that does not exist.
    m1, m2 = (str(m) for m in rng.choice(machine_ids, 2, replace=False))
    line2 = machines.set_index("machine_id").loc[m2, "line_id"]
    ghost_machine = ids.machine_id(line2, 99)
    for sensor_id, machine_id, stype in [(ids.sensor_id(m1, "TEMP", 2), m1, "TEMP"),
                                         (ids.sensor_id(ghost_machine, "VIB", 1), ghost_machine, "VIB")]:
        nominal = C.BASELINE["PUMP"][stype]
        start = int(rng.integers(0, scale.slots - 6))
        for k in range(6):
            r = reading(sensor_id, machine_id, start + k, round(nominal * float(rng.normal(1, 0.02)), 2),
                        C.SENSOR_UNITS[stype])
            tel.append(r)
            label("UNKNOWN_SENSOR", "telemetry_event", r["telemetry_id"], machine_id, sensor_id,
                  r["ts"], r["ts"], "QUARANTINE", "sensor_id not in sensor master data")

    # 2a. Physically impossible values: outside the instrument range of a real sensor.
    for k in range(8):
        m = str(rng.choice(machine_ids))
        stype = C.SENSOR_TYPES[k % len(C.SENSOR_TYPES)]
        s = by_machine_type[(m, stype)]
        slot = clean_running_window(m, 1)
        value = (round(s.range_max * 1.5, 2) if k % 2 == 0
                 else round(s.range_min - max(1.0, 0.1 * s.nominal_value), 2))
        r = reading(s.sensor_id, m, slot, value, s.unit)
        tel.append(r)
        label("IMPOSSIBLE_VALUE", "telemetry_event", r["telemetry_id"], m, s.sensor_id, r["ts"], r["ts"],
              "REJECT_READING", "value outside sensor range_min..range_max")

    # 2b. Impossible unit: a reading delivered in a unit the sensor does not report.
    for stype, unit, convert in [("TEMP", "degF", lambda v: v * 1.8 + 32), ("PRES", "psi", lambda v: v * 14.5)]:
        m = str(rng.choice(machine_ids))
        s = by_machine_type[(m, stype)]
        slot = clean_running_window(m, 1)
        r = reading(s.sensor_id, m, slot, round(convert(s.nominal_value), 2), unit)
        tel.append(r)
        label("IMPOSSIBLE_UNIT", "telemetry_event", r["telemetry_id"], m, s.sensor_id, r["ts"], r["ts"],
              "REJECT_READING", "unit differs from the sensor's registered unit")

    # 3. Sensor time gaps hidden as zero: a gateway outage while the machine was RUNNING,
    #    delivered as 0.0 on all 5 sensors instead of "no value".
    for _ in range(3):
        m = str(rng.choice(machine_ids))
        start = clean_running_window(m, 6)
        for stype in C.SENSOR_TYPES:
            s = by_machine_type[(m, stype)]
            for k in range(6):
                r = reading(s.sensor_id, m, start + k, 0.0, s.unit)
                tel.append(r)
                label("ZERO_FILLED_GAP", "telemetry_event", r["telemetry_id"], m, s.sensor_id,
                      r["ts"], r["ts"], "TREAT_AS_MISSING",
                      "reading is exactly 0 while the machine is RUNNING")

    # 4. Failure recorded before its symptom, for modes that must show a symptom first.
    fe = tables["failure_events"]
    gradual = fe[fe["failure_mode"].isin(C.GRADUAL_MODES) & fe["first_symptom_ts"].notna()]
    picks = gradual.iloc[sorted(rng.choice(len(gradual), min(3, len(gradual)), replace=False))].copy()
    picks["first_symptom_ts"] = [t + timedelta(hours=int(rng.integers(2, 13))) for t in picks["failure_ts"]]
    for r in picks.itertuples():
        label("FAILURE_BEFORE_SYMPTOM", "failure_event", r.failure_id, r.machine_id, None,
              r.first_symptom_ts, r.failure_ts, "FLAG_FOR_REVIEW",
              "gradual failure mode must have first_symptom_ts < failure_ts")

    # 5. Maintenance that ends before it starts (start and end swapped on entry).
    wo = tables["maintenance_work_orders"]
    done = wo[(wo["status"] == "COMPLETED") & (wo["work_order_type"] != "SENSOR_REPLACEMENT")]
    wo_picks = done.iloc[sorted(rng.choice(len(done), 3, replace=False))].copy()
    wo_picks["start_ts"], wo_picks["end_ts"] = wo_picks["end_ts"].copy(), wo_picks["start_ts"].copy()
    for r in wo_picks.itertuples():
        label("MAINTENANCE_END_BEFORE_START", "maintenance_work_order", r.work_order_id, r.machine_id,
              None, r.start_ts, r.end_ts, "REJECT_WORK_ORDER", "end_ts must not be before start_ts")

    exceptions = {
        "telemetry_exceptions": _with_ts(pd.DataFrame(tel), ["ts"]),
        "failure_event_exceptions": picks.reset_index(drop=True),
        "work_order_exceptions": wo_picks.reset_index(drop=True),
    }
    return exceptions, _ground_truth(tables, failure_plans, sensor_faults, gt, scale)


def _ground_truth(tables: dict, failure_plans: list[dict], sensor_faults: list[dict],
                  injected: list[dict], scale: C.Scale) -> pd.DataFrame:
    rows = []
    fe = tables["failure_events"].set_index(["machine_id", "failure_ts"])
    wo = tables["maintenance_work_orders"]
    for f in sorted(failure_plans, key=lambda f: (f["failure_slot"], f["machine_id"])):
        failure_id = fe.loc[(f["machine_id"], pd.Timestamp(_ts(f["failure_slot"], scale)))].failure_id
        rows.append({"category": "MACHINE_FAILURE", "issue_type": f["failure_mode"],
                     "entity": "failure_event", "record_id": failure_id, "machine_id": f["machine_id"],
                     "sensor_id": None, "start_ts": _ts(f["onset_slot"], scale),
                     "end_ts": _ts(f["failure_slot"], scale),
                     "expected_decision": "ELEVATED_RISK_BEFORE_FAILURE",
                     "related_id": wo.loc[wo["failure_id"] == failure_id, "work_order_id"].iloc[0],
                     "rule": "start_ts = true onset of degradation; telemetry drifts until end_ts"})
    sensor_wo = wo[wo["work_order_type"] == "SENSOR_REPLACEMENT"]
    for f in sorted(sensor_faults, key=lambda f: (f["start_slot"], f["sensor_id"])):
        end = _ts(f["end_slot"], scale)
        related = sensor_wo[(sensor_wo["sensor_id"] == f["sensor_id"]) & (sensor_wo["end_ts"] == end)]
        rows.append({"category": "SENSOR_FAULT", "issue_type": f["fault_type"], "entity": "sensor",
                     "record_id": f["sensor_id"], "machine_id": f["machine_id"],
                     "sensor_id": f["sensor_id"], "start_ts": _ts(f["start_slot"], scale),
                     "end_ts": end, "expected_decision": "SENSOR_FAULT_NOT_MACHINE_FAULT",
                     "related_id": related["work_order_id"].iloc[0],
                     "rule": "one sensor misbehaves; other sensors and operating state stay normal"})
    rows.extend(injected)
    gt = pd.DataFrame(rows, columns=GT_COLUMNS[1:])
    gt.insert(0, "gt_id", [f"GT-{i:06d}" for i in range(1, len(gt) + 1)])
    return _with_ts(gt, ["start_ts", "end_ts"])


def _with_ts(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_datetime(df[c]).dt.tz_convert(C.TZ)
    return df
