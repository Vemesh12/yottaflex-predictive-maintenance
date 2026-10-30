"""Work orders, failure events and their bridge/history tables, built from the planned work items.

Every derived value is computed from source records, never drawn independently:
  labor_hours      = sum of technician hours, each = work-order end - start
  labor_cost_inr   = sum(hours x technician.hourly_rate_inr)
  parts_cost_inr   = sum(work_order_part.line_cost_inr), line = quantity x part.unit_cost_inr
  total_cost_inr   = labor_cost_inr + parts_cost_inr
  downtime_min     = sum of machine_state_history durations linked to the work order (finalize())
  severity         = rule on machine criticality and downtime (finalize())
  status           = last row of work_order_status_history
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from .. import config as C
from .. import ids
from ..rng import stream

KIND_ORDER = {"CORRECTIVE": 0, "SENSOR_REPLACEMENT": 1, "PREVENTIVE": 2}


def _ts(slot: int, scale: C.Scale):
    return C.SIM_START + timedelta(minutes=int(slot) * scale.interval_min)


def _schedule(item: dict, scale: C.Scale, rng) -> dict:
    """Lifecycle timestamps for one work item. Returns created/assigned/start/end + history."""
    kind = item["kind"]
    if kind == "PREVENTIVE":
        w = item["pm"]
        start, end = _ts(w["start_slot"], scale), _ts(w["end_slot"], scale)
        created = start - timedelta(days=C.PM_LEAD_DAYS)
        assigned = created + timedelta(days=1)
        if w["cancelled"]:
            cancel = _ts(w["cancel_slot"], scale)
            steps = [("OPEN", created)] + ([("ASSIGNED", assigned)] if assigned <= cancel else [])
            return {"created": created, "start": None, "end": None,
                    "history": steps + [("CANCELLED", cancel)]}
    elif kind == "CORRECTIVE":
        f = item["failure"]
        created = _ts(f["failure_slot"], scale)
        start, end = _ts(f["repair_start_slot"], scale), _ts(f["end_slot"], scale)
        assigned = created + (start - created) / 2
    else:  # SENSOR_REPLACEMENT: reported mid-fault, sensor swapped at the end of the fault
        f = item["fault"]
        work_slots = int(rng.integers(2, 5))
        created = _ts(f["start_slot"] + (f["end_slot"] - f["start_slot"]) // 2, scale)
        start, end = _ts(f["end_slot"] - work_slots, scale), _ts(f["end_slot"], scale)
        assigned = created + (start - created) / 2
    return {"created": created, "start": start, "end": end,
            "history": [("OPEN", created), ("ASSIGNED", assigned), ("IN_PROGRESS", start),
                        ("COMPLETED", end)]}


def build(machines: pd.DataFrame, lines: pd.DataFrame, technicians: pd.DataFrame,
          parts: pd.DataFrame, items: list[dict], scale: C.Scale, seed: int) -> dict:
    """items: {"machine_id", "ref", "kind", and "pm" | "failure" | "fault"} for every machine."""
    machine = machines.set_index("machine_id")
    plant_of = machine["line_id"].map(lines.set_index("line_id")["plant_id"])
    part_by_name = parts.set_index("part_name")
    rate = technicians.set_index("technician_id")["hourly_rate_inr"]

    # Failure IDs in time order.
    failures = sorted((it for it in items if it["kind"] == "CORRECTIVE"),
                      key=lambda it: (it["failure"]["failure_slot"], it["machine_id"]))
    failure_id = {(it["machine_id"], it["ref"]): ids.failure_id(i)
                  for i, it in enumerate(failures, start=1)}

    planned = []
    for it in items:
        slot = (it.get("pm") or it.get("failure") or it.get("fault"))
        slot = slot.get("start_slot", slot.get("failure_slot"))
        rng = stream(seed, "work_order", it["machine_id"], it["kind"], slot)
        planned.append((it, rng, _schedule(it, scale, rng)))
    # WO counter follows creation time, as a real CMMS would.
    planned.sort(key=lambda p: (p[2]["created"], p[0]["machine_id"], KIND_ORDER[p[0]["kind"]]))

    wo_rows, part_rows, tech_rows, hist_rows, fail_rows = [], [], [], [], []
    key_map = {}
    for n, (it, rng, sch) in enumerate(planned, start=1):
        wo = ids.work_order_id(n)
        key_map[f"{it['machine_id']}#{it['ref']}"] = wo
        m = machine.loc[it["machine_id"]]
        kind = it["kind"]
        completed = sch["history"][-1][0] == "COMPLETED"

        # --- who does the work ---
        if kind == "PREVENTIVE":
            spec = "HYDRAULICS" if m.machine_type == "HYDRAULIC_PRESS" else "MECHANICAL"
        elif kind == "CORRECTIVE":
            mode = it["failure"]["failure_mode"]
            spec = ("HYDRAULICS" if mode == "PRESSURE_LOSS" and m.machine_type == "HYDRAULIC_PRESS"
                    else C.LEAD_SPECIALIZATION[mode])
        else:
            spec = "INSTRUMENTATION"
        plant_techs = technicians[technicians["plant_id"] == plant_of[it["machine_id"]]]
        lead_pool = plant_techs[plant_techs["specialization"] == spec]["technician_id"].tolist()
        crew = [(str(rng.choice(lead_pool)), "LEAD")]
        if kind == "CORRECTIVE" and rng.random() < 0.5:
            others = [t for t in plant_techs["technician_id"] if t != crew[0][0]]
            crew.append((str(rng.choice(others)), "ASSIST"))

        # --- which parts ---
        if kind == "PREVENTIVE":
            used = [("Lubricant (5 L)", int(rng.integers(1, 4)))]
            if m.machine_type == "HYDRAULIC_PRESS":
                used.append(("Hydraulic oil filter", 1))
        elif kind == "CORRECTIVE":
            options = parts[(parts["failure_mode_addressed"] == mode)
                            & parts["compatible_machine_type"].isin([m.machine_type, "ALL"])]
            used = [(str(rng.choice(options["part_name"].tolist())), 1)]
            if mode != "ELECTRICAL_FAULT":
                used.append(("Lubricant (5 L)", 1))
        else:
            used = [(C.SENSOR_PART[it["fault"]["sensor_type"]], 1)]

        labor_hours = labor_cost = parts_cost = 0
        if completed:
            hours = (sch["end"] - sch["start"]).total_seconds() / 3600
            for tech, role in crew:
                tech_rows.append({"work_order_id": wo, "technician_id": tech, "role": role,
                                  "hours": hours})
                labor_hours += hours
                labor_cost += round(hours * int(rate[tech]))
            for name, qty in used:
                p = part_by_name.loc[name]
                line_cost = qty * int(p.unit_cost_inr)
                part_rows.append({"work_order_id": wo, "part_id": p.part_id, "quantity": qty,
                                  "unit_cost_inr": int(p.unit_cost_inr), "line_cost_inr": line_cost})
                parts_cost += line_cost

        prev = None
        for status, ts in sch["history"]:
            hist_rows.append({"work_order_id": wo, "from_status": prev, "to_status": status,
                              "changed_ts": ts})
            prev = status

        f_id = failure_id.get((it["machine_id"], it["ref"])) if kind == "CORRECTIVE" else None
        if kind == "PREVENTIVE":
            description = f"Preventive maintenance ({m.pm_interval_days}-day interval)"
        elif kind == "CORRECTIVE":
            description = f"Breakdown repair: {mode}"
        else:
            description = "Replace sensor reported faulty by operator"
        wo_rows.append({
            "work_order_id": wo, "machine_id": it["machine_id"], "work_order_type": kind,
            "priority": ("LOW" if kind == "PREVENTIVE" else "MEDIUM" if kind == "SENSOR_REPLACEMENT"
                         else C.CORRECTIVE_PRIORITY[m.criticality]),
            "status": prev, "failure_id": f_id,
            "sensor_id": it["fault"]["sensor_id"] if kind == "SENSOR_REPLACEMENT" else None,
            "created_ts": sch["created"], "start_ts": sch["start"], "end_ts": sch["end"],
            "labor_hours": labor_hours, "labor_cost_inr": labor_cost,
            "parts_cost_inr": parts_cost, "total_cost_inr": labor_cost + parts_cost,
            "downtime_min": 0,  # filled from state history in finalize()
            "description": description,
        })
        if kind == "CORRECTIVE":
            f = it["failure"]
            fail_rows.append({
                "failure_id": f_id, "machine_id": it["machine_id"],
                "failure_ts": _ts(f["failure_slot"], scale), "failure_mode": f["failure_mode"],
                "first_symptom_ts": (None if f["first_symptom_slot"] is None
                                     else _ts(f["first_symptom_slot"], scale)),
                "severity": None, "downtime_min": 0,  # filled in finalize()
            })

    work_orders = _frame(wo_rows, WO_COLUMNS, ["created_ts", "start_ts", "end_ts"])
    failure_events = _frame(fail_rows, FAILURE_COLUMNS, ["failure_ts", "first_symptom_ts"])
    status_history = _frame(hist_rows, ["work_order_id", "from_status", "to_status", "changed_ts"],
                            ["changed_ts"])
    status_history.insert(0, "status_event_id",
                          [ids.status_event_id(i) for i in range(1, len(status_history) + 1)])
    return {
        "maintenance_work_orders": work_orders,
        "failure_events": failure_events.sort_values("failure_id").reset_index(drop=True),
        "work_order_parts": pd.DataFrame(part_rows, columns=["work_order_id", "part_id", "quantity",
                                                             "unit_cost_inr", "line_cost_inr"]),
        "work_order_technicians": pd.DataFrame(tech_rows, columns=["work_order_id", "technician_id",
                                                                   "role", "hours"]),
        "work_order_status_history": status_history,
        "key_map": key_map,
    }


WO_COLUMNS = ["work_order_id", "machine_id", "work_order_type", "priority", "status", "failure_id",
              "sensor_id", "created_ts", "start_ts", "end_ts", "labor_hours", "labor_cost_inr",
              "parts_cost_inr", "total_cost_inr", "downtime_min", "description"]
FAILURE_COLUMNS = ["failure_id", "machine_id", "failure_ts", "failure_mode", "first_symptom_ts",
                   "severity", "downtime_min"]


def finalize(tables: dict, state_history: pd.DataFrame, machines: pd.DataFrame) -> None:
    """Fill downtime and severity from the state history (in place)."""
    downtime = state_history.dropna(subset=["work_order_id"]).groupby("work_order_id")["duration_min"].sum()
    wo = tables["maintenance_work_orders"]
    wo["downtime_min"] = wo["work_order_id"].map(downtime).fillna(0).astype(int)

    fe = tables["failure_events"]
    corrective = wo.dropna(subset=["failure_id"]).set_index("failure_id")["downtime_min"]
    fe["downtime_min"] = fe["failure_id"].map(corrective).astype(int)
    crit = fe["machine_id"].map(machines.set_index("machine_id")["criticality"])
    fe["severity"] = ["CRITICAL" if c == "A" else "MAJOR" if d >= C.SEVERITY_MAJOR_DOWNTIME_MIN
                      else "MINOR" for c, d in zip(crit, fe["downtime_min"])]


def _frame(rows: list[dict], columns: list[str], ts_cols: list[str]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    for c in ts_cols:
        df[c] = pd.to_datetime(df[c]).dt.tz_convert(C.TZ) if len(df) else df[c]
    return df
