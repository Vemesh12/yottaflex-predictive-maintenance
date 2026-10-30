"""Seeded random streams.

Each part of the generator gets its own stream derived from (seed, name), so adding a new
stream or generating machines in a different order never changes the numbers of another stream.
"""
from __future__ import annotations

import zlib

import numpy as np


def stream(seed: int, *keys: str | int) -> np.random.Generator:
    entropy = [seed] + [zlib.crc32(str(k).encode()) for k in keys]
    return np.random.default_rng(entropy)
