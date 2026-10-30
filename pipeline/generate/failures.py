"""Machine failures: when they happen (a documented hazard rule), how they change the
operating timeline, and the gradual telemetry drift that precedes them.

Timeline of one failure (slot = 30 min):

    onset ............ first_symptom ........ failure | FAILED (waiting) | REPAIR | back to schedule
    |<---- degradation: drift grows as progress^2 --->|<- response ---->|<- repair hours ->|

- onset          true start of degradation (ground truth only)
- first_symptom  when someone recorded a symptom (operational record, between onset and failure)
- failure        always during a RUNNING slot
"""
from __future__ import annotations

import numpy as np

from .. import config as C
from ..rng import stream
from .states import R, S


def plan_failures(machine, state: np.ndarray, pm_windows: list[dict], scale: C.Scale,
                  seed: int) -> list[dict]:
    rng = stream(seed, "failures", machine.machine_id)
    days, n = scale.days, scale.slots
    spd = 24 * 60 // scale.interval_min
    # One draw of each kind per day, used or not, so the sequence never depends on outcomes.
    u, mode_u, sym_u, slot_u, resp_u, rep_u, rec_u = (rng.random(days) for _ in range(7))

    age_years = (C.SIM_START.date() - machine.install_date).days / 365.25
    base = C.FAILURE_BASE_DAILY_HAZARD[machine.machine_type] * (1 + C.AGE_HAZARD_PER_YEAR * age_years)
    interval = int(machine.pm_interval_days)
    pm_days = sorted({w["start_slot"] // spd for w in pm_windows})
    # Before the first PM in the window, the previous PM happened one interval earlier.
    last_service = pm_days[0] - interval if pm_days else -interval // 2

    modes = list(C.FAILURE_MODE_WEIGHTS[machine.machine_type])
    cum = np.cumsum(list(C.FAILURE_MODE_WEIGHTS[machine.machine_type].values()))
    failures: list[dict] = []
    earliest_onset = 0
    for d in range(days):
        if d in pm_days:
            last_service = d
        wear = (d - last_service) / interval
        if u[d] >= base * (0.4 + wear ** 2):
            continue

        mode = modes[int(np.searchsorted(cum, mode_u[d] * cum[-1], side="right"))]
        lo, hi = C.SYMPTOM_DAYS[mode]
        symptom_days = min(hi, lo + int(sym_u[d] * (hi - lo + 1)))
        running = np.flatnonzero(state[d * spd:(d + 1) * spd] == S["RUNNING"])
        if len(running) == 0:
            continue  # machines only fail while running
        fail = d * spd + int(running[int(slot_u[d] * len(running))])
        onset = fail - symptom_days * spd
        if onset < earliest_onset:
            continue  # warning window must be fully inside the simulation, after the last repair

        lo, hi = C.RESPONSE_SLOTS[machine.criticality]
        repair_start = fail + min(hi, lo + int(resp_u[d] * (hi - lo + 1)))
        lo, hi = C.REPAIR_HOURS[mode]
        repair_hours = min(hi, lo + int(rep_u[d] * (hi - lo + 1)))
        end = repair_start + repair_hours * 60 // scale.interval_min
        if end > n:
            continue  # the repair must finish inside the window so the work order is complete
        if any(w["start_slot"] < end and w["end_slot"] > onset for w in pm_windows):
            continue  # a PM inside the warning window would have caught the defect

        if mode in C.GRADUAL_MODES:
            frac = 0.3 + 0.5 * rec_u[d]
        else:  # sudden mode: half the time nobody recorded a symptom
            frac = None if rec_u[d] < 0.5 else 0.3 + (rec_u[d] - 0.5)
        first_symptom = None if frac is None else onset + int(frac * (fail - onset))

        failures.append({
            "machine_id": machine.machine_id, "failure_mode": mode, "onset_slot": onset,
            "first_symptom_slot": first_symptom, "failure_slot": fail,
            "repair_start_slot": repair_start, "end_slot": end,
        })
        last_service = end // spd
        earliest_onset = end + C.MIN_DAYS_BETWEEN_FAILURE_EVENTS * spd
    return failures


def apply_to_timeline(state: np.ndarray, reason: np.ndarray, wo_ref: np.ndarray,
                      failures: list[dict], failure_refs: list[int],
                      pm_windows: list[dict], pm_refs: list[int], scale: C.Scale) -> None:
    """Write failures and PM jobs into the per-slot arrays (in place) and link them to their
    work items. A PM due within PM_CANCEL_AFTER_REPAIR_DAYS after a repair is cancelled and the
    machine does what it would have done without it."""
    spd = 24 * 60 // scale.interval_min
    for w, ref in zip(pm_windows, pm_refs):
        s, e = w["start_slot"], w["end_slot"]
        causes = [f["end_slot"] for f in failures
                  if f["end_slot"] <= s < f["end_slot"] + C.PM_CANCEL_AFTER_REPAIR_DAYS * spd]
        w["cancelled"] = bool(causes)
        w["cancel_slot"] = causes[0] if causes else None  # cancelled when that repair finished
        if w["cancelled"]:
            state[s:e] = w["prior_state"]
            reason[s:e] = w["prior_reason"]
        else:
            wo_ref[s:e] = ref
    for f, ref in zip(failures, failure_refs):
        fs, rs, e = f["failure_slot"], f["repair_start_slot"], f["end_slot"]
        state[fs:rs], reason[fs:rs] = S["FAILED"], R["BREAKDOWN"]
        state[rs:e], reason[rs:e] = S["MAINTENANCE"], R["CORRECTIVE_REPAIR"]
        wo_ref[fs:e] = ref


def drift_profile(failures: list[dict], n: int) -> dict:
    """Per sensor type: multiplier and additive arrays that bend telemetry before each failure."""
    mult = {t: np.ones(n) for t in C.SENSOR_TYPES}
    add = {t: np.zeros(n) for t in C.SENSOR_TYPES}
    for f in failures:
        s, e = f["onset_slot"], f["failure_slot"]
        progress = ((np.arange(s, e) - s) / (e - s)) ** 2
        for stype, (kind, g) in C.FAILURE_SIGNATURE[f["failure_mode"]].items():
            if kind == "mult":
                mult[stype][s:e] *= 1 + g * progress
            else:
                add[stype][s:e] += g * progress
    return {"mult": mult, "add": add}
