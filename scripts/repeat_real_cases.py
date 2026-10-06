#!/usr/bin/env python
"""Repeated runs on the three real cases for two arms.

Arm A: PRSentinel via pl.run_pipeline with mutation=False, fallback off,
unique name rep_<case>_A_<nn>. We monkeypatch test_generator.ask_llm and
llm_client.ask_llm with a recording wrapper per run (both arms), restoring
originals in finally. Wrapper records temperature actually received and
forwards unchanged. Keep temperature as config.GENERATION_TEMPERATURE (0.0)
per instructions.

Arm B: uses only pure helpers from scripts.baseline_single_prompt (frozen
prompt, prompt builder, code extraction, runner scoring). Writes to temp dir
per run, never to baselines_single_prompt/.
"""
import argparse
import json
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from prsentinel import config
from prsentinel import llm_client
from prsentinel import pipeline as pl
from prsentinel import test_generator as tg
from prsentinel import test_runner as tr

import scripts.baseline_single_prompt as bsp

PROJECT = Path(__file__).resolve().parents[1]
REAL_CASES = ("real_youtube-dl_bug3", "real_youtube-dl_bug43", "real_PySnooper_bug3")
RESULTS_BASE = PROJECT / "results" / "repeats"
REPORTS_DIR = PROJECT / "reports"
REQUIRED_KEYS = [
    "case", "arm", "run_index", "timestamp", "provider", "model",
    "temperature", "gemini_answers", "fallback_used", "tests_generated",
    "tests_catching", "tests_wrong_on_before", "tests_odd", "caught_yes_no",
    "invalid", "invalid_reason", "exit_code", "error", "test_content_hash",
]