"""Load generated CSV/Parquet files into a DuckDB database that enforces the schema's PK/FK/CHECK
constraints. If any generated row breaks a rule, the load fails loudly instead of hiding it."""
from __future__ import annotations

import time
from pathlib import Path

import duckdb

SCHEMA = Path(__file__).parent / "sql" / "schema.sql"

# Load order = parents before children.
LOAD_ORDER = [
    ("plant", "plants.csv"),
    ("production_line", "production_lines.csv"),
    ("machine", "machines.csv"),
    ("sensor", "sensors.csv"),
    ("operating_shift", "operating_shifts.csv"),
    ("technician", "technicians.csv"),
    ("part", "parts.csv"),
    ("machine_state_history", "machine_state_history.csv"),
]


def load(data_dir: Path, log=print) -> Path:
    t0 = time.perf_counter()
    db_path = data_dir / "plant.duckdb"
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute(SCHEMA.read_text(encoding="utf-8"))
        for table, file in LOAD_ORDER:
            con.execute(f"INSERT INTO {table} BY NAME SELECT * FROM read_csv(?, header = true)",
                        [str(data_dir / file)])
        con.execute("INSERT INTO telemetry_event BY NAME SELECT * FROM read_parquet(?)",
                    [str(data_dir / "telemetry" / "*.parquet")])
        for table, _ in LOAD_ORDER + [("telemetry_event", None)]:
            n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            log(f"{table:<24}{n:>12,}")
    finally:
        con.close()
    log(f"loaded in {time.perf_counter() - t0:.1f}s -> {db_path}")
    return db_path
