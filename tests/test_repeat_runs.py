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


def test_summarize_caught_and_rates():
    runs=[
        {'invalid':False,'caught_yes_no':True,'tests_generated':4,'tests_catching':2,'test_content_hash':'h1'},
        {'invalid':False,'caught_yes_no':False,'tests_generated':4,'tests_catching':1,'test_content_hash':'h2'},
    ]
    s=rs.summarize(runs)
    assert s['caught']==1 and s['catch_rate']==0.5

def test_summarize_wilson_bounds():
    runs=[{'invalid':False,'caught_yes_no':True} for _ in range(6)]+[{'invalid':False,'caught_yes_no':False} for _ in range(4)]
    s=rs.summarize(runs)
    assert abs(s['wilson_lo']-0.3127)<0.01 and abs(s['wilson_hi']-0.8318)<0.01

def test_summarize_mean_fraction_and_distinct():
    runs=[
        {'invalid':False,'caught_yes_no':True,'tests_generated':10,'tests_catching':6,'test_content_hash':'h1'},
        {'invalid':False,'caught_yes_no':True,'tests_generated':4,'tests_catching':2,'test_content_hash':'h1'},
        {'invalid':False,'caught_yes_no':False,'tests_generated':2,'tests_catching':0,'test_content_hash':'h2'},
    ]
    s=rs.summarize(runs)
    assert abs(s['mean_fraction_catching']-((0.6+0.5+0.0)/3))<1e-9 and s['distinct_test_files']==2

def test_summarize_zero_valid_runs():
    runs=[{'invalid':True},{'invalid':True}]
    s=rs.summarize(runs)
    assert s['valid']==0 and s['excluded']==2 and s['caught']==0 and s['catch_rate']==0.0 and s['wilson_lo']==0.0 and s['wilson_hi']==1.0 and s['mean_fraction_catching']==0.0 and s['distinct_test_files']==0

def test_wilson_6_of_10_approx():
    lo,hi=rs.wilson_interval(6,10)
    assert abs(lo-0.3127)<0.01 and abs(hi-0.8318)<0.01

def test_wilson_0_of_10_approx():
    lo,hi=rs.wilson_interval(0,10)
    assert abs(lo-0.0)<0.01 and abs(hi-0.2775)<0.01

def test_wilson_10_of_10_approx():
    lo,hi=rs.wilson_interval(10,10)
    assert abs(lo-0.7225)<0.01 and abs(hi-1.0)<0.01

def test_normalize_treats_crlf_lf_and_spaces_same():
    s1='def f():\n  return 1\n'
    s2='def f():\r\n  return 1  \n\n'
    assert rs.normalize_content(s1)==rs.normalize_content(s2)

def test_content_hash_differs_for_different_code():
    assert rs.content_hash('a')!=rs.content_hash('b')

def test_summarize_excludes_invalid_runs():
    runs=[{'invalid':True},{'invalid':False},{'invalid':False}]
    s=rs.summarize(runs)
    assert s['valid']==2 and s['runs']==3 and s['excluded']==1

def test_summarize_reports_excluded_count():
    runs=[{'invalid':True},{'invalid':False}]
    s=rs.summarize(runs)
    assert s['excluded']==1 and s['valid']==1
