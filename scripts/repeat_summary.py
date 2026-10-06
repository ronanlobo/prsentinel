#!/usr/bin/env python
"""Offline summary for repeated runs.

Reads only results/repeats/**/*.json. Computes per case/arm: N, valid
(invalid==False), runs caught, catch rate among valid with Wilson 95% CI
(inline), mean fraction of tests catching among valid, distinct test files
by normalized content (strip trailing spaces, collapse blank lines,
normalize line endings) count of distinct hashes. If 10/10 identical, state
plainly. Report invalid exclusions.

No network, no live AI calls.
"""
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List

PROJECT = Path(__file__).resolve().parents[1]
RESULTS_BASE = PROJECT / "results" / "repeats"