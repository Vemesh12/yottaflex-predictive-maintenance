"""File output helpers. Output is byte-for-byte deterministic so checksums prove reproducibility."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


def _iso(series: pd.Series) -> pd.Series:
    # 2026-07-01T06:00:00+0530 -> 2026-07-01T06:00:00+05:30 (ISO 8601)
    s = series.dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    return s.str[:-2] + ":" + s.str[-2:]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    out = df.copy()
    for col in out.columns:
        if isinstance(out[col].dtype, pd.DatetimeTZDtype):
            out[col] = _iso(out[col])
    out.to_csv(path, index=False, lineterminator="\n")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(obj, path: Path) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")
