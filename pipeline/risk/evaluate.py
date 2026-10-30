"""Evaluation of the risk engine against ground truth, with a chronological split.

Label of an evaluation point (machine m at time t):
  positive  = machine m fails in (t, t + 7 days]
  excluded  = machine m is down at t (between a failure and the end of its repair)

Chronological split by evaluation day (thirds of the window, e.g. 1-29 / 30-59 / 60-90):
  train       thresholds learned here (engine.calibrate, no labels)
  validation  the alert level (MEDIUM / HIGH / CRITICAL) is chosen here, by F1
  test        reported once, with the choice made on validation
Purging: a point is only scored in its split if its whole 7-day horizon lies inside that split,
so no label "looks" into the next period, and the last 7 days are not scored at all (their
outcome is unknown: right-censored).

Ground truth is read only in this module, and only to build labels.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .. import config as C
from ..io import write_csv, write_json
from .engine import train_days

ALERT_LEVELS = ["MEDIUM", "HIGH", "CRITICAL"]
LEVEL_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def load_failures(data_dir: Path) -> pd.DataFrame:
    gt = pd.read_csv(data_dir / "ground_truth" / "ground_truth.csv", parse_dates=["start_ts", "end_ts"])
    wo = pd.read_csv(data_dir / "maintenance_work_orders.csv", parse_dates=["end_ts"])
    f = gt[gt["category"] == "MACHINE_FAILURE"][["record_id", "machine_id", "issue_type", "start_ts", "end_ts", "related_id"]]
    f = f.rename(columns={"record_id": "failure_id", "issue_type": "failure_mode", "start_ts": "onset_ts",
                          "end_ts": "failure_ts", "related_id": "work_order_id"})
    return f.merge(wo[["work_order_id", "end_ts"]].rename(columns={"end_ts": "repair_end_ts"}), on="work_order_id")


def split_bounds(days: int) -> dict:
    a, b = train_days(days), 2 * days // 3
    return {"train": (1, a), "validation": (a, b), "test": (b, days)}  # [start, end) in eval days


def label(scores: pd.DataFrame, failures: pd.DataFrame, days: int) -> pd.DataFrame:
    h = timedelta(days=C.RISK_HORIZON_DAYS)
    out = scores.copy()
    out["fails_within_horizon"] = False
    out["machine_down"] = False
    for f in failures.itertuples():
        m = out["machine_id"] == f.machine_id
        out.loc[m & (out["eval_ts"] < f.failure_ts) & (out["eval_ts"] + h >= f.failure_ts), "fails_within_horizon"] = True
        out.loc[m & (out["eval_ts"] >= f.failure_ts) & (out["eval_ts"] <= f.repair_end_ts), "machine_down"] = True
    out["split"] = None
    for name, (lo, hi) in split_bounds(days).items():
        keep = ((out["eval_day"] >= lo) & (out["eval_day"] + C.RISK_HORIZON_DAYS <= hi) & ~out["machine_down"])
        out.loc[keep, "split"] = name
    return out


def confusion(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    tp = int(np.sum(y_true & y_pred)); fp = int(np.sum(~y_true & y_pred))
    fn = int(np.sum(y_true & ~y_pred)); tn = int(np.sum(~y_true & ~y_pred))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "points": tp + fp + fn + tn,
            "precision": _r(precision), "recall": _r(recall), "f1": _r(f1),
            "false_positive_rate": _r(fp / (fp + tn) if fp + tn else None)}


def _r(x):
    return None if x is None else round(float(x), 4)


def event_metrics(points: pd.DataFrame, failures: pd.DataFrame, alert: pd.Series, lo_ts, hi_ts) -> dict:
    """Per failure in [lo_ts, hi_ts): was there an alert in the 7 days before it, and how early?"""
    h = timedelta(days=C.RISK_HORIZON_DAYS)
    rows = []
    for f in failures[(failures["failure_ts"] >= lo_ts) & (failures["failure_ts"] < hi_ts)].itertuples():
        w = points[(points["machine_id"] == f.machine_id) & (points["eval_ts"] < f.failure_ts)
                   & (points["eval_ts"] >= f.failure_ts - h) & alert]
        first = w["eval_ts"].min() if len(w) else None
        rows.append({"failure_id": f.failure_id, "failure_mode": f.failure_mode, "detected": first is not None,
                     "lead_time_hours": None if first is None else (f.failure_ts - first).total_seconds() / 3600})
    ev = pd.DataFrame(rows, columns=["failure_id", "failure_mode", "detected", "lead_time_hours"])
    lead = ev["lead_time_hours"].dropna()
    by_mode = {m: {"failures": len(g), "detected": int(g["detected"].sum()),
                   "median_lead_hours": _r(g["lead_time_hours"].median()) if g["detected"].any() else None}
               for m, g in ev.groupby("failure_mode")}
    return {"failures": len(ev), "detected": int(ev["detected"].sum()),
            "event_recall": _r(ev["detected"].mean()) if len(ev) else None,
            "lead_time_hours": {"mean": _r(lead.mean()) if len(lead) else None,
                                "median": _r(lead.median()) if len(lead) else None,
                                "min": _r(lead.min()) if len(lead) else None,
                                "max": _r(lead.max()) if len(lead) else None},
            "by_failure_mode": by_mode, "events": ev}


def evaluate(data_dir, log=print) -> dict:
    data_dir = Path(data_dir)
    days = json.loads((data_dir / "manifest.json").read_text())["scale"]["days"]
    risk = data_dir / "risk"
    scores = pd.read_csv(risk / "risk_scores.csv", parse_dates=["eval_ts"])
    features = pd.read_csv(risk / "features.csv", parse_dates=["eval_ts"])
    failures = load_failures(data_dir)
    pts = label(scores, failures, days)
    rank = pts["risk_level"].map(LEVEL_RANK)
    bounds = split_bounds(days)
    ts_of = lambda d: pd.Timestamp(C.SIM_START + timedelta(days=d))  # noqa: E731

    # 1. Choose the alert level on VALIDATION only.
    val = pts[pts["split"] == "validation"]
    choice = {lvl: confusion(val["fails_within_horizon"].to_numpy(),
                             (val["risk_level"].map(LEVEL_RANK) >= LEVEL_RANK[lvl]).to_numpy())
              for lvl in ALERT_LEVELS}
    chosen = max(ALERT_LEVELS, key=lambda l: (choice[l]["f1"] or 0, LEVEL_RANK[l]))
    alert = rank >= LEVEL_RANK[chosen]

    # 2. Metrics per split at the chosen level.
    splits, events_all = {}, []
    for name, (lo, hi) in bounds.items():
        s = pts["split"] == name
        ev = event_metrics(pts, failures, alert, ts_of(lo), ts_of(hi))
        events_all.append(ev.pop("events").assign(split=name))
        splits[name] = {"eval_days": [lo, hi - 1],
                        "point_level": confusion(pts.loc[s, "fails_within_horizon"].to_numpy(), alert[s].to_numpy()),
                        "failure_level": ev}

    # 3. Test results at every level (for transparency; the choice was already made).
    test = pts["split"] == "test"
    test_by_level = {lvl: confusion(pts.loc[test, "fails_within_horizon"].to_numpy(),
                                    (rank[test] >= LEVEL_RANK[lvl]).to_numpy()) for lvl in ALERT_LEVELS}

    # 4. Simple baselines on the same test points.
    f = features.set_index(["machine_id", "eval_day"]).loc[list(zip(pts["machine_id"], pts["eval_day"]))]
    sensors = pd.read_csv(data_dir / "sensors.csv")
    temp_nom = pts["machine_id"].map(sensors[sensors["sensor_type"] == "TEMP"].set_index("machine_id")["nominal_value"])
    baselines = {
        "maintenance_overdue_only": (f["service_history_known"].to_numpy() & (f["wear_ratio"].to_numpy() > 1)),
        "single_sensor_normal_band": ((f["vib_excess"] > C.NORMAL_BAND["VIB"]).to_numpy()
                                      | (f["temp_excess_c"].to_numpy() > C.NORMAL_BAND["TEMP"] * temp_nom.to_numpy())
                                      | (f["pres_drop"] > C.NORMAL_BAND["PRES"]).to_numpy()
                                      | (f["curr_excess"] > C.NORMAL_BAND["CURR"]).to_numpy()),
    }
    baseline_results = {}
    for name, pred in baselines.items():
        pred = pd.Series(pred, index=pts.index)
        baseline_results[name] = {
            "point_level": confusion(pts.loc[test, "fails_within_horizon"].to_numpy(), pred[test].to_numpy()),
            "failure_level": {k: v for k, v in event_metrics(pts, failures, pred, ts_of(bounds["test"][0]),
                                                             ts_of(bounds["test"][1])).items() if k != "events"}}

    # 5. Sensor faults: did the engine raise a sensor alert, or wrongly a machine alert?
    gt = pd.read_csv(data_dir / "ground_truth" / "ground_truth.csv", parse_dates=["start_ts", "end_ts"])
    sf_rows = []
    for g in gt[gt["category"] == "SENSOR_FAULT"].itertuples():
        group = g.sensor_id.split("-")[-2]
        w = pts[(pts["machine_id"] == g.machine_id) & (pts["eval_ts"] > g.start_ts)
                & (pts["eval_ts"] <= g.end_ts + timedelta(days=1))]
        if not len(w):
            continue
        sf_rows.append({"fault_type": g.issue_type, "points": len(w),
                        "sensor_alert": int(w["sensor_alerts"].fillna("").str.contains(f"{group} sensor").sum()),
                        "machine_alert": int(alert[w.index].sum())})
    sf = pd.DataFrame(sf_rows, columns=["fault_type", "points", "sensor_alert", "machine_alert"])
    sensor_faults = {t: {"faults": len(g), "eval_points": int(g["points"].sum()),
                         "with_sensor_alert": int(g["sensor_alert"].sum()),
                         "with_machine_alert": int(g["machine_alert"].sum())}
                     for t, g in sf.groupby("fault_type")}

    report = {
        "label": f"machine fails within {C.RISK_HORIZON_DAYS} days after the evaluation time",
        "evaluation_points": "one per machine per day at 06:00",
        "splits": {k: {"eval_days": [lo, hi - 1]} for k, (lo, hi) in bounds.items()},
        "alert_level_selection": {"chosen": chosen, "selected_on": "validation",
                                  "validation_by_level": choice},
        "results": splits,
        "test_by_level": test_by_level,
        "baselines_on_test": baseline_results,
        "sensor_fault_handling": sensor_faults,
    }
    write_json(report, risk / "evaluation_report.json")
    write_csv(pd.concat(events_all, ignore_index=True), risk / "failure_detection.csv")
    write_csv(pts[["machine_id", "eval_day", "eval_ts", "risk_score", "risk_level", "split",
                   "fails_within_horizon", "machine_down"]], risk / "evaluation_points.csv")
    (risk / "evaluation_summary.md").write_text(summary(report), encoding="utf-8")
    log(summary(report))
    return report


def summary(r: dict) -> str:
    t = r["results"]["test"]
    lines = [f"# Risk engine evaluation", "",
             f"Label: {r['label']}. Evaluation points: {r['evaluation_points']}.", "",
             "| Split | Eval days | Points | Failures |", "|---|---|---:|---:|"]
    for name, s in r["results"].items():
        lines.append(f"| {name} | {s['eval_days'][0]}-{s['eval_days'][1]} | {s['point_level']['points']} "
                     f"| {s['failure_level']['failures']} |")
    lines += ["", f"Alert level chosen on validation: **{r['alert_level_selection']['chosen']} or above**.", "",
              "## Test results (chosen level)", "",
              "| Metric | Value |", "|---|---:|"]
    p, e = t["point_level"], t["failure_level"]
    for k in ("precision", "recall", "f1", "false_positive_rate"):
        lines.append(f"| {k.replace('_', ' ')} (machine-days) | {p[k]} |")
    lines += [f"| failures detected before they happened | {e['detected']} / {e['failures']} ({e['event_recall']}) |",
              f"| median lead time (hours) | {e['lead_time_hours']['median']} |",
              f"| mean lead time (hours) | {e['lead_time_hours']['mean']} |", "",
              "Confusion matrix (test machine-days):", "",
              "| | predicted alert | predicted no alert |", "|---|---:|---:|",
              f"| fails within 7 days | {p['tp']} | {p['fn']} |",
              f"| does not fail | {p['fp']} | {p['tn']} |", "",
              "## Test results by alert level", "", "| Level | Precision | Recall | F1 | FPR |", "|---|---:|---:|---:|---:|"]
    for lvl, m in r["test_by_level"].items():
        lines.append(f"| {lvl}+ | {m['precision']} | {m['recall']} | {m['f1']} | {m['false_positive_rate']} |")
    lines += ["", "## By failure mode (test)", "", "| Mode | Failures | Detected | Median lead (h) |", "|---|---:|---:|---:|"]
    for mode, m in e["by_failure_mode"].items():
        lines.append(f"| {mode} | {m['failures']} | {m['detected']} | {m['median_lead_hours']} |")
    lines += ["", "## Baselines (test)", "", "| Approach | Precision | Recall | F1 | FPR | Failures detected |",
              "|---|---:|---:|---:|---:|---:|",
              f"| **Risk engine** | {p['precision']} | {p['recall']} | {p['f1']} | {p['false_positive_rate']} "
              f"| {e['detected']} / {e['failures']} |"]
    for name, b in r["baselines_on_test"].items():
        bp, be = b["point_level"], b["failure_level"]
        lines.append(f"| {name} | {bp['precision']} | {bp['recall']} | {bp['f1']} | {bp['false_positive_rate']} "
                     f"| {be['detected']} / {be['failures']} |")
    lines += ["", "## Sensor faults (all splits)", "",
              "| Fault type | Faults | Eval points during fault | Sensor alert raised | Machine alert raised |",
              "|---|---:|---:|---:|---:|"]
    for k, v in r["sensor_fault_handling"].items():
        lines.append(f"| {k} | {v['faults']} | {v['eval_points']} | {v['with_sensor_alert']} | {v['with_machine_alert']} |")
    return "\n".join(lines) + "\n"
