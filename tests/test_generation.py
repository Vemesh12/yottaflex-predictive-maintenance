"""Day 1 checks: volumes, ID conventions, keys, operating context and reproducibility.

Runs on the starter scale so the whole suite takes a few seconds.
"""
from __future__ import annotations

import json

import pandas as pd
import pyarrow.parquet as pq
import pytest

from pipeline import config as C
from pipeline.generate import generate
from pipeline.ids import PATTERNS
from pipeline.load import load

SCALE = C.get_scale("starter")


def _read(out):
    tables = {name: pd.read_csv(out / f"{name}.csv") for name in [
        "plants", "production_lines", "machines", "sensors", "operating_shifts", "technicians",
        "parts", "machine_state_history"]}
    tables["telemetry"] = pq.read_table(out / "telemetry").to_pandas()
    return tables


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    out = tmp_path_factory.mktemp("starter")
    manifest = generate(SCALE, C.DEFAULT_SEED, out, log=lambda *_: None)
    return out, manifest, _read(out)


def test_volumes_match_scale(run):
    _, _, t = run
    assert len(t["plants"]) == SCALE.plants
    assert len(t["production_lines"]) == SCALE.lines
    assert len(t["machines"]) == SCALE.machines
    assert len(t["sensors"]) == SCALE.machines * len(C.SENSOR_TYPES)
    assert len(t["operating_shifts"]) == SCALE.plants * SCALE.days * 3
    assert len(t["telemetry"]) == len(t["sensors"]) * SCALE.slots


def test_full_scale_meets_required_volume():
    full = C.get_scale("full")
    assert (full.plants, full.lines, full.machines) == (3, 12, 100)
    assert full.machines * len(C.SENSOR_TYPES) == 500
    readings = full.machines * len(C.SENSOR_TYPES) * full.slots
    assert 1_000_000 <= readings <= 3_000_000
    assert full.days == 90


@pytest.mark.parametrize("table,column", [
    ("plants", "plant_id"), ("production_lines", "line_id"), ("machines", "machine_id"),
    ("sensors", "sensor_id"), ("operating_shifts", "shift_id"), ("technicians", "technician_id"),
    ("parts", "part_id"), ("machine_state_history", "state_event_id"), ("telemetry", "telemetry_id"),
])
def test_primary_keys_unique_and_well_formed(run, table, column):
    _, _, t = run
    col = t[table][column]
    assert col.is_unique
    assert col.map(lambda v: bool(PATTERNS[column].match(v))).all(), f"bad {column} format"


@pytest.mark.parametrize("child,fk,parent,pk", [
    ("production_lines", "plant_id", "plants", "plant_id"),
    ("machines", "line_id", "production_lines", "line_id"),
    ("sensors", "machine_id", "machines", "machine_id"),
    ("operating_shifts", "plant_id", "plants", "plant_id"),
    ("technicians", "plant_id", "plants", "plant_id"),
    ("machine_state_history", "machine_id", "machines", "machine_id"),
    ("machine_state_history", "shift_id", "operating_shifts", "shift_id"),
    ("telemetry", "sensor_id", "sensors", "sensor_id"),
    ("telemetry", "machine_id", "machines", "machine_id"),
])
def test_foreign_keys_resolve(run, child, fk, parent, pk):
    _, _, t = run
    assert set(t[child][fk]) <= set(t[parent][pk])


def test_child_ids_embed_parent_ids(run):
    _, _, t = run
    assert (t["production_lines"].apply(lambda r: r.line_id.startswith(f"LINE-{r.plant_id}-"), axis=1)).all()
    assert (t["machines"].apply(lambda r: r.machine_id.startswith(f"MCH-{r.line_id}-"), axis=1)).all()
    assert (t["sensors"].apply(lambda r: r.sensor_id == f"SNS-{r.machine_id}-{r.sensor_type}-01", axis=1)).all()
    # Telemetry's machine_id must be the machine that owns the sensor.
    owner = t["sensors"].set_index("sensor_id")["machine_id"]
    assert (t["telemetry"]["sensor_id"].map(owner) == t["telemetry"]["machine_id"]).all()


def test_dates_in_order(run):
    _, _, t = run
    plant_date = t["plants"].set_index("plant_id")["commissioned_date"]
    lines = t["production_lines"]
    assert (lines["commissioned_date"] >= lines["plant_id"].map(plant_date)).all()
    line_date = lines.set_index("line_id")["commissioned_date"]
    machines = t["machines"]
    assert (machines["install_date"] >= machines["line_id"].map(line_date)).all()
    assert (machines["install_date"] < C.SIM_START.date().isoformat()).all()


def test_state_history_is_contiguous_per_machine(run):
    _, _, t = run
    h = t["machine_state_history"].copy()
    h["start_ts"] = pd.to_datetime(h["start_ts"])
    h["end_ts"] = pd.to_datetime(h["end_ts"])
    window_end = pd.Timestamp(C.SIM_START) + pd.Timedelta(days=SCALE.days)
    for _, g in h.sort_values("start_ts").groupby("machine_id"):
        assert g["start_ts"].iloc[0] == pd.Timestamp(C.SIM_START)
        assert g["end_ts"].iloc[-1] == window_end
        nxt, cur = g.iloc[1:].reset_index(drop=True), g.iloc[:-1].reset_index(drop=True)
        assert (nxt["start_ts"] == cur["end_ts"]).all()  # no gap, no overlap
        assert (nxt["previous_state"] == cur["state"]).all()
        assert ((g["end_ts"] - g["start_ts"]).dt.total_seconds() / 60 == g["duration_min"]).all()


def test_telemetry_follows_operating_state(run):
    out, _, t = run
    import duckdb
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT s.state, se.sensor_type, t.value, se.range_min, se.range_max
        FROM read_parquet('{(out / 'telemetry' / '*.parquet').as_posix()}') t
        JOIN read_csv('{(out / 'sensors.csv').as_posix()}') se USING (sensor_id)
        JOIN read_csv('{(out / 'machine_state_history.csv').as_posix()}') s
          ON s.machine_id = t.machine_id AND t.ts >= s.start_ts AND t.ts < s.end_ts
    """).df()
    assert len(df) == len(t["telemetry"])  # every reading falls in exactly one state segment
    assert df["value"].between(df["range_min"], df["range_max"]).all()
    rpm = df[df["sensor_type"] == "RPM"]
    assert (rpm.loc[rpm["state"] == "RUNNING", "value"] > 0).all()
    assert (rpm.loc[rpm["state"] != "RUNNING", "value"] == 0).all()
    temp = df[df["sensor_type"] == "TEMP"]
    assert temp.loc[temp["state"] == "RUNNING", "value"].mean() > temp.loc[temp["state"] == "SHUTDOWN", "value"].mean()


def test_shift_calendar(run):
    _, _, t = run
    s = t["operating_shifts"]
    weekday = pd.to_datetime(s["shift_date"]).dt.day_of_week
    assert (s.loc[weekday == 6, "planned_status"] != "PRODUCTION").all()  # Sunday off
    assert (s.loc[(weekday == 5) & (s["shift_code"] == "C"), "planned_status"] != "PRODUCTION").all()


def test_same_seed_is_reproducible(run, tmp_path):
    _, first, _ = run
    second = generate(SCALE, C.DEFAULT_SEED, tmp_path, log=lambda *_: None)
    assert first["files"] == second["files"]  # identical row counts and SHA-256 for every file


def test_different_seed_changes_data(run, tmp_path):
    _, first, _ = run
    other = generate(SCALE, C.DEFAULT_SEED + 1, tmp_path, log=lambda *_: None)
    assert first["files"]["sensors.csv"]["sha256"] != other["files"]["sensors.csv"]["sha256"]


def test_manifest_written(run):
    out, manifest, _ = run
    on_disk = json.loads((out / "manifest.json").read_text())
    assert on_disk["seed"] == C.DEFAULT_SEED
    assert on_disk["files"] == manifest["files"]


def test_duckdb_load_enforces_constraints(run):
    out, _, _ = run
    db = load(out, log=lambda *_: None)
    import duckdb
    con = duckdb.connect(str(db), read_only=True)
    assert con.execute("SELECT count(*) FROM telemetry_event").fetchone()[0] == SCALE.machines * 5 * SCALE.slots
    con.close()
