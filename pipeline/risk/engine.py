"""Explainable rule-based risk engine.

score (0-100) = sum of named point contributions, capped at 100, so every score can be read back
as reasons:
  - sensor evidence (config.RISK_FEATURES, up to 40 per sensor group): each feature earns 50% of
    its points at the "moderate" threshold rising to 100% at the "strong" threshold;
  - corroboration (+10): 2 or more sensor groups abnormal at once. A real machine fault shows up on
    several sensors; a single misbehaving sensor usually does not;
  - maintenance overdue (+3) and a failure in the last 30 days (+2).
A sensor whose data-quality flag is not OK (stuck, dropout, spikes) contributes NO machine-risk
points; it raises a separate instrumentation alert instead. This is how sensor faults are kept from
being reported as machine faults.

Calibration: thresholds are learned from the TRAINING period only, without labels, as
  centre = median,  spread = 1.4826 x MAD (robust standard deviation)
  moderate = centre + 3 x spread,  strong = centre + 5 x spread
Median/MAD barely move when a few machines are degrading, so the training period does not need
labels to learn what "normal" looks like.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .. import config as C

QUALITY_COL = {"TEMP": "temp_quality", "VIB": "vib_quality", "PRES": "pres_quality", "CURR": "curr_quality"}


def calibrate(features: pd.DataFrame, train_days: int) -> dict:
    """Learn moderate/strong thresholds per feature from the training period (eval_day < train_days)."""
    train = features[features["eval_day"] < train_days]
    thresholds = {}
    for feat, group, _, _ in C.RISK_FEATURES:
        v = train.loc[train[QUALITY_COL[group]] == "OK", feat].dropna()
        centre = float(v.median())
        spread = max(1.4826 * float((v - centre).abs().median()), 1e-9)
        thresholds[feat] = {"centre": centre, "spread": spread,
                            "moderate": centre + C.THRESHOLD_MODERATE_K * spread,
                            "strong": centre + C.THRESHOLD_STRONG_K * spread,
                            "n_train": int(len(v))}
    return thresholds


def level_of(score: float) -> str:
    return next(name for cut, name in C.RISK_LEVELS if score >= cut)


def score_row(row, thresholds: dict) -> dict:
    contributions: dict[str, float] = {}
    reasons: list[tuple[float, str, str]] = []
    abnormal_groups: set[str] = set()
    sensor_alerts = []

    for group, qcol in QUALITY_COL.items():
        if row[qcol] not in ("OK", "NO_DATA"):
            sensor_alerts.append(f"{group} sensor {row[qcol]}: instrumentation check, readings ignored")

    for feat, group, weight, template in C.RISK_FEATURES:
        v = row[feat]
        if row[QUALITY_COL[group]] != "OK" or pd.isna(v):
            continue
        t = thresholds[feat]
        if v < t["moderate"]:
            continue
        frac = 0.5 + 0.5 * min(1.0, (v - t["moderate"]) / (t["strong"] - t["moderate"]))
        pts = round(weight * frac, 1)
        contributions[feat] = pts
        abnormal_groups.add(group)
        reasons.append((pts, group, template.format(v=v)))

    if len(abnormal_groups) >= 2:
        contributions["corroboration"] = C.RISK_CORROBORATION_POINTS
        reasons.append((C.RISK_CORROBORATION_POINTS, "",
                        f"{len(abnormal_groups)} sensor groups abnormal together ({', '.join(sorted(abnormal_groups))})"))
    if row["service_history_known"] and row["wear_ratio"] > 1:
        contributions["maintenance_overdue"] = C.RISK_OVERDUE_POINTS
        reasons.append((C.RISK_OVERDUE_POINTS, "",
                        f"Preventive maintenance overdue ({row['days_since_service']:.0f} days since service)"))
    if row["failures_30d"] >= 1:
        contributions["recent_failure"] = C.RISK_RECENT_FAILURE_POINTS
        reasons.append((C.RISK_RECENT_FAILURE_POINTS, "", f"{int(row['failures_30d'])} failure(s) in last 30 days"))

    score = round(min(float(C.RISK_SCORE_CAP), sum(contributions.values())), 1)
    level = level_of(score)
    reasons.sort(key=lambda r: -r[0])
    top_group = next((g for _, g, _ in reasons if g), None)
    action = C.LEVEL_ACTION[level]
    if top_group and level != "LOW":
        action += f": {C.GROUP_ACTION[top_group]}"
    return {"risk_score": score, "risk_level": level,
            "reasons": "; ".join(text for _, _, text in reasons),
            "recommended_action": action,
            "sensor_alerts": "; ".join(sensor_alerts),
            "contributions": json.dumps(contributions, sort_keys=True)}


def score(features: pd.DataFrame, thresholds: dict) -> pd.DataFrame:
    scored = pd.DataFrame([score_row(r, thresholds) for _, r in features.iterrows()], index=features.index)
    return pd.concat([features[["machine_id", "eval_day", "eval_ts"]], scored], axis=1)


def train_days(days: int) -> int:
    return days // 3


def run(data_dir, log=print) -> dict:
    """Features -> calibrate on training period -> score every machine-day. Writes risk/ outputs."""
    from pathlib import Path

    from ..export import write_json as write_records
    from ..io import write_csv, write_json
    from .features import build_features

    data_dir = Path(data_dir)
    days = json.loads((data_dir / "manifest.json").read_text())["scale"]["days"]
    features = build_features(data_dir)
    thresholds = calibrate(features, train_days(days))
    scores = score(features, thresholds)

    out = data_dir / "risk"
    out.mkdir(exist_ok=True)
    write_csv(features, out / "features.csv")
    write_csv(scores, out / "risk_scores.csv")
    write_json({"train_days": train_days(days), "thresholds": thresholds}, out / "calibration.json")
    # "Now": the latest evaluation (end of the window), ranked: the plant's work list.
    current = (scores[scores["eval_day"] == days]
               .sort_values(["risk_score", "machine_id"], ascending=[False, True]))
    write_csv(current, out / "current_risk.csv")
    write_records(current, out / "current_risk.json")
    counts = current["risk_level"].value_counts().to_dict()
    log(f"scored {len(scores):,} machine-days; now: " +
        ", ".join(f"{k} {counts.get(k, 0)}" for _, k in C.RISK_LEVELS) +
        f"; sensor alerts {int((current['sensor_alerts'] != '').sum())} -> {out}")
    return {"features": features, "scores": scores, "thresholds": thresholds}
