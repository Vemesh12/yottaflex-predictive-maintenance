"""Master (parent) tables: Plant -> ProductionLine -> Machine -> Sensor, plus OperatingShift,
Technician and Part. Parents are always built before children and children only use parent IDs
taken from the parent DataFrame, so foreign keys are valid by construction (and re-checked in tests).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .. import config as C
from .. import ids
from ..rng import stream


def _random_date(rng: np.random.Generator, start: date, end: date) -> date:
    return start + timedelta(days=int(rng.integers(0, (end - start).days + 1)))


def build_plants(scale: C.Scale, seed: int) -> pd.DataFrame:
    rng = stream(seed, "plants")
    rows = []
    for i in range(scale.plants):
        name, city, state = C.PLANTS[i % len(C.PLANTS)]
        rows.append({
            "plant_id": ids.plant_id(i + 1),
            "plant_name": name,
            "city": city,
            "state": state,
            "country": "India",
            "timezone": "Asia/Kolkata",
            "commissioned_date": _random_date(rng, date(2008, 1, 1), date(2014, 12, 31)),
            "status": "ACTIVE",
        })
    return pd.DataFrame(rows)


PRODUCT_FAMILIES = ["Fluid handling", "Air systems", "Metal forming", "Precision machining"]


def build_lines(plants: pd.DataFrame, scale: C.Scale, seed: int) -> pd.DataFrame:
    rng = stream(seed, "lines")
    rows = []
    for plant in plants.itertuples():
        for n in range(1, scale.lines_per_plant + 1):
            rows.append({
                "line_id": ids.line_id(plant.plant_id, n),
                "plant_id": plant.plant_id,
                "line_name": f"{plant.city} Line {n}",
                "product_family": PRODUCT_FAMILIES[(n - 1) % len(PRODUCT_FAMILIES)],
                # A line cannot be commissioned before its plant.
                "commissioned_date": _random_date(rng, plant.commissioned_date, date(2016, 12, 31)),
                "status": "ACTIVE",
            })
    return pd.DataFrame(rows)


def build_machines(lines: pd.DataFrame, scale: C.Scale, seed: int) -> pd.DataFrame:
    rng = stream(seed, "machines")
    # Spread machines as evenly as possible: 100 over 12 lines -> 4 lines of 9, 8 lines of 8.
    base, extra = divmod(scale.machines, len(lines))
    per_line = [base + (1 if i < extra else 0) for i in range(len(lines))]

    rows = []
    for line, count in zip(lines.itertuples(), per_line):
        for n in range(1, count + 1):
            mtype = str(rng.choice(C.MACHINE_TYPES, p=C.MACHINE_TYPE_WEIGHTS))
            crit = str(rng.choice(C.CRITICALITY, p=C.CRITICALITY_WEIGHTS))
            maker = str(rng.choice(C.MANUFACTURERS[mtype]))
            rows.append({
                "machine_id": ids.machine_id(line.line_id, n),
                "line_id": line.line_id,
                "machine_name": f"{mtype.replace('_', ' ').title()} {n:02d}",
                "machine_type": mtype,
                "manufacturer": maker,
                "model": f"{maker[:3].upper()}-{int(rng.integers(100, 999))}",
                "install_date": _random_date(rng, line.commissioned_date, date(2025, 12, 31)),
                "criticality": crit,
                "pm_interval_days": C.PM_INTERVAL_DAYS[crit],
                "status": "ACTIVE",
            })
    return pd.DataFrame(rows)


def build_sensors(machines: pd.DataFrame, scale: C.Scale, seed: int) -> pd.DataFrame:
    rng = stream(seed, "sensors")
    rows = []
    for m in machines.itertuples():
        for stype in C.SENSOR_TYPES:
            # Unit-to-unit variation: each physical machine runs slightly differently (+/-3%).
            nominal = C.BASELINE[m.machine_type][stype] * float(rng.normal(1.0, 0.03))
            nominal = round(nominal, 2)
            rmin, rmax = C.sensor_range(stype, C.BASELINE[m.machine_type][stype])
            band = C.NORMAL_BAND[stype]
            rows.append({
                "sensor_id": ids.sensor_id(m.machine_id, stype, 1),
                "machine_id": m.machine_id,
                "sensor_type": stype,
                "unit": C.SENSOR_UNITS[stype],
                "range_min": rmin,
                "range_max": rmax,
                "nominal_value": nominal,
                "normal_min": round(nominal * (1 - band), 2),
                "normal_max": round(nominal * (1 + band), 2),
                "sampling_interval_min": scale.interval_min,
                "install_date": m.install_date,
                "status": "ACTIVE",
            })
    return pd.DataFrame(rows)


def build_shifts(plants: pd.DataFrame, scale: C.Scale, seed: int) -> pd.DataFrame:
    """Three 8-hour shifts per plant per day. Planned production follows a weekly calendar,
    plus one 2-day planned plant shutdown per plant when the window is at least 30 days."""
    rng = stream(seed, "shifts")
    rows = []
    for plant in plants.itertuples():
        shutdown_days: set[int] = set()
        if scale.days >= 30:
            # Pick a Tuesday..Thursday start somewhere in the middle third of the window.
            candidates = [d for d in range(scale.days // 3, 2 * scale.days // 3)
                          if (C.SIM_START + timedelta(days=d)).weekday() in (1, 2, 3)]
            start = int(rng.choice(candidates))
            shutdown_days = {start, start + 1}

        for d in range(scale.days):
            day_start = C.SIM_START + timedelta(days=d)  # 06:00 local
            weekday = day_start.weekday()
            for code, hour, hours in C.SHIFTS:
                start_ts = day_start.replace(hour=hour)
                end_ts = start_ts + timedelta(hours=hours)
                if d in shutdown_days:
                    planned = "PLANNED_SHUTDOWN"
                elif code in C.PRODUCTION_SHIFTS[weekday]:
                    planned = "PRODUCTION"
                else:
                    planned = "NON_PRODUCTION"
                rows.append({
                    "shift_id": ids.shift_id(plant.plant_id, start_ts.date().isoformat(), code),
                    "plant_id": plant.plant_id,
                    "shift_date": start_ts.date(),
                    "shift_code": code,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "planned_status": planned,
                    "planned_production_hours": hours if planned == "PRODUCTION" else 0,
                })
    df = pd.DataFrame(rows)
    df["start_ts"] = pd.to_datetime(df["start_ts"])
    df["end_ts"] = pd.to_datetime(df["end_ts"])
    return df


def build_technicians(plants: pd.DataFrame, scale: C.Scale, seed: int) -> pd.DataFrame:
    rng = stream(seed, "technicians")
    rows = []
    names = list(C.TECH_FIRST_NAMES)
    k = 0
    for plant in plants.itertuples():
        for n in range(1, scale.technicians_per_plant + 1):
            skill = int(rng.choice([1, 2, 3], p=[0.3, 0.5, 0.2]))
            rows.append({
                "technician_id": ids.technician_id(plant.plant_id, n),
                "plant_id": plant.plant_id,
                # Synthetic display names only (first name + letter), not real people.
                "technician_name": f"{names[k % len(names)]} {chr(65 + (k // len(names)) % 26)}.",
                # Cycle specialisations so every plant has every skill.
                "specialization": C.SPECIALIZATIONS[(n - 1) % len(C.SPECIALIZATIONS)],
                "skill_level": skill,
                "hourly_rate_inr": C.HOURLY_RATE_INR[skill],
                "hire_date": _random_date(rng, date(2012, 1, 1), date(2025, 6, 30)),
                "status": "ACTIVE",
            })
            k += 1
    return pd.DataFrame(rows)


def build_parts() -> pd.DataFrame:
    rows = []
    for n, (name, cat, compat, cost, lead, mode) in enumerate(C.PARTS, start=1):
        rows.append({
            "part_id": ids.part_id(n),
            "part_name": name,
            "category": cat,
            "compatible_machine_type": compat,
            "unit_cost_inr": cost,
            "lead_time_days": lead,
            "failure_mode_addressed": mode,
        })
    return pd.DataFrame(rows)
