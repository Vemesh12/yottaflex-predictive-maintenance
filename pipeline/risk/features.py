"""Feature engineering for the risk engine.

One evaluation point per machine per day, at 06:00 (eval_day e = SIM_START + e days). The features
of point e are built ONLY from:
  - daily telemetry summaries of days < e (readings taken while the machine was RUNNING),
  - work orders that were completed before the evaluation time,
  - failure events that happened before the evaluation time,
  - master data (sensor nominal values, machine install date, PM interval).
Ground truth is never read here.

After a completed maintenance job the telemetry history "resets": only days after the job are
used, because the repair changed the machine's condition.

Sensor features (normalised by the sensor's own nominal value, so all machines are comparable):
  <s>_level   mean of the most recent day with data (within the last 3 days)
  <s>_trend   mean of the last 3 days minus mean of days t-10..t-4
Data-quality flag per sensor (last 3 days): STUCK, DROPOUT, SPIKES or OK.
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .. import config as C

SENSOR_GROUPS = ["TEMP", "VIB", "PRES", "CURR"]


def daily_summaries(data_dir: Path) -> pd.DataFrame:
    """Per machine, sensor type and day (running readings only): count, valid count, mean, std,
    max, and n_repeat = readings identical to the previous running reading (a stuck sensor)."""
    con = duckdb.connect()
    start = C.SIM_START.isoformat()
    df = con.execute(f"""
        WITH r AS (
            SELECT t.machine_id, s.sensor_type, t.value,
                   floor((epoch(t.ts) - epoch(TIMESTAMPTZ '{start}')) / 86400)::INTEGER AS day,
                   t.value = lag(t.value) OVER (PARTITION BY t.sensor_id ORDER BY t.ts) AS repeat
            FROM read_parquet('{(data_dir / 'telemetry' / '*.parquet').as_posix()}') t
            JOIN read_csv('{(data_dir / 'sensors.csv').as_posix()}') s USING (sensor_id)
            JOIN read_csv('{(data_dir / 'machine_state_history.csv').as_posix()}') h
              ON h.machine_id = t.machine_id AND t.ts >= h.start_ts AND t.ts < h.end_ts
            WHERE h.state = 'RUNNING'
        )
        SELECT machine_id, sensor_type, day, count(*) AS n, count(value) AS n_valid,
               avg(value) AS mean, stddev_pop(value) AS std, max(value) AS mx,
               count(*) FILTER (WHERE repeat) AS n_repeat
        FROM r GROUP BY ALL
    """).df()
    con.close()
    return df


def _cube(daily: pd.DataFrame, machines: list[str], days: int, col: str) -> np.ndarray:
    """[machine, sensor group, day] array of one daily statistic (NaN where no data)."""
    out = np.full((len(machines), len(SENSOR_GROUPS), days), np.nan)
    m_idx = {m: i for i, m in enumerate(machines)}
    g_idx = {g: i for i, g in enumerate(SENSOR_GROUPS)}
    d = daily[daily["sensor_type"].isin(SENSOR_GROUPS) & (daily["day"] < days)]
    out[d["machine_id"].map(m_idx), d["sensor_type"].map(g_idx), d["day"]] = d[col].to_numpy(float)
    return out


def build_features(data_dir: Path) -> pd.DataFrame:
    scale = json.loads((data_dir / "manifest.json").read_text())["scale"]
    days, slot_hours = scale["days"], scale["interval_min"] / 60
    machines = pd.read_csv(data_dir / "machines.csv")
    sensors = pd.read_csv(data_dir / "sensors.csv")
    wo = pd.read_csv(data_dir / "maintenance_work_orders.csv", parse_dates=["end_ts"])
    fe = pd.read_csv(data_dir / "failure_events.csv", parse_dates=["failure_ts"])
    daily = daily_summaries(data_dir)

    ids = machines["machine_id"].tolist()
    mean, n, n_valid = (_cube(daily, ids, days, c) for c in ("mean", "n", "n_valid"))
    mx, n_repeat = _cube(daily, ids, days, "mx"), _cube(daily, ids, days, "n_repeat")
    running_slots = np.nan_to_num(_cube(daily, ids, days, "n")[:, SENSOR_GROUPS.index("TEMP")])
    nominal = (sensors.pivot(index="machine_id", columns="sensor_type", values="nominal_value")
               .loc[ids, SENSOR_GROUPS].to_numpy())

    # Maintenance history: completed preventive/corrective jobs (sensor swaps don't reset wear).
    service = wo[(wo["status"] == "COMPLETED") & (wo["work_order_type"] != "SENSOR_REPLACEMENT")]
    service_ends = {m: sorted(g["end_ts"]) for m, g in service.groupby("machine_id")}
    failures = {m: sorted(g["failure_ts"]) for m, g in fe.groupby("machine_id")}

    rows = []
    for i, m in enumerate(machines.itertuples()):
        install = pd.Timestamp(m.install_date, tz=C.TZ)
        for e in range(1, days + 1):  # e = days is "now": the end of the window
            t = pd.Timestamp(C.SIM_START + timedelta(days=e))
            past_service = [s for s in service_ends.get(m.machine_id, []) if s < t]
            last_service = past_service[-1] if past_service else None
            # Only days fully after the last service count as current condition.
            first_day = 0 if last_service is None else int((last_service - pd.Timestamp(C.SIM_START))
                                                           .total_seconds() // 86400) + 1
            row = {"machine_id": m.machine_id, "eval_day": e, "eval_ts": t}
            for g, group in enumerate(SENSOR_GROUPS):
                row.update(_sensor_features(group, mean[i, g], n[i, g], n_valid[i, g], n_repeat[i, g],
                                            mx[i, g], nominal[i, g], e, first_day))
            since = (t - last_service) if last_service is not None else (t - pd.Timestamp(C.SIM_START))
            row["days_since_service"] = since.total_seconds() / 86400
            row["service_history_known"] = last_service is not None
            row["wear_ratio"] = row["days_since_service"] / m.pm_interval_days
            row["run_hours_since_service"] = running_slots[i, first_day:e].sum() * slot_hours
            row["age_years"] = (t - install).days / 365.25
            row["failures_30d"] = sum(t - timedelta(days=30) <= f < t for f in failures.get(m.machine_id, []))
            rows.append(row)
    return pd.DataFrame(rows)


def _sensor_features(group, mean, n, n_valid, n_repeat, mx, nominal, e, first_day) -> dict:
    lo = max(first_day, e - C.TREND_RECENT_DAYS)
    recent = mean[lo:e]
    have = np.flatnonzero(~np.isnan(recent))
    level = recent[have[-1]] if len(have) else np.nan
    recent_mean = np.nanmean(recent) if len(have) else np.nan
    b0, b1 = max(first_day, e - C.TREND_BASELINE_DAYS[1]), max(first_day, e - C.TREND_BASELINE_DAYS[0] + 1)
    base = mean[b0:b1]
    base_mean = np.nanmean(base) if np.any(~np.isnan(base)) else np.nan
    trend = recent_mean - base_mean

    # Data quality over the last 3 days (single-sensor patterns, see validate.py).
    q = "OK"
    win = slice(lo, e)
    if not len(have):
        q = "NO_DATA"
    elif np.nansum(n[win] - n_valid[win]) > 0:
        q = "DROPOUT"
    elif np.any(n_repeat[win] >= 5):  # 5 repeats = 6 identical readings in a row; noise never does that
        q = "STUCK"
    elif np.any(mx[win] > 2.0 * mean[win]):
        q = "SPIKES"

    key = {"TEMP": "temp", "VIB": "vib", "PRES": "pres", "CURR": "curr"}[group]
    out = {f"{key}_quality": q}
    if group == "TEMP":  # temperature in degC (an offset matters, not a ratio)
        out["temp_excess_c"] = level - nominal
        out["temp_trend_c"] = trend
    elif group == "PRES":  # pressure failures make it DROP
        out["pres_drop"] = 1 - level / nominal
        out["pres_trend"] = -trend / nominal
    else:
        out[f"{key}_excess"] = level / nominal - 1
        out[f"{key}_trend"] = trend / nominal
    return out
