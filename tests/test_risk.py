"""Day 3 checks: no future leakage, label-free calibration, explainable scores, chronological
evaluation and correct metrics."""
from __future__ import annotations

import json
import shutil
from datetime import timedelta

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

from pipeline import config as C
from pipeline.generate import generate
from pipeline.risk import engine
from pipeline.risk.evaluate import confusion, evaluate, split_bounds
from pipeline.risk.features import build_features

SCALE = C.get_scale("starter")


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("day3")
    generate(SCALE, C.DEFAULT_SEED, out, log=lambda *_: None)
    result = engine.run(out, log=lambda *_: None)
    report = evaluate(out, log=lambda *_: None)
    return out, result, report


# ---------------------------------------------------------------- leakage -----------

def _poison_future(src, dst, cutoff_day: int):
    """Copy a dataset and wreck everything from cutoff_day on: telemetry x10, future work orders,
    failures and state changes removed, ground truth deleted."""
    shutil.copytree(src, dst)
    cutoff = pd.Timestamp(C.SIM_START + timedelta(days=cutoff_day))
    for path in (dst / "telemetry").glob("*.parquet"):
        t = pq.read_table(path)
        future = pc.greater_equal(t["ts"], pa.scalar(cutoff.to_pydatetime(), t.schema.field("ts").type))
        t = t.set_column(t.schema.get_field_index("value"), "value",
                         pc.if_else(future, pc.multiply(t["value"], 10.0), t["value"]))
        pq.write_table(t, path)
    wo = pd.read_csv(dst / "maintenance_work_orders.csv")
    wo[pd.to_datetime(wo["created_ts"]) < cutoff].to_csv(dst / "maintenance_work_orders.csv", index=False)
    fe = pd.read_csv(dst / "failure_events.csv")
    fe[pd.to_datetime(fe["failure_ts"]) < cutoff].to_csv(dst / "failure_events.csv", index=False)
    h = pd.read_csv(dst / "machine_state_history.csv")
    h.loc[pd.to_datetime(h["start_ts"]) >= cutoff, "state"] = "RUNNING"  # garbage future context
    h.to_csv(dst / "machine_state_history.csv", index=False)
    shutil.rmtree(dst / "ground_truth")


def test_features_never_use_future_data_or_ground_truth(run, tmp_path):
    out, result, _ = run
    cutoff_day = 15
    _poison_future(out, tmp_path / "poisoned", cutoff_day)
    poisoned = build_features(tmp_path / "poisoned")  # also proves ground truth is not needed
    clean = result["features"]
    keep = lambda f: f[f["eval_day"] <= cutoff_day].reset_index(drop=True)  # noqa: E731
    pd.testing.assert_frame_equal(keep(clean), keep(poisoned))
    # Sanity: the poison really changed the future, so the test is not vacuous.
    later = lambda f: f[f["eval_day"] > cutoff_day + 1]["vib_excess"].dropna()  # noqa: E731
    assert later(poisoned).mean() > later(clean).mean() + 1


def test_calibration_uses_only_the_training_period(run):
    _, result, _ = run
    f = result["features"].copy()
    days = SCALE.days
    before = engine.calibrate(f, engine.train_days(days))
    f.loc[f["eval_day"] >= engine.train_days(days), [x for x, *_ in C.RISK_FEATURES]] = 1e6
    assert engine.calibrate(f, engine.train_days(days)) == before


def test_feature_columns_contain_no_labels(run):
    out, _, _ = run
    cols = set(pd.read_csv(out / "risk" / "features.csv", nrows=0).columns)
    assert not cols & {"fails_within_horizon", "failure_mode", "onset_ts", "issue_type", "label", "split"}


# ---------------------------------------------------------------- scoring -----------

def test_scores_are_bounded_explained_and_banded(run):
    out, _, _ = run
    s = pd.read_csv(out / "risk" / "risk_scores.csv").fillna("")
    for r in s.itertuples():
        contrib = json.loads(r.contributions)
        assert 0 <= r.risk_score <= 100
        assert abs(r.risk_score - min(100, sum(contrib.values()))) < 0.051
        assert r.risk_level == engine.level_of(r.risk_score)
        if r.risk_level != "LOW":
            assert r.reasons and r.recommended_action != C.LEVEL_ACTION["LOW"]


def _row(thresholds, **over):
    row = {f: t["centre"] for f, t in thresholds.items()}
    row.update({f"{k}_quality": "OK" for k in ("temp", "vib", "pres", "curr")},
               service_history_known=True, wear_ratio=0.5, days_since_service=10, failures_30d=0)
    row.update(over)
    return pd.Series(row)


def test_one_strong_sensor_group_alerts_and_two_groups_escalate(run):
    _, result, _ = run
    th = result["thresholds"]
    normal = engine.score_row(_row(th), th)
    assert normal["risk_level"] == "LOW" and normal["risk_score"] == 0
    one = engine.score_row(_row(th, vib_excess=th["vib_excess"]["strong"], vib_trend=th["vib_trend"]["strong"]), th)
    assert one["risk_level"] == "MEDIUM" and one["risk_score"] == 40
    assert "bearings" in one["recommended_action"]
    two = engine.score_row(_row(th, vib_excess=th["vib_excess"]["strong"], vib_trend=th["vib_trend"]["strong"],
                                temp_excess_c=th["temp_excess_c"]["strong"]), th)
    assert two["risk_level"] in ("HIGH", "CRITICAL")
    assert json.loads(two["contributions"])["corroboration"] == C.RISK_CORROBORATION_POINTS


def test_faulty_sensor_raises_sensor_alert_not_machine_risk(run):
    _, result, _ = run
    th = result["thresholds"]
    r = engine.score_row(_row(th, temp_excess_c=50.0, temp_trend_c=30.0, temp_quality="STUCK"), th)
    assert r["risk_score"] == 0 and r["risk_level"] == "LOW"
    assert "TEMP sensor STUCK" in r["sensor_alerts"]


def test_scoring_is_reproducible(run, tmp_path):
    out, _, _ = run
    copy = tmp_path / "again"
    shutil.copytree(out, copy)
    shutil.rmtree(copy / "risk")
    engine.run(copy, log=lambda *_: None)
    assert (copy / "risk" / "risk_scores.csv").read_bytes() == (out / "risk" / "risk_scores.csv").read_bytes()


# ---------------------------------------------------------------- evaluation --------

def test_confusion_metrics_by_hand():
    y = np.array([True, True, True, False, False, False, False, False])
    p = np.array([True, True, False, True, False, False, False, False])
    m = confusion(y, p)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 4)
    assert m["precision"] == round(2 / 3, 4) and m["recall"] == round(2 / 3, 4)
    assert m["f1"] == round(2 / 3, 4) and m["false_positive_rate"] == 0.2


def test_splits_are_chronological_and_purged(run):
    out, _, _ = run
    pts = pd.read_csv(out / "risk" / "evaluation_points.csv")
    bounds = split_bounds(SCALE.days)
    assert bounds["train"][1] == bounds["validation"][0] and bounds["validation"][1] == bounds["test"][0]
    for name, (lo, hi) in bounds.items():
        s = pts[pts["split"] == name]
        assert len(s) > 0
        assert s["eval_day"].min() >= lo and (s["eval_day"] + C.RISK_HORIZON_DAYS).max() <= hi
    assert not pts.loc[pts["machine_down"], "split"].notna().any()


def test_alert_level_choice_ignores_the_test_period(run, tmp_path):
    """Delete every failure after the validation period from ground truth: the chosen alert
    level must not change, because it is selected on validation labels only."""
    out, _, report = run
    copy = tmp_path / "no_test_failures"
    shutil.copytree(out, copy)
    gt = pd.read_csv(copy / "ground_truth" / "ground_truth.csv")
    val_end = pd.Timestamp(C.SIM_START + timedelta(days=split_bounds(SCALE.days)["validation"][1]))
    drop = (gt["category"] == "MACHINE_FAILURE") & (pd.to_datetime(gt["end_ts"]) >= val_end)
    gt[~drop].to_csv(copy / "ground_truth" / "ground_truth.csv", index=False)
    again = evaluate(copy, log=lambda *_: None)
    assert again["alert_level_selection"] == report["alert_level_selection"]
    assert again["results"]["test"]["failure_level"]["failures"] == 0


def test_report_is_computed_from_points(run):
    out, _, report = run
    pts = pd.read_csv(out / "risk" / "evaluation_points.csv")
    chosen = report["alert_level_selection"]["chosen"]
    rank = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
    test = pts[pts["split"] == "test"]
    expected = confusion(test["fails_within_horizon"].to_numpy(),
                         (test["risk_level"].map(rank) >= rank[chosen]).to_numpy())
    assert report["results"]["test"]["point_level"] == expected
