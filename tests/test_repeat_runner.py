import json
import pytest
from scripts import repeat_real_cases as rrc

ROW = lambda label, name="t": {"name": name, "label": label}


def rec(provider="Groq", temps=(0.0,), rows=None, code="x = 1"):
    rows = [ROW("CATCHES_CHANGE", "a"), ROW("NO_SIGNAL", "b")] if rows is None else rows
    return rrc.build_record("c", "baseline", 1, code, rows, provider,
                            list(temps), 0.0, "WHOLE")


def test_valid_groq_run_counts_labels():
    r = rec()
    assert r["invalid"] is False and r["caught_yes_no"] is True
    assert r["tests_generated"] == 2 and r["tests_catching"] == 1


def test_gemini_run_is_invalid():
    r = rec(provider="Gemini")
    assert r["invalid"] and r["gemini_answers"] == 1


def test_temperature_mismatch_is_invalid():
    assert rec(temps=(0.7,))["invalid"]


def test_no_model_call_is_invalid():
    assert rec(temps=())["invalid"]


def test_whole_file_row_is_not_counted_as_a_test():
    r = rec(rows=[ROW("TEST_WRONG_ON_BEFORE", "WHOLE")])
    assert r["tests_generated"] == 0 and r["caught_yes_no"] is False


def test_wrapper_records_and_forwards_unchanged():
    seen = []
    w = rrc.RecordingAsk(lambda p, *a, **k: seen.append((p, a, k)) or "ok")
    assert w("hi", 0.0) == "ok"
    assert w.temperatures == [0.0] and seen == [("hi", (0.0,), {})]


def test_originals_restored_even_after_exception():
    class M:  # stand-ins for the two modules
        pass
    llm, tg = M(), M()
    llm.ask_llm = lambda p, *a: "llm"
    tg.ask_llm = lambda p, *a: "tg"
    o1, o2 = llm.ask_llm, tg.ask_llm
    with pytest.raises(ValueError):
        with rrc.recording(llm, tg):
            assert llm.ask_llm is not o1
            raise ValueError("boom")
    assert llm.ask_llm is o1 and tg.ask_llm is o2


def fake_record(case, arm, n):
    return rec()


def test_run_all_writes_files_and_resume_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(rrc, "ARMS", ("baseline",))
    calls = []
    def do_run(c, a, n):
        calls.append((c, a, n))
        r = fake_record(c, a, n)
        r.update(case=c, arm=a, run_index=n)
        return r
    assert rrc.run_all(["c1"], 2, do_run, base=tmp_path) == 0
    assert len(calls) == 2
    assert rrc.run_all(["c1"], 2, do_run, base=tmp_path) == 0
    assert len(calls) == 2  # nothing redone


def test_unreadable_file_stops_and_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(rrc, "ARMS", ("baseline",))
    f = tmp_path / "c1" / "baseline" / "run_01.json"
    f.parent.mkdir(parents=True)
    f.write_text("{broken")
    assert rrc.run_all(["c1"], 1, fake_record, base=tmp_path) == rrc.EXIT_STOPPED
    assert f.read_text() == "{broken"


def test_daily_limit_exits_6_and_keeps_finished_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(rrc, "ARMS", ("baseline",))
    class Limit(Exception):
        pass
    def do_run(c, a, n):
        if n == 2:
            raise Limit()
        r = fake_record(c, a, n)
        r.update(case=c, arm=a, run_index=n)
        return r
    code = rrc.run_all(["c1"], 3, do_run, base=tmp_path, limit_exc=Limit)
    assert code == rrc.EXIT_DAILY_LIMIT
    assert (tmp_path / "c1" / "baseline" / "run_01.json").exists()
    assert not (tmp_path / "c1" / "baseline" / "run_02.json").exists()