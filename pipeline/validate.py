"""Validation: rule checks over the generated files, run twice.

  1. clean baseline  - the generated data as-is. Every integrity check must find 0 issues;
                       anything found here is an UNEXPECTED data-integrity issue.
  2. received view   - the clean data with exceptions/ applied (dirty records replace or add
                       to the clean ones), i.e. what a plant would actually deliver.

Checks only read the data. ground_truth/ is opened afterwards, purely to score how well the
checks found the injected problems (true/false positives, misses).

Also reported, as data quality rather than integrity: missing readings and sensor-fault
patterns (stuck, spikes, dropouts). These are realistic, expected features of the baseline.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import pandas as pd

from . import config as C
from .generate import TABLE_FILES
from .generate.states import REASONS
from .io import write_json

VIEWS = {  # view name -> file
    "plant": "plants.csv", "production_line": "production_lines.csv", "machine": "machines.csv",
    "sensor": "sensors.csv", "operating_shift": "operating_shifts.csv",
    "technician": "technicians.csv", "part": "parts.csv",
    "machine_state_history": "machine_state_history.csv", "failure_event": "failure_events.csv",
    "maintenance_work_order": "maintenance_work_orders.csv", "work_order_part": "work_order_parts.csv",
    "work_order_technician": "work_order_technicians.csv",
    "work_order_status_history": "work_order_status_history.csv",
}
assert set(VIEWS.values()) == set(TABLE_FILES.values())


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def _checks(tel: str, fe: str, wo: str) -> list[dict]:
    """Every check returns one row per offending record, with a `record_id` column."""
    window_end = f"TIMESTAMPTZ '{C.SIM_START.isoformat()}' + INTERVAL {{days}} DAY"
    checks = []

    def add(name, category, sql, issue_type=None):
        checks.append({"name": name, "category": category, "sql": sql, "issue_type": issue_type})

    # --- primary keys -------------------------------------------------------------------
    for table, key in [("plant", "plant_id"), ("production_line", "line_id"), ("machine", "machine_id"),
                       ("sensor", "sensor_id"), ("operating_shift", "shift_id"),
                       ("technician", "technician_id"), ("part", "part_id"),
                       ("machine_state_history", "state_event_id"), (fe, "failure_id"),
                       (wo, "work_order_id"), ("work_order_status_history", "status_event_id"),
                       ("work_order_part", "work_order_id || '|' || part_id"),
                       ("work_order_technician", "work_order_id || '|' || technician_id"),
                       (tel, "telemetry_id")]:
        add(f"pk_unique:{table.removesuffix('_rx')}", "primary_key",
            f"SELECT {key} AS record_id FROM {table} GROUP BY 1 HAVING count(*) > 1")

    # --- foreign keys -------------------------------------------------------------------
    for child, key, col, parent, pk, issue in [
        ("production_line", "line_id", "plant_id", "plant", "plant_id", None),
        ("machine", "machine_id", "line_id", "production_line", "line_id", None),
        ("sensor", "sensor_id", "machine_id", "machine", "machine_id", None),
        ("operating_shift", "shift_id", "plant_id", "plant", "plant_id", None),
        ("technician", "technician_id", "plant_id", "plant", "plant_id", None),
        ("machine_state_history", "state_event_id", "machine_id", "machine", "machine_id", None),
        ("machine_state_history", "state_event_id", "shift_id", "operating_shift", "shift_id", None),
        ("machine_state_history", "state_event_id", "work_order_id", wo, "work_order_id", None),
        (fe, "failure_id", "machine_id", "machine", "machine_id", None),
        (wo, "work_order_id", "machine_id", "machine", "machine_id", None),
        (wo, "work_order_id", "failure_id", fe, "failure_id", None),
        (wo, "work_order_id", "sensor_id", "sensor", "sensor_id", None),
        ("work_order_part", "work_order_id", "work_order_id", wo, "work_order_id", None),
        ("work_order_part", "part_id", "part_id", "part", "part_id", None),
        ("work_order_technician", "work_order_id", "work_order_id", wo, "work_order_id", None),
        ("work_order_technician", "technician_id", "technician_id", "technician", "technician_id", None),
        ("work_order_status_history", "status_event_id", "work_order_id", wo, "work_order_id", None),
        (tel, "telemetry_id", "sensor_id", "sensor", "sensor_id", "UNKNOWN_SENSOR"),
    ]:
        add(f"fk:{child.removesuffix('_rx')}.{col}->{parent.removesuffix('_rx')}", "foreign_key",
            f"SELECT c.{key} AS record_id FROM {child} c ANTI JOIN {parent} p ON c.{col} = p.{pk} "
            f"WHERE c.{col} IS NOT NULL", issue)

    # --- allowed values -----------------------------------------------------------------
    for table, col, allowed in [
        ("machine", "machine_type", C.MACHINE_TYPES), ("machine", "criticality", C.CRITICALITY),
        ("machine", "status", ["ACTIVE", "INACTIVE", "RETIRED"]),
        ("sensor", "sensor_type", C.SENSOR_TYPES), ("sensor", "unit", C.SENSOR_UNITS.values()),
        ("machine_state_history", "state", C.MACHINE_STATES), ("machine_state_history", "reason", REASONS),
        ("operating_shift", "shift_code", ["A", "B", "C"]),
        ("operating_shift", "planned_status", ["PRODUCTION", "NON_PRODUCTION", "PLANNED_SHUTDOWN"]),
        ("technician", "specialization", C.SPECIALIZATIONS),
        (fe, "failure_mode", C.FAILURE_MODES), (fe, "severity", ["MINOR", "MAJOR", "CRITICAL"]),
        (wo, "work_order_type", C.WO_TYPES), (wo, "status", C.WO_STATUSES),
        (wo, "priority", ["LOW", "MEDIUM", "HIGH", "EMERGENCY"]),
        ("work_order_status_history", "to_status", C.WO_STATUSES),
        ("work_order_technician", "role", ["LEAD", "ASSIST"]),
    ]:
        add(f"enum:{table.removesuffix('_rx')}.{col}", "enum",
            f"SELECT coalesce({col}::VARCHAR, 'NULL') AS record_id FROM {table} "
            f"WHERE {col} IS NULL OR {col} NOT IN {_in(allowed)}")

    # --- telemetry ----------------------------------------------------------------------
    add("telemetry:unit_matches_sensor", "telemetry",
        f"SELECT t.telemetry_id AS record_id FROM {tel} t JOIN sensor s USING (sensor_id) "
        f"WHERE t.unit <> s.unit", "IMPOSSIBLE_UNIT")
    add("telemetry:value_within_sensor_range", "telemetry",
        f"SELECT t.telemetry_id AS record_id FROM {tel} t JOIN sensor s USING (sensor_id) "
        f"WHERE t.unit = s.unit AND (t.value < s.range_min OR t.value > s.range_max)", "IMPOSSIBLE_VALUE")
    add("telemetry:zero_while_running", "telemetry",
        f"WITH z AS (SELECT * FROM {tel} WHERE value = 0) "
        f"SELECT z.telemetry_id AS record_id FROM z JOIN machine_state_history h "
        f"ON h.machine_id = z.machine_id AND z.ts >= h.start_ts AND z.ts < h.end_ts "
        f"WHERE h.state = 'RUNNING'", "ZERO_FILLED_GAP")
    add("telemetry:machine_matches_sensor_owner", "telemetry",
        f"SELECT t.telemetry_id AS record_id FROM {tel} t JOIN sensor s USING (sensor_id) "
        f"WHERE t.machine_id <> s.machine_id")
    add("telemetry:on_30min_grid_inside_window", "telemetry",
        f"SELECT telemetry_id AS record_id FROM {tel} WHERE epoch(ts)::BIGINT % {60 * 30} <> 0 "
        f"OR ts < TIMESTAMPTZ '{C.SIM_START.isoformat()}' OR ts >= {window_end}")
    add("telemetry:no_duplicate_sensor_timestamp", "telemetry",
        f"SELECT sensor_id || '@' || ts AS record_id FROM {tel} GROUP BY sensor_id, ts HAVING count(*) > 1")

    # --- date ordering ------------------------------------------------------------------
    add("dates:line_after_plant", "date_order",
        "SELECT l.line_id AS record_id FROM production_line l JOIN plant p USING (plant_id) "
        "WHERE l.commissioned_date < p.commissioned_date")
    add("dates:machine_after_line", "date_order",
        "SELECT m.machine_id AS record_id FROM machine m JOIN production_line l USING (line_id) "
        "WHERE m.install_date < l.commissioned_date")
    add("dates:sensor_after_machine", "date_order",
        "SELECT s.sensor_id AS record_id FROM sensor s JOIN machine m USING (machine_id) "
        "WHERE s.install_date < m.install_date")
    add("dates:shift_end_after_start", "date_order",
        "SELECT shift_id AS record_id FROM operating_shift WHERE end_ts <= start_ts")
    add("dates:state_end_after_start", "date_order",
        "SELECT state_event_id AS record_id FROM machine_state_history WHERE end_ts <= start_ts")
    add("dates:work_order_created_before_start", "date_order",
        f"SELECT work_order_id AS record_id FROM {wo} WHERE start_ts < created_ts")
    add("dates:maintenance_end_not_before_start", "date_order",
        f"SELECT work_order_id AS record_id FROM {wo} WHERE end_ts < start_ts",
        "MAINTENANCE_END_BEFORE_START")
    add("dates:symptom_recorded_before_failure", "date_order",
        f"SELECT failure_id AS record_id FROM {fe} WHERE first_symptom_ts >= failure_ts "
        f"OR (first_symptom_ts IS NULL AND failure_mode IN {_in(sorted(C.GRADUAL_MODES))})",
        "FAILURE_BEFORE_SYMPTOM")
    add("dates:failure_inside_window", "date_order",
        f"SELECT failure_id AS record_id FROM {fe} "
        f"WHERE failure_ts < TIMESTAMPTZ '{C.SIM_START.isoformat()}' OR failure_ts >= {window_end}")

    # --- lifecycle and history ----------------------------------------------------------
    add("lifecycle:state_history_contiguous", "lifecycle",
        "SELECT state_event_id AS record_id FROM (SELECT *, lag(end_ts) OVER w AS prev_end, "
        "lag(state) OVER w AS prev_state, row_number() OVER w AS n FROM machine_state_history "
        "WINDOW w AS (PARTITION BY machine_id ORDER BY start_ts)) "
        f"WHERE (n = 1 AND start_ts <> TIMESTAMPTZ '{C.SIM_START.isoformat()}') OR start_ts <> prev_end "
        "OR previous_state IS DISTINCT FROM prev_state")
    add("lifecycle:state_history_reaches_window_end", "lifecycle",
        f"SELECT machine_id AS record_id FROM machine_state_history GROUP BY 1 "
        f"HAVING max(end_ts) <> {window_end}")
    add("lifecycle:downtime_states_linked_to_work_order", "lifecycle",
        "SELECT state_event_id AS record_id FROM machine_state_history "
        "WHERE (state IN ('FAILED', 'MAINTENANCE')) <> (work_order_id IS NOT NULL)")
    allowed = " OR ".join(f"(from_status = '{a}' AND to_status = '{b}')"
                          for a, bs in C.WO_TRANSITIONS.items() if a for b in bs)
    add("lifecycle:work_order_transitions_allowed", "lifecycle",
        "SELECT status_event_id AS record_id FROM (SELECT *, lag(to_status) OVER w AS prev_to, "
        "lag(changed_ts) OVER w AS prev_ts FROM work_order_status_history "
        "WINDOW w AS (PARTITION BY work_order_id ORDER BY status_event_id)) "
        f"WHERE NOT ((from_status IS NULL AND to_status = 'OPEN' AND prev_to IS NULL) OR ({allowed})) "
        "OR from_status IS DISTINCT FROM prev_to OR changed_ts < prev_ts")
    add("lifecycle:work_order_status_is_last_history_status", "lifecycle",
        f"SELECT w.work_order_id AS record_id FROM {wo} w JOIN (SELECT work_order_id, "
        "arg_max(to_status, status_event_id) AS last FROM work_order_status_history GROUP BY 1) h "
        "USING (work_order_id) WHERE w.status <> h.last")
    add("lifecycle:completed_work_orders_have_times", "lifecycle",
        f"SELECT work_order_id AS record_id FROM {wo} WHERE (status = 'COMPLETED') "
        "<> (start_ts IS NOT NULL AND end_ts IS NOT NULL)")
    add("lifecycle:each_failure_has_one_corrective_work_order", "lifecycle",
        f"SELECT f.failure_id AS record_id FROM {fe} f LEFT JOIN {wo} w "
        "ON w.failure_id = f.failure_id AND w.work_order_type = 'CORRECTIVE' "
        "GROUP BY 1 HAVING count(w.work_order_id) <> 1")
    add("lifecycle:failure_starts_failed_state", "lifecycle",
        f"SELECT f.failure_id AS record_id FROM {fe} f ANTI JOIN machine_state_history h "
        "ON h.machine_id = f.machine_id AND h.start_ts = f.failure_ts AND h.state = 'FAILED'")

    # --- reconciliation of derived values -----------------------------------------------
    add("reconcile:total_cost", "reconciliation",
        f"SELECT work_order_id AS record_id FROM {wo} "
        "WHERE total_cost_inr <> labor_cost_inr + parts_cost_inr")
    add("reconcile:parts_cost", "reconciliation",
        f"SELECT w.work_order_id AS record_id FROM {wo} w LEFT JOIN (SELECT work_order_id, "
        "sum(line_cost_inr) AS s FROM work_order_part GROUP BY 1) p USING (work_order_id) "
        "WHERE w.parts_cost_inr <> coalesce(p.s, 0)")
    add("reconcile:part_line_cost", "reconciliation",
        "SELECT wp.work_order_id || '|' || wp.part_id AS record_id FROM work_order_part wp "
        "JOIN part p USING (part_id) WHERE wp.unit_cost_inr <> p.unit_cost_inr "
        "OR wp.line_cost_inr <> wp.quantity * wp.unit_cost_inr")
    add("reconcile:labor_cost_and_hours", "reconciliation",
        f"SELECT w.work_order_id AS record_id FROM {wo} w LEFT JOIN (SELECT work_order_id, "
        "sum(round(hours * t.hourly_rate_inr)) AS cost, sum(hours) AS hours FROM work_order_technician "
        "JOIN technician t USING (technician_id) GROUP BY 1) l USING (work_order_id) "
        "WHERE w.labor_cost_inr <> coalesce(l.cost, 0) OR abs(w.labor_hours - coalesce(l.hours, 0)) > 1e-9")
    add("reconcile:technician_hours_match_work_duration", "reconciliation",
        f"SELECT wt.work_order_id AS record_id FROM work_order_technician wt JOIN {wo} w "
        "USING (work_order_id) WHERE abs(wt.hours - epoch(w.end_ts - w.start_ts) / 3600) > 1e-9")
    add("reconcile:work_order_downtime", "reconciliation",
        f"SELECT w.work_order_id AS record_id FROM {wo} w LEFT JOIN (SELECT work_order_id, "
        "sum(duration_min) AS d FROM machine_state_history GROUP BY 1) h USING (work_order_id) "
        "WHERE w.downtime_min <> coalesce(h.d, 0)")
    add("reconcile:state_duration", "reconciliation",
        "SELECT state_event_id AS record_id FROM machine_state_history "
        "WHERE duration_min <> epoch(end_ts - start_ts) / 60")
    add("reconcile:failure_downtime_matches_work_order", "reconciliation",
        f"SELECT f.failure_id AS record_id FROM {fe} f JOIN {wo} w USING (failure_id) "
        "WHERE f.downtime_min <> w.downtime_min")
    add("reconcile:failure_severity_rule", "reconciliation",
        f"SELECT f.failure_id AS record_id FROM {fe} f JOIN machine m USING (machine_id) "
        "WHERE f.severity <> CASE WHEN m.criticality = 'A' THEN 'CRITICAL' "
        f"WHEN f.downtime_min >= {C.SEVERITY_MAJOR_DOWNTIME_MIN} THEN 'MAJOR' ELSE 'MINOR' END")
    add("reconcile:technician_same_plant_as_machine", "reconciliation",
        f"SELECT wt.work_order_id || '|' || wt.technician_id AS record_id FROM work_order_technician wt "
        f"JOIN technician t USING (technician_id) JOIN {wo} w USING (work_order_id) "
        "JOIN machine m ON m.machine_id = w.machine_id JOIN production_line l ON l.line_id = m.line_id "
        "WHERE t.plant_id <> l.plant_id")
    add("reconcile:part_compatible_with_machine", "reconciliation",
        f"SELECT wp.work_order_id || '|' || wp.part_id AS record_id FROM work_order_part wp "
        f"JOIN part p USING (part_id) JOIN {wo} w USING (work_order_id) "
        "JOIN machine m ON m.machine_id = w.machine_id "
        "WHERE p.compatible_machine_type NOT IN ('ALL', m.machine_type)")
    return checks


def _create_views(con, data_dir: Path) -> None:
    for view, file in VIEWS.items():
        con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_csv('{(data_dir / file).as_posix()}', "
                    "header = true)")
    con.execute(f"CREATE VIEW telemetry_event AS SELECT * FROM "
                f"read_parquet('{(data_dir / 'telemetry' / '*.parquet').as_posix()}')")
    exc = data_dir / "exceptions"
    for view, file in [("exc_telemetry", "telemetry_exceptions.csv"),
                       ("exc_failure_event", "failure_event_exceptions.csv"),
                       ("exc_work_order", "work_order_exceptions.csv")]:
        con.execute(f"CREATE VIEW {view} AS SELECT * FROM read_csv('{(exc / file).as_posix()}', header = true)")
    # Received view: an exception record replaces the clean record with the same ID, or is added.
    for rx, clean, exc_view, key in [("telemetry_rx", "telemetry_event", "exc_telemetry", "telemetry_id"),
                                     ("failure_event_rx", "failure_event", "exc_failure_event", "failure_id"),
                                     ("maintenance_work_order_rx", "maintenance_work_order",
                                      "exc_work_order", "work_order_id")]:
        con.execute(f"CREATE VIEW {rx} AS SELECT * FROM {clean} WHERE {key} NOT IN "
                    f"(SELECT {key} FROM {exc_view}) UNION ALL BY NAME SELECT * FROM {exc_view}")


def _run(con, checks: list[dict], days: int) -> list[dict]:
    results = []
    for c in checks:
        ids = [r[0] for r in con.execute(c["sql"].replace("{days}", str(days))).fetchall()]
        results.append({"name": c["name"], "category": c["category"], "issue_type": c["issue_type"],
                        "violations": len(ids), "record_ids": sorted(map(str, ids))})
    return results


def _sensor_fault_patterns(con, tel: str) -> dict:
    """Single-sensor patterns, looking only at readings taken while the machine was RUNNING
    (a stopped machine legitimately reports flat, near-zero values).
    Returns {pattern: [(sensor_id, first_ts, last_ts)]}."""
    running = (f"SELECT t.sensor_id, t.ts, t.value, s.normal_max FROM {tel} t "
               f"JOIN sensor s USING (sensor_id) JOIN machine_state_history h "
               f"ON h.machine_id = t.machine_id AND t.ts >= h.start_ts AND t.ts < h.end_ts "
               f"WHERE s.sensor_type IN {_in(C.FAULT_SENSOR_TYPES)} AND h.state = 'RUNNING'")
    con.execute(f"CREATE OR REPLACE TEMP TABLE running_readings AS {running}")
    stuck = con.execute(
        "WITH f AS (SELECT *, CASE WHEN value IS NOT DISTINCT FROM lag(value) OVER w THEN 0 ELSE 1 END AS new_run "
        "FROM running_readings WINDOW w AS (PARTITION BY sensor_id ORDER BY ts)), "
        "r AS (SELECT *, sum(new_run) OVER (PARTITION BY sensor_id ORDER BY ts) AS run FROM f) "
        "SELECT sensor_id, epoch(min(ts)), epoch(max(ts)) FROM r WHERE value IS NOT NULL GROUP BY sensor_id, run "
        "HAVING count(*) >= 6 ORDER BY 1, 2").fetchall()
    # A missing value is missing whatever the machine is doing, so dropouts use all readings.
    dropout = con.execute(
        f"SELECT sensor_id, epoch(min(ts)), epoch(max(ts)) FROM {tel} WHERE value IS NULL "
        "GROUP BY sensor_id ORDER BY 1").fetchall()
    spikes = con.execute(
        "WITH n AS (SELECT *, lag(value) OVER w AS p, lead(value) OVER w AS q FROM running_readings "
        "WINDOW w AS (PARTITION BY sensor_id ORDER BY ts)) "
        "SELECT sensor_id, epoch(min(ts)), epoch(max(ts)) FROM n WHERE value > 2 * p AND value > 2 * q AND value > normal_max "
        "GROUP BY sensor_id HAVING count(*) >= 3 ORDER BY 1").fetchall()
    return {"STUCK": stuck, "DROPOUT": dropout, "SPIKES": spikes}


def validate(data_dir: Path, log=print) -> dict:
    t0 = time.perf_counter()
    days = json.loads((data_dir / "manifest.json").read_text())["scale"]["days"]
    con = duckdb.connect()
    con.execute("SET TimeZone = 'Asia/Kolkata'")
    _create_views(con, data_dir)

    clean = _run(con, _checks("telemetry_event", "failure_event", "maintenance_work_order"), days)
    received = _run(con, _checks("telemetry_rx", "failure_event_rx", "maintenance_work_order_rx"), days)
    patterns = _sensor_fault_patterns(con, "telemetry_event")
    missing = con.execute("SELECT count(*) FROM telemetry_event WHERE value IS NULL").fetchone()[0]
    total = con.execute("SELECT count(*) FROM telemetry_event").fetchone()[0]

    # ---- scoring against ground truth (only now is ground truth read) ----
    gt = pd.read_csv(data_dir / "ground_truth" / "ground_truth.csv")
    for col in ("start_ts", "end_ts"):  # epoch seconds, comparable with the pattern windows
        gt[col] = pd.to_datetime(gt[col]).map(lambda t: t.timestamp())
    injected = gt[gt["category"] == "INJECTED_ANOMALY"]
    edge = {}
    for issue in sorted(injected["issue_type"].unique()):
        expected = set(injected.loc[injected["issue_type"] == issue, "record_id"])
        found = set().union(*[set(r["record_ids"]) for r in received if r["issue_type"] == issue])
        edge[issue] = {"expected": len(expected), "detected": len(found),
                       "true_positive": len(expected & found), "false_positive": len(found - expected),
                       "missed": len(expected - found)}
    injected_ids = set(injected["record_id"])
    secondary = [{"name": r["name"], "violations": r["violations"],
                  "all_on_injected_records": set(r["record_ids"]) <= injected_ids}
                 for r in received if r["violations"] and r["issue_type"] is None]

    faults = gt[gt["category"] == "SENSOR_FAULT"]
    sensor_fault_detection = {}
    for kind in C.SENSOR_FAULT_TYPES:
        truth = faults[faults["issue_type"] == kind]
        flagged = patterns.get(kind)
        if flagged is None:
            sensor_fault_detection[kind] = {"faults": len(truth), "detected": None,
                                            "note": "not detectable from one sensor alone; needs cross-sensor model"}
            continue
        hit = sum(any(s == f.sensor_id and a <= f.end_ts and b >= f.start_ts for s, a, b in flagged)
                  for f in truth.itertuples())
        false_alarms = sum(not any(s == f.sensor_id and a <= f.end_ts and b >= f.start_ts
                                   for f in faults.itertuples()) for s, a, b in flagged)
        sensor_fault_detection[kind] = {"faults": len(truth), "detected": hit,
                                        "flagged_without_fault": false_alarms}

    clean_failed = [r for r in clean if r["violations"]]
    edge_ok = all(v["missed"] == 0 and v["false_positive"] == 0 for v in edge.values())
    report = {
        "dataset": str(data_dir.as_posix()),
        "passed": not clean_failed and edge_ok,
        "clean_baseline": {"checks_run": len(clean), "checks_passed": len(clean) - len(clean_failed),
                           "unexpected_issues": [{k: r[k] for k in ("name", "violations")} | {"sample": r["record_ids"][:5]}
                                                 for r in clean_failed]},
        "received_with_exceptions": {
            "checks_run": len(received),
            "edge_case_detection": edge,
            "secondary_findings": secondary,
            "violations_by_check": {r["name"]: r["violations"] for r in received if r["violations"]},
        },
        "data_quality": {"telemetry_readings": total, "missing_readings": missing,
                         "completeness_pct": round(100 * (total - missing) / total, 3),
                         "sensor_fault_detection": sensor_fault_detection},
        "category_counts": {cat: sum(1 for c in clean if c["category"] == cat)
                            for cat in sorted({c["category"] for c in clean})},
    }
    out = data_dir / "validation"
    out.mkdir(exist_ok=True)
    write_json(report, out / "validation_report.json")
    (out / "validation_summary.md").write_text(_summary(report), encoding="utf-8")
    log(_summary(report))
    log(f"validated in {time.perf_counter() - t0:.1f}s -> {out}")
    return report


def _summary(r: dict) -> str:
    cb, rx, dq = r["clean_baseline"], r["received_with_exceptions"], r["data_quality"]
    lines = [f"# Validation summary: {r['dataset']}", "",
             f"**Overall: {'PASS' if r['passed'] else 'FAIL'}**", "",
             "## 1. Clean baseline (integrity)", "",
             f"{cb['checks_passed']} / {cb['checks_run']} checks passed, "
             f"{len(cb['unexpected_issues'])} with unexpected issues.", ""]
    lines += [f"- {u['name']}: {u['violations']} (e.g. {', '.join(u['sample'])})" for u in cb["unexpected_issues"]]
    lines += ["## 2. Injected edge cases (received data)", "",
              "| Issue | Expected | Detected | True pos. | False pos. | Missed |", "|---|---:|---:|---:|---:|---:|"]
    lines += [f"| {k} | {v['expected']} | {v['detected']} | {v['true_positive']} | {v['false_positive']} | {v['missed']} |"
              for k, v in rx["edge_case_detection"].items()]
    if rx["secondary_findings"]:
        lines += ["", "Other checks that fired on the received data:", ""]
        lines += [f"- {s['name']}: {s['violations']}"
                  f"{' (all on injected records)' if s['all_on_injected_records'] else ' (NOT explained by injected records)'}"
                  for s in rx["secondary_findings"]]
    lines += ["", "## 3. Data quality (expected, informational)", "",
              f"- Telemetry completeness: {dq['completeness_pct']}% "
              f"({dq['missing_readings']:,} missing of {dq['telemetry_readings']:,})", "",
              "| Sensor fault type | Faults in ground truth | Detected by single-sensor rules | Flagged without a fault |",
              "|---|---:|---:|---:|"]
    for k, v in dq["sensor_fault_detection"].items():
        lines.append(f"| {k} | {v['faults']} | {v['detected'] if v['detected'] is not None else 'n/a: ' + v['note']} "
                     f"| {v.get('flagged_without_fault', '-')} |")
    return "\n".join(lines) + "\n"
