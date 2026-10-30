"""Day 2 checks: failures and drift, sensor faults, work orders, edge cases, ground-truth
separation, validation and exports."""
from __future__ import annotations

import json
import shutil

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from pipeline import config as C
from pipeline.generate import TABLE_FILES, generate, master, plan_machine
from pipeline.generate.failures import drift_profile
from pipeline.generate.telemetry import TimeGrid, machine_telemetry
from pipeline.validate import validate

SCALE = C.get_scale("starter")
SEED = C.DEFAULT_SEED
SPD = 24 * 60 // SCALE.interval_min


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("day2")
    generate(SCALE, SEED, out, log=lambda *_: None)
    report = validate(out, log=lambda *_: None)
    return out, report


def _csv(out, name):
    return pd.read_csv(out / name)


# ---------------------------------------------------------------- failures ----------

def test_full_scale_failure_count_in_required_range():
    """Planning only (no telemetry), so the full 100-machine scale stays fast."""
    scale = C.get_scale("full")
    plants = master.build_plants(scale, SEED)
    lines = master.build_lines(plants, scale, SEED)
    machines = master.build_machines(lines, scale, SEED)
    sensors = master.build_sensors(machines, scale, SEED)
    shifts = master.build_shifts(plants, scale, SEED)
    plant_of = dict(zip(lines["line_id"], lines["plant_id"]))
    by_plant = {p: g.sort_values("start_ts").reset_index(drop=True) for p, g in shifts.groupby("plant_id")}
    by_machine = {m: g for m, g in sensors.groupby("machine_id", sort=False)}
    total = sum(len(plan_machine(m, by_plant[plant_of[m.line_id]], by_machine[m.machine_id],
                                 scale, SEED)["failures"]) for m in machines.itertuples())
    assert 100 <= total <= 200


def test_failure_timeline_is_consistent(run):
    out, _ = run
    fe = _csv(out, "failure_events.csv")
    gt = _csv(out, "ground_truth/ground_truth.csv")
    hist = _csv(out, "machine_state_history.csv")
    assert len(fe) > 0
    onset = gt[gt["category"] == "MACHINE_FAILURE"].set_index("record_id")["start_ts"]
    for f in fe.itertuples():
        t_fail, t_onset = pd.Timestamp(f.failure_ts), pd.Timestamp(onset[f.failure_id])
        assert t_onset >= pd.Timestamp(C.SIM_START) and t_onset < t_fail
        if f.failure_mode in C.GRADUAL_MODES:
            assert t_onset <= pd.Timestamp(f.first_symptom_ts) < t_fail
        # FAILED starts exactly at the failure, followed by corrective repair.
        h = hist[hist["machine_id"] == f.machine_id].reset_index(drop=True)
        i = h.index[(h["state"] == "FAILED") & (h["start_ts"] == f.failure_ts)][0]
        assert h.loc[i + 1, "state"] == "MAINTENANCE" and h.loc[i + 1, "reason"] == "CORRECTIVE_REPAIR"
        assert h.loc[i, "work_order_id"] == h.loc[i + 1, "work_order_id"]


def _one_machine():
    plants = master.build_plants(SCALE, SEED)
    lines = master.build_lines(plants, SCALE, SEED)
    machines = master.build_machines(lines, SCALE, SEED)
    sensors = master.build_sensors(machines, SCALE, SEED)
    m = next(machines.itertuples())
    return m, sensors[sensors["machine_id"] == m.machine_id]


def _values(table, sensor_type):
    df = table.to_pandas()
    return df[df["sensor_id"].str.contains(f"-{sensor_type}-")]["value"].to_numpy()


def test_drift_builds_up_before_failure_only():
    m, sensors = _one_machine()
    grid = TimeGrid(SCALE)
    state = np.full(SCALE.slots, C.STATE_CODE["RUNNING"], dtype=np.int8)
    fail = {"failure_mode": "BEARING_WEAR", "onset_slot": 5 * SPD, "failure_slot": 12 * SPD}
    base = machine_telemetry(m, sensors, state, grid, 0, SEED)
    drifted = machine_telemetry(m, sensors, state, grid, 0, SEED, drift=drift_profile([fail], SCALE.slots))
    vb, vd = _values(base, "VIB"), _values(drifted, "VIB")
    assert np.array_equal(vb[:fail["onset_slot"]], vd[:fail["onset_slot"]])      # untouched before onset
    assert np.array_equal(vb[fail["failure_slot"]:], vd[fail["failure_slot"]:])  # and after failure
    last_day = slice(fail["failure_slot"] - SPD // 4, fail["failure_slot"])
    assert vd[last_day].mean() > 2.0 * vb[last_day].mean()  # signature: vibration ~2.6x near failure
    assert np.all(np.diff([vd[s:s + SPD].mean() for s in range(fail["onset_slot"], fail["failure_slot"], SPD)]) > -0.2)


# ---------------------------------------------------------------- sensor faults -----

@pytest.mark.parametrize("kind", C.SENSOR_FAULT_TYPES)
def test_sensor_fault_touches_only_one_sensor(kind):
    m, sensors = _one_machine()
    grid = TimeGrid(SCALE)
    state = np.full(SCALE.slots, C.STATE_CODE["RUNNING"], dtype=np.int8)
    temp_id = sensors[sensors["sensor_type"] == "TEMP"]["sensor_id"].iloc[0]
    fault = {"sensor_id": temp_id, "sensor_type": "TEMP", "fault_type": kind,
             "start_slot": 100, "end_slot": 160, "machine_id": m.machine_id}
    clean = machine_telemetry(m, sensors, state, grid, 0, SEED).to_pandas()
    faulty = machine_telemetry(m, sensors, state, grid, 0, SEED, faults=[fault]).to_pandas()
    other = clean["sensor_id"] != temp_id
    pd.testing.assert_frame_equal(clean[other], faulty[other])  # the machine's other sensors are untouched
    tc, tf = clean.loc[~other, "value"].to_numpy(), faulty.loc[~other, "value"].to_numpy()
    assert np.array_equal(tc[:100], tf[:100]) and np.array_equal(tc[160:], tf[160:])
    window = tf[100:160]
    if kind == "STUCK":
        assert np.all(window == window[0])
    elif kind == "DROPOUT":
        assert np.isnan(window).all()  # missing, not zero
    elif kind == "BIAS":
        assert np.allclose(window - tc[100:160], C.SENSOR_BIAS["TEMP"], atol=0.02)
    else:
        assert (window > 2 * tc[100:160]).sum() >= 3


def test_dropout_is_stored_as_null_not_zero(run):
    out, _ = run
    gt = _csv(out, "ground_truth/ground_truth.csv")
    drop = gt[(gt["category"] == "SENSOR_FAULT") & (gt["issue_type"] == "DROPOUT")]
    tel = pq.read_table(out / "telemetry").to_pandas()
    for f in drop.itertuples():
        w = tel[(tel["sensor_id"] == f.sensor_id) & (tel["ts"] >= pd.Timestamp(f.start_ts))
                & (tel["ts"] < pd.Timestamp(f.end_ts))]
        assert len(w) > 0 and w["value"].isna().all()


def test_every_sensor_fault_has_a_replacement_work_order(run):
    out, _ = run
    gt = _csv(out, "ground_truth/ground_truth.csv")
    wo = _csv(out, "maintenance_work_orders.csv").set_index("work_order_id")
    for f in gt[gt["category"] == "SENSOR_FAULT"].itertuples():
        w = wo.loc[f.related_id]
        assert w.work_order_type == "SENSOR_REPLACEMENT" and w.sensor_id == f.sensor_id
        assert w.downtime_min == 0  # replacing a sensor does not stop the machine


# ---------------------------------------------------------------- work orders -------

def test_work_order_values_are_derived(run):
    out, _ = run
    wo = _csv(out, "maintenance_work_orders.csv")
    parts = _csv(out, "work_order_parts.csv").groupby("work_order_id")["line_cost_inr"].sum()
    hist = _csv(out, "machine_state_history.csv").groupby("work_order_id")["duration_min"].sum()
    assert (wo["total_cost_inr"] == wo["labor_cost_inr"] + wo["parts_cost_inr"]).all()
    assert (wo["parts_cost_inr"] == wo["work_order_id"].map(parts).fillna(0)).all()
    assert (wo["downtime_min"] == wo["work_order_id"].map(hist).fillna(0)).all()
    assert set(wo["work_order_type"]) >= {"PREVENTIVE", "CORRECTIVE"}


def test_work_order_lifecycle(run):
    out, _ = run
    hist = _csv(out, "work_order_status_history.csv")
    wo = _csv(out, "maintenance_work_orders.csv").set_index("work_order_id")
    for wo_id, h in hist.groupby("work_order_id"):
        prev = None
        for r in h.sort_values("status_event_id").itertuples():
            assert r.to_status in C.WO_TRANSITIONS[prev]
            prev = r.to_status
        assert wo.loc[wo_id, "status"] == prev
        assert list(h["changed_ts"]) == sorted(h["changed_ts"])


# ---------------------------------------------------------------- edge cases & GT ---

def test_validator_clean_baseline_has_no_issues(run):
    _, report = run
    assert report["clean_baseline"]["unexpected_issues"] == []
    assert report["clean_baseline"]["checks_run"] >= 80


def test_validator_finds_every_injected_anomaly(run):
    _, report = run
    edge = report["received_with_exceptions"]["edge_case_detection"]
    assert set(edge) == {"UNKNOWN_SENSOR", "IMPOSSIBLE_VALUE", "IMPOSSIBLE_UNIT", "FAILURE_BEFORE_SYMPTOM",
                         "MAINTENANCE_END_BEFORE_START", "ZERO_FILLED_GAP"}
    for issue, r in edge.items():
        assert r["expected"] > 0, issue
        assert r["missed"] == 0 and r["false_positive"] == 0, issue
    assert all(s["all_on_injected_records"] for s in report["received_with_exceptions"]["secondary_findings"])


def test_validator_catches_corruption_it_was_not_told_about(run, tmp_path):
    """Proves results are computed, not hardcoded: break a copy of the clean data in ways the
    ground truth knows nothing about, and the clean-baseline checks must fail."""
    out, _ = run
    copy = tmp_path / "broken"
    shutil.copytree(out, copy)
    wo = pd.read_csv(copy / "maintenance_work_orders.csv")
    wo.loc[0, "total_cost_inr"] += 1
    wo.to_csv(copy / "maintenance_work_orders.csv", index=False)
    sensors = pd.read_csv(copy / "sensors.csv")
    sensors.loc[0, "machine_id"] = "MCH-LINE-PLT-001-001-999"
    sensors.to_csv(copy / "sensors.csv", index=False)
    report = validate(copy, log=lambda *_: None)
    failed = {u["name"] for u in report["clean_baseline"]["unexpected_issues"]}
    assert "reconcile:total_cost" in failed
    assert "fk:sensor.machine_id->machine" in failed
    assert report["passed"] is False


def test_clean_data_is_not_modified_by_edge_cases(run):
    out, _ = run
    tel = pq.read_table(out / "telemetry").to_pandas().set_index("telemetry_id")
    exc = _csv(out, "exceptions/telemetry_exceptions.csv")
    replaced = exc[exc["telemetry_id"].isin(tel.index)]
    added = exc[~exc["telemetry_id"].isin(tel.index)]
    assert set(added["sensor_id"]).isdisjoint(_csv(out, "sensors.csv")["sensor_id"])  # unknown sensors
    clean_vals = tel.loc[replaced["telemetry_id"], "value"].to_numpy()
    assert not np.any(clean_vals == replaced["value"].to_numpy())  # clean rows kept their true value
    fe = _csv(out, "failure_events.csv").dropna(subset=["first_symptom_ts"])
    assert (pd.to_datetime(fe["first_symptom_ts"]) < pd.to_datetime(fe["failure_ts"])).all()


def test_ground_truth_is_separate_from_features(run):
    out, _ = run
    label_words = {"ground_truth", "issue_type", "expected_decision", "label", "gt_id", "onset_ts"}
    for path in list(out.glob("*.csv")) + list((out / "exceptions").glob("*.csv")):
        assert not label_words & set(pd.read_csv(path, nrows=0).columns), path.name
    assert not label_words & set(pq.read_schema(next((out / "telemetry").glob("*.parquet"))).names)
    seed_sql = (out / "export" / "sql" / "seed.sql").read_text(encoding="utf-8")
    assert "INTO ground_truth" not in seed_sql and "TABLE ground_truth" not in seed_sql
    assert "GT-0" not in seed_sql
    gt = _csv(out, "ground_truth/ground_truth.csv")
    known = (set(_csv(out, "failure_events.csv")["failure_id"]) | set(_csv(out, "sensors.csv")["sensor_id"])
             | set(_csv(out, "exceptions/telemetry_exceptions.csv")["telemetry_id"])
             | set(_csv(out, "maintenance_work_orders.csv")["work_order_id"]))
    assert set(gt["record_id"]) <= known  # every label points at a real record


# ---------------------------------------------------------------- exports -----------

def test_json_exports_match_csv(run):
    out, _ = run
    for file in TABLE_FILES.values():
        records = json.loads((out / "export" / "json" / file.replace(".csv", ".json")).read_text(encoding="utf-8"))
        assert len(records) == len(_csv(out, file)), file


def test_sql_seed_rebuilds_the_database(run, monkeypatch):
    out, _ = run
    monkeypatch.chdir(out)  # the seed loads telemetry from a path relative to the data folder
    con = duckdb.connect()
    con.execute((out / "export" / "sql" / "seed.sql").read_text(encoding="utf-8"))
    from pipeline.load import LOAD_ORDER
    for table, file in LOAD_ORDER:
        assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == len(_csv(out, file)), table
    assert con.execute("SELECT count(*) FROM telemetry_event").fetchone()[0] == SCALE.machines * 5 * SCALE.slots
