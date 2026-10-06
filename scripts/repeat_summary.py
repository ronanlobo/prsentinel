#!/usr/bin/env python
"""Offline summary for repeated runs."""
import json
import math
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT = Path(__file__).resolve().parents[1]
RESULTS_BASE = PROJECT / "results" / "repeats"


def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n if n > 0 else 0
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(max(0, (p * (1 - p) + z * z / (4 * n)) / n))
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    if lo < 0.0:
        lo = 0.0
    if hi > 1.0:
        hi = 1.0
    return lo, hi