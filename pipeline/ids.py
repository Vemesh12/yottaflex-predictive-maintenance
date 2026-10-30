"""Deterministic ID builders. IDs embed their parent ID, as the problem statement specifies.

PLT-001 -> LINE-PLT-001-001 -> MCH-LINE-PLT-001-001-001 -> SNS-MCH-LINE-PLT-001-001-001-TEMP-01
"""
from __future__ import annotations

import re
from datetime import datetime

TS_ID_FORMAT = "%Y%m%dT%H%M%S"  # plant local time (IST), compact form used inside telemetry IDs


def plant_id(n: int) -> str:
    return f"PLT-{n:03d}"


def line_id(plant: str, n: int) -> str:
    return f"LINE-{plant}-{n:03d}"


def machine_id(line: str, n: int) -> str:
    return f"MCH-{line}-{n:03d}"


def sensor_id(machine: str, sensor_type: str, n: int = 1) -> str:
    return f"SNS-{machine}-{sensor_type}-{n:02d}"


def telemetry_id(sensor: str, ts: datetime) -> str:
    return f"TEL-{sensor}-{ts.strftime(TS_ID_FORMAT)}"


def work_order_id(n: int, year: int = 2026) -> str:
    return f"WO-{year}-{n:06d}"


def shift_id(plant: str, shift_date: str, code: str) -> str:
    return f"SHF-{plant}-{shift_date.replace('-', '')}-{code}"


def technician_id(plant: str, n: int) -> str:
    return f"TECH-{plant}-{n:03d}"


def part_id(n: int) -> str:
    return f"PART-{n:04d}"


def state_event_id(n: int) -> str:
    return f"MSE-{n:07d}"


PATTERNS = {
    "plant_id": re.compile(r"^PLT-\d{3}$"),
    "line_id": re.compile(r"^LINE-PLT-\d{3}-\d{3}$"),
    "machine_id": re.compile(r"^MCH-LINE-PLT-\d{3}-\d{3}-\d{3}$"),
    "sensor_id": re.compile(r"^SNS-MCH-LINE-PLT-\d{3}-\d{3}-\d{3}-(TEMP|VIB|PRES|RPM|CURR)-\d{2}$"),
    "telemetry_id": re.compile(r"^TEL-SNS-MCH-LINE-PLT-\d{3}-\d{3}-\d{3}-[A-Z]+-\d{2}-\d{8}T\d{6}$"),
    "work_order_id": re.compile(r"^WO-\d{4}-\d{6}$"),
    "shift_id": re.compile(r"^SHF-PLT-\d{3}-\d{8}-[ABC]$"),
    "technician_id": re.compile(r"^TECH-PLT-\d{3}-\d{3}$"),
    "part_id": re.compile(r"^PART-\d{4}$"),
    "state_event_id": re.compile(r"^MSE-\d{7}$"),
}
