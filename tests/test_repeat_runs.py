import json
import os
import tempfile
from pathlib import Path
import pytest

from scripts import repeat_real_cases as rrc
from scripts import repeat_summary as rs


def test_resume_skips_valid_file(tmp_path, monkeypatch):
    case = "real_youtube-dl_bug3"
    arm = "prsentinel"
    out_dir = tmp_path / "results" / "repeats" / case / arm
    out_dir.mkdir(parents=True)
    f = out_dir / "run_00.json"
    data = {
        "case": case,
        "arm": arm,
        "run_index": 0,
        "timestamp": "2026-01-01T00:00:00Z",
        "provider": "Groq",
        "model": "test",
        "temperature": 0.0,
        "gemini_answers": 0,
        "fallback_used": False,
        "tests_generated": 1,
        "tests_catching": 1,
        "tests_wrong_on_before": 0,
        "tests_odd": 0,
        "caught_yes_no": True,
        "invalid": False,
        "invalid_reason": "",
        "exit_code": None,
        "error": None,
        "test_content_hash": "abc",
    }
    f.write_text(json.dumps(data), encoding="utf-8")
    assert rrc.should_skip_run(f) is True


def test_unreadable_file_stops(tmp_path):
    case = "real_youtube-dl_bug3"
    arm = "prsentinel"
    out_dir = tmp_path / "results" / "repeats" / case / arm
    out_dir.mkdir(parents=True)
    f = out_dir / "run_00.json"
    f.write_text("{broken", encoding="utf-8")
    with pytest.raises(RuntimeError):
        rrc.should_skip_run(f)


def test_atomic_write(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    f = d / "run_01.json"
    rrc.atomic_write_json(f, {"a": 1})
    assert f.exists()
    assert not (d / "run_01.json.tmp").exists()
    with open(f) as fh:
        assert json.load(fh)["a"] == 1
