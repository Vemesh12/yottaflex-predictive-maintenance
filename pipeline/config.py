"""Generator configuration: scale presets, domain constants and documented assumptions.

All numbers here are illustrative synthetic values, not industrial safety limits.
They are documented in docs/data-dictionary.md and docs/assumptions.md.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from zoneinfo import ZoneInfo

DEFAULT_SEED = 20261022
GENERATOR_VERSION = "0.1.0"

# All plants are in India; every timestamp is stored timezone-aware in IST (+05:30).
TZ = ZoneInfo("Asia/Kolkata")
# Simulation starts at the first shift (A, 06:00) so every shift record lies fully inside the window.
SIM_START = datetime(2026, 7, 1, 6, 0, tzinfo=TZ)


@dataclass(frozen=True)
class Scale:
    name: str
    plants: int
    lines_per_plant: int
    machines: int
    days: int
    interval_min: int
    technicians_per_plant: int

    @property
    def slots(self) -> int:
        return self.days * 24 * 60 // self.interval_min

    @property
    def lines(self) -> int:
        return self.plants * self.lines_per_plant


SCALES = {
    # Starter: same generator, small enough to run in a couple of seconds.
    "starter": Scale("starter", plants=1, lines_per_plant=2, machines=10, days=14,
                     interval_min=30, technicians_per_plant=4),
    # Full: 3 plants, 12 lines, 100 machines, 500 sensors, 90 days @ 30 min = 2,160,000 readings.
    "full": Scale("full", plants=3, lines_per_plant=4, machines=100, days=90,
                  interval_min=30, technicians_per_plant=6),
}


def get_scale(name: str, **overrides) -> Scale:
    scale = SCALES[name]
    overrides = {k: v for k, v in overrides.items() if v is not None}
    return replace(scale, **overrides) if overrides else scale


PLANTS = [
    ("Hyderabad Plant", "Hyderabad", "Telangana"),
    ("Pune Plant", "Pune", "Maharashtra"),
    ("Chennai Plant", "Chennai", "Tamil Nadu"),
]

# ---------------------------------------------------------------------------
# Machines and sensors
# ---------------------------------------------------------------------------
MACHINE_TYPES = ["PUMP", "COMPRESSOR", "HYDRAULIC_PRESS", "CNC_SPINDLE"]
MACHINE_TYPE_WEIGHTS = [0.35, 0.25, 0.20, 0.20]
CRITICALITY = ["A", "B", "C"]                 # A = line stops if machine stops
CRITICALITY_WEIGHTS = [0.25, 0.45, 0.30]
PM_INTERVAL_DAYS = {"A": 30, "B": 45, "C": 60}  # preventive-maintenance cadence by criticality

MANUFACTURERS = {
    "PUMP": ["Kirloskar", "Grundfos", "KSB"],
    "COMPRESSOR": ["Atlas Copco", "Ingersoll Rand", "ELGi"],
    "HYDRAULIC_PRESS": ["Bosch Rexroth", "Parker", "Yuken"],
    "CNC_SPINDLE": ["Fanuc", "Siemens", "Haas"],
}

# Every machine carries the same five sensor types (5 x 100 machines = 500 sensors).
SENSOR_TYPES = ["TEMP", "VIB", "PRES", "RPM", "CURR"]
SENSOR_UNITS = {"TEMP": "degC", "VIB": "mm/s", "PRES": "bar", "RPM": "rpm", "CURR": "A"}

# Nominal RUNNING baseline per machine type at nominal load (0.85).
BASELINE = {
    "PUMP":            {"TEMP": 58.0, "VIB": 2.8, "PRES": 6.0,   "RPM": 1480.0, "CURR": 42.0},
    "COMPRESSOR":      {"TEMP": 78.0, "VIB": 3.5, "PRES": 8.5,   "RPM": 2950.0, "CURR": 85.0},
    "HYDRAULIC_PRESS": {"TEMP": 50.0, "VIB": 2.2, "PRES": 160.0, "RPM": 1450.0, "CURR": 55.0},
    "CNC_SPINDLE":     {"TEMP": 45.0, "VIB": 1.6, "PRES": 4.0,   "RPM": 8000.0, "CURR": 25.0},
}

# Instrument measurement range = what the sensor can physically report.
# Anything outside this range is an "impossible" reading (Day 2 edge case).
def sensor_range(sensor_type: str, nominal: float) -> tuple[float, float]:
    if sensor_type == "TEMP":
        return -40.0, 200.0
    if sensor_type == "VIB":
        return 0.0, 50.0
    if sensor_type == "PRES":
        return 0.0, round(nominal * 2.5, 1)
    if sensor_type == "RPM":
        return 0.0, round(nominal * 1.5, 0)
    return 0.0, round(nominal * 3.0, 1)  # CURR


# Normal RUNNING envelope as +/- fraction of nominal (outside it = warning, not impossible).
NORMAL_BAND = {"TEMP": 0.15, "VIB": 0.40, "PRES": 0.10, "RPM": 0.03, "CURR": 0.25}
# Gaussian measurement noise as a fraction of nominal.
NOISE = {"TEMP": 0.008, "VIB": 0.05, "PRES": 0.012, "RPM": 0.003, "CURR": 0.02}

# ---------------------------------------------------------------------------
# Operating context
# ---------------------------------------------------------------------------
MACHINE_STATES = ["RUNNING", "IDLE", "SHUTDOWN", "MAINTENANCE", "FAILED"]  # FAILED used from Day 2
STATE_CODE = {s: i for i, s in enumerate(MACHINE_STATES)}

# Shifts in plant local time. C crosses midnight.
SHIFTS = [("A", 6, 8), ("B", 14, 8), ("C", 22, 8)]  # (code, start hour, hours)
# Weekday (Mon=0): which shifts produce. Saturday night and Sunday are planned off.
PRODUCTION_SHIFTS = {0: "ABC", 1: "ABC", 2: "ABC", 3: "ABC", 4: "ABC", 5: "AB", 6: ""}

# Micro-stops during production shifts (Markov chain per 30-min slot).
P_RUN_TO_IDLE = 0.02
P_IDLE_TO_RUN = 0.50

AMBIENT_MEAN_C = 28.0
AMBIENT_DAILY_AMP_C = 4.0
NOMINAL_LOAD = 0.85
THERMAL_ALPHA = 0.4  # fraction of the gap to the target temperature closed per slot

# ---------------------------------------------------------------------------
# People and parts
# ---------------------------------------------------------------------------
SPECIALIZATIONS = ["MECHANICAL", "ELECTRICAL", "INSTRUMENTATION", "HYDRAULICS"]
TECH_FIRST_NAMES = ["Arjun", "Priya", "Ravi", "Meena", "Kiran", "Suresh", "Anita", "Vikram",
                    "Lakshmi", "Rahul", "Divya", "Manoj", "Sneha", "Ajay", "Kavya", "Naveen",
                    "Pooja", "Sanjay"]
HOURLY_RATE_INR = {1: 450, 2: 650, 3: 900}

# (name, category, compatible machine type or ALL, unit cost INR, lead time days, failure mode addressed)
PARTS = [
    ("Pump bearing set", "BEARING", "PUMP", 8500, 3, "BEARING_WEAR"),
    ("Mechanical seal", "SEAL", "PUMP", 12000, 5, "PRESSURE_LOSS"),
    ("Impeller", "IMPELLER", "PUMP", 26000, 10, "PRESSURE_LOSS"),
    ("Compressor bearing set", "BEARING", "COMPRESSOR", 15500, 4, "BEARING_WEAR"),
    ("Compressor valve plate", "VALVE", "COMPRESSOR", 18000, 7, "PRESSURE_LOSS"),
    ("Oil cooler", "COOLING", "COMPRESSOR", 32000, 12, "OVERHEATING"),
    ("Hydraulic pump cartridge", "PUMP_CARTRIDGE", "HYDRAULIC_PRESS", 45000, 14, "PRESSURE_LOSS"),
    ("Hydraulic seal kit", "SEAL", "HYDRAULIC_PRESS", 9500, 4, "PRESSURE_LOSS"),
    ("Hydraulic oil filter", "FILTER", "HYDRAULIC_PRESS", 2800, 2, "OVERHEATING"),
    ("Spindle bearing set", "BEARING", "CNC_SPINDLE", 38000, 10, "BEARING_WEAR"),
    ("Spindle coolant pump", "COOLING", "CNC_SPINDLE", 14500, 6, "OVERHEATING"),
    ("Drive belt", "BELT", "ALL", 1800, 1, "IMBALANCE"),
    ("Coupling insert", "COUPLING", "ALL", 2400, 2, "IMBALANCE"),
    ("Motor winding rewind", "MOTOR", "ALL", 22000, 7, "ELECTRICAL_FAULT"),
    ("Motor contactor", "ELECTRICAL", "ALL", 4200, 2, "ELECTRICAL_FAULT"),
    ("Cooling fan", "COOLING", "ALL", 3600, 2, "OVERHEATING"),
    ("Temperature sensor (RTD)", "SENSOR", "ALL", 3200, 2, "SENSOR_FAULT"),
    ("Vibration sensor (accelerometer)", "SENSOR", "ALL", 11500, 4, "SENSOR_FAULT"),
    ("Pressure transmitter", "SENSOR", "ALL", 7800, 3, "SENSOR_FAULT"),
    ("Lubricant (5 L)", "CONSUMABLE", "ALL", 1500, 1, "PREVENTIVE"),
]

FAILURE_MODES = ["BEARING_WEAR", "OVERHEATING", "PRESSURE_LOSS", "IMBALANCE", "ELECTRICAL_FAULT"]
