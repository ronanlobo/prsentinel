#!/usr/bin/env python
"""Repeated runs helpers and script structure (skeleton for tests)."""
import json
import os
from pathlib import Path
from typing import Any, Dict

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


def should_skip_run(path: Path) -> bool:
    """Return True if run exists and is valid; raise RuntimeError if unreadable."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise RuntimeError("unreadable run file")
    for k in REQUIRED_KEYS:
        if k not in data:
            raise RuntimeError("missing required key")
    return True


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
