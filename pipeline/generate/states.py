"""Operating-state timeline per machine (the "operating context" telemetry depends on).

Rules, applied in order (later rules override earlier ones):
  1. Shift calendar: PRODUCTION shifts -> RUNNING; other shifts -> SHUTDOWN.
  2. Micro-stops: inside production, a Markov chain switches RUNNING <-> IDLE.
  3. Preventive maintenance: every pm_interval_days the machine is in MAINTENANCE for 4-8 hours,
     starting at shift A on a production day.

The timeline is stored as explicit state-change records (machine_state_history), never as a
mutable "current state" column, so history is never overwritten.
"""
from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from .. import config as C
from ..rng import stream

REASONS = ["PRODUCTION", "MICRO_STOP", "NON_PRODUCTION_SHIFT", "PLANNED_PLANT_SHUTDOWN",
           "PREVENTIVE_MAINTENANCE"]
R = {r: i for i, r in enumerate(REASONS)}
S = C.STATE_CODE


def plan_machine_states(machine, plant_shifts: pd.DataFrame, scale: C.Scale, seed: int):
    """Return (state codes per slot, reason codes per slot, preventive-maintenance windows)."""
    rng = stream(seed, "states", machine.machine_id)
    n = scale.slots
    slots_per_shift = 8 * 60 // scale.interval_min
    slots_per_day = 24 * 60 // scale.interval_min

    planned = plant_shifts["planned_status"].to_numpy()
    shift_of_slot = np.arange(n) // slots_per_shift
    slot_planned = planned[shift_of_slot]

    state = np.full(n, S["SHUTDOWN"], dtype=np.int8)
    reason = np.where(slot_planned == "PLANNED_SHUTDOWN", R["PLANNED_PLANT_SHUTDOWN"],
                      R["NON_PRODUCTION_SHIFT"]).astype(np.int8)

    # Rules 1 + 2: production slots run, with Markov micro-stops.
    producing = slot_planned == "PRODUCTION"
    u = rng.random(n)
    running = True
    for i in range(n):
        if not producing[i]:
            running = True  # every production period starts in RUNNING
            continue
        if running and u[i] < C.P_RUN_TO_IDLE:
            running = False
        elif not running and u[i] < C.P_IDLE_TO_RUN:
            running = True
        state[i] = S["RUNNING"] if running else S["IDLE"]
        reason[i] = R["PRODUCTION"] if running else R["MICRO_STOP"]

    # Rule 3: preventive maintenance windows.
    pm_windows = []
    interval = int(machine.pm_interval_days)
    day = int(rng.integers(1, min(interval, scale.days)))
    while day < scale.days:
        d = day
        # Move to the next day whose shift A is a production shift.
        while d < scale.days and slot_planned[d * slots_per_day] != "PRODUCTION":
            d += 1
        if d >= scale.days:
            break
        start = d * slots_per_day
        end = min(start + int(rng.integers(8, 17)), n)  # 4-8 hours at 30-min slots
        state[start:end] = S["MAINTENANCE"]
        reason[start:end] = R["PREVENTIVE_MAINTENANCE"]
        pm_windows.append({"machine_id": machine.machine_id, "start_slot": start, "end_slot": end,
                           "maintenance_type": "PREVENTIVE"})
        day += interval

    return state, reason, pm_windows


def to_state_events(machine_id: str, state: np.ndarray, reason: np.ndarray,
                    plant_shifts: pd.DataFrame, scale: C.Scale) -> list[dict]:
    """Run-length encode the per-slot timeline into explicit state-change records."""
    slots_per_shift = 8 * 60 // scale.interval_min
    shift_ids = plant_shifts["shift_id"].to_numpy()
    key = state.astype(np.int16) * 100 + reason
    change = np.flatnonzero(np.diff(key)) + 1
    starts = np.concatenate([[0], change])
    ends = np.concatenate([change, [len(state)]])

    rows = []
    prev = None
    for s, e in zip(starts, ends):
        st = C.MACHINE_STATES[state[s]]
        rows.append({
            "machine_id": machine_id,
            "state": st,
            "previous_state": prev,
            "reason": REASONS[reason[s]],
            "start_ts": C.SIM_START + timedelta(minutes=int(s) * scale.interval_min),
            "end_ts": C.SIM_START + timedelta(minutes=int(e) * scale.interval_min),
            "duration_min": int(e - s) * scale.interval_min,
            "shift_id": shift_ids[s // slots_per_shift],
            "work_order_id": None,  # linked to preventive/corrective work orders on Day 2
        })
        prev = st
    return rows
