"""Tests for the pipeline's own --no-fallback switch.

A run that dies half way still has most of a report in it, and that report looks
exactly like a finished one. classifier_eval already refuses to produce a score
under those conditions. These tests pin the same promise to the pipeline:

- with --no-fallback, a daily limit stops the whole run and says so, printing how
  many calls got through and that no results should be trusted;
- an answer that came from the fallback model is named loudly, once;
- with no flag, nothing changes, so today's behaviour is still the default.

Nothing here touches the internet: the AI is a fake that raises the same kind of
error the real providers do.
"""

import sys

import pytest

from prsentinel import llm_client
from prsentinel import pipeline as pl

from test_pipeline import (fake_change, one_change,  # noqa: F401
                           workspace, write_modules)

GENERATED_TEST = """
    from target import get_recent_scores

    def test_one():
        assert get_recent_scores([1, 2, 3], 2) == [2, 3]
"""


@pytest.fixture(autouse=True)
def fallback_back_on():
    """Every test starts and ends with fallback allowed and no warning shown."""
    llm_client.ALLOW_FALLBACK = True
    llm_client.CALLS_MADE = 0
    llm_client.LAST_PROVIDER = ""
    pl.reset_gemini_warning()
    yield
    llm_client.ALLOW_FALLBACK = True
    llm_client.CALLS_MADE = 0
    llm_client.LAST_PROVIDER = ""
    pl.reset_gemini_warning()


def run_main(monkeypatch, before, after, extra=()):
    """Run main() with the pipeline itself replaced by a fake.

    Returns the exit code and exactly what the flag was set to when the pipeline
    was about to start, which is the only place the decision matters.
    """
    seen = {}

    def fake_run_pipeline(*args, **kwargs):
        seen["allow_fallback"] = llm_client.ALLOW_FALLBACK
        return {}

    monkeypatch.setattr(pl, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(sys, "argv", ["pipeline", before, after, *extra])

    code = pl.main()
    return code, seen


def break_generation_on_a_daily_limit(monkeypatch):
    """Make the test writer report that the AI is out for the day."""
    def out_for_the_day(change):
        raise llm_client.DailyLimitReached(
            "Groq has no allowance left for today.")

    monkeypatch.setattr(pl.tg, "generate_tests", out_for_the_day)


# ---------------------------------------------------------------------------
# The flag, and what it leaves alone
# ---------------------------------------------------------------------------

def test_fallback_is_allowed_when_the_flag_is_not_given(monkeypatch, workspace):
    """Today's behaviour must be what happens with no options at all."""
    before, after = write_modules(workspace)

    code, seen = run_main(monkeypatch, before, after)

    assert code == 0
    assert seen["allow_fallback"] is True


def test_the_flag_turns_the_fallback_off(monkeypatch, workspace):
    before, after = write_modules(workspace)

    code, seen = run_main(monkeypatch, before, after, extra=["--no-fallback"])

    assert code == 0
    assert seen["allow_fallback"] is False


# ---------------------------------------------------------------------------
# A daily limit stops the whole run
# ---------------------------------------------------------------------------

def test_a_daily_limit_stops_the_run_at_once(monkeypatch, workspace, capsys):
    before, after = write_modules(workspace)
    one_change(monkeypatch, fake_change("get_recent_scores"))
    break_generation_on_a_daily_limit(monkeypatch)
    llm_client.CALLS_MADE = 4

    with pytest.raises(pl.DailyLimitStop):
        pl.run_pipeline(before, after)

    printed = capsys.readouterr().out
    assert "THE RUN STOPPED EARLY" in printed
    assert "out for the day" in printed.lower()


def test_a_stopped_run_says_how_many_calls_got_through(monkeypatch, workspace,
                                                       capsys):
    before, after = write_modules(workspace)
    one_change(monkeypatch, fake_change("get_recent_scores"))
    break_generation_on_a_daily_limit(monkeypatch)
    llm_client.CALLS_MADE = 4

    with pytest.raises(pl.DailyLimitStop):
        pl.run_pipeline(before, after)

    printed = capsys.readouterr().out
    assert "Model calls completed before the stop" in printed
    assert "4" in printed


def test_a_stopped_run_warns_against_trusting_any_result(monkeypatch, workspace,
                                                         capsys):
    """A half-finished report looks exactly like a finished one."""
    before, after = write_modules(workspace)
    one_change(monkeypatch, fake_change("get_recent_scores"))
    break_generation_on_a_daily_limit(monkeypatch)

    with pytest.raises(pl.DailyLimitStop):
        pl.run_pipeline(before, after)

    assert "No results should be trusted" in capsys.readouterr().out


def test_a_stopped_run_saves_no_report(monkeypatch, workspace, capsys):
    """Nothing is saved, so no half a report can be read as a whole one."""
    before, after = write_modules(workspace)
    one_change(monkeypatch, fake_change("get_recent_scores"))
    break_generation_on_a_daily_limit(monkeypatch)

    with pytest.raises(pl.DailyLimitStop):
        pl.run_pipeline(before, after)

    assert not (workspace / "reports").exists()


def test_a_daily_limit_is_not_treated_as_one_failed_function(monkeypatch,
                                                             workspace):
    """A function that fails must not swallow the end of the whole run."""
    before, after = write_modules(workspace)
    one_change(monkeypatch, fake_change("get_recent_scores"))
    break_generation_on_a_daily_limit(monkeypatch)

    with pytest.raises(llm_client.DailyLimitReached):
        pl.generate_test_files(before, after, "my_example")


# ---------------------------------------------------------------------------
# Naming the fallback model
# ---------------------------------------------------------------------------

def test_the_gemini_warning_is_said_once(capsys):
    """Said once, and loudly, so it cannot be scrolled past unnoticed."""
    llm_client.LAST_PROVIDER = "Gemini"

    pl.warn_if_gemini()
    pl.warn_if_gemini()

    assert capsys.readouterr().out.count("AN ANSWER CAME FROM GEMINI") == 1


def test_the_gemini_warning_is_not_said_for_a_groq_answer(capsys):
    llm_client.LAST_PROVIDER = "Groq"

    pl.warn_if_gemini()

    assert capsys.readouterr().out == ""


def test_an_answer_from_gemini_is_announced_during_generation(monkeypatch,
                                                              workspace, capsys):
    """The warning must appear at the point the fallback answer arrives."""
    before, after = write_modules(workspace)
    one_change(monkeypatch, fake_change("get_recent_scores"))

    def gemini_generate_tests(change):
        llm_client.LAST_PROVIDER = "Gemini"
        return GENERATED_TEST

    monkeypatch.setattr(pl.tg, "generate_tests", gemini_generate_tests)

    pl.generate_test_files(before, after, "my_example")

    assert "AN ANSWER CAME FROM GEMINI" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The exit code
# ---------------------------------------------------------------------------

def test_a_stopped_run_has_its_own_exit_code(monkeypatch, workspace):
    """A number, not zero. Zero means the report is complete and sound."""
    before, after = write_modules(workspace)

    def stop(*args, **kwargs):
        raise pl.DailyLimitStop("out for the day")

    monkeypatch.setattr(pl, "run_pipeline", stop)
    monkeypatch.setattr(sys, "argv", ["pipeline", before, after])

    assert pl.main() == pl.EXIT_DAILY_LIMIT
    assert pl.EXIT_DAILY_LIMIT != 0


def test_an_ordinary_break_still_has_the_broken_exit_code(monkeypatch,
                                                          workspace):
    """The stop must not have swallowed the old behaviour for real errors."""
    before, after = write_modules(workspace)

    def broken(*args, **kwargs):
        raise RuntimeError("the pipeline broke")

    monkeypatch.setattr(pl, "run_pipeline", broken)
    monkeypatch.setattr(sys, "argv", ["pipeline", before, after])

    assert pl.main() == 1
