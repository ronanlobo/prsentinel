"""Tests for the guards on the kept-back run.

The kept-back cases are the one set the prompt was never tuned against. They are
worth nothing if something can quietly spoil the run and still print a number,
so the three ways that could happen are each stopped here:

- a Gemini answer appearing in a run that was meant to be Groq only,
- a provider running out for the day part way through,
- the run starting at all while the tuning scores are still unfilled.

A kept-back score is also the number most likely to be quoted in a write-up, so
the risk is not only a wrong score, it is a wrong score that nobody realises is
wrong. Every guard below therefore withholds the score entirely rather than
printing it with a warning attached. A number with a caveat next to it still gets
copied on its own.

Nothing here runs a real test, calls a real model, or touches a real case folder.
The AI is a fake and the cases are pretend, so these tests are quick, offline and
free. They also never run the kept-back command for real.
"""

import json
import sys
from pathlib import Path

import pytest

from prsentinel import classifier as cl
from prsentinel import classifier_eval as ce
from prsentinel import heldback_eval as he
from prsentinel import llm_client as lc


# A provider's real daily-limit message, word for word. If either provider ever
# words it differently, this is the one to update.
GROQ_DAILY = (
    "Error code: 429 - {'error': {'message': \"Rate limit reached for model "
    "'openai/gpt-oss-120b' in organization 'org_01m3rhn38xe5rabevaavha2b4m' "
    "service tier 'on_demand' on tokens per day (TPD): Limit 200000, Used "
    "199488, Requested 736. Please try again in 1m36.767999999s.\"}}"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def reply(label, reason="because"):
    """Build the JSON reply the AI would give."""
    return json.dumps({"label": label, "confidence": "high", "reason": reason})


def answer_from(provider, label="REAL_BUG"):
    """Build a fake ask_llm that reports which provider answered.

    This mirrors what llm_client.ask_llm does on the way out: set the name, hand
    back the text. Nothing else is recorded, which is the point.
    """
    def fake_ask(prompt):
        lc.CALLS_MADE += 1
        lc.LAST_PROVIDER = provider
        return reply(label)

    return fake_ask


def groq_then_gemini(first="Gemini", label="REAL_BUG"):
    """Build a fake AI where the named provider answers the first call only.

    The counter is this fake's own rather than lc.CALLS_MADE, because the real
    ask_llm is what increments that, and a fake that replaces it has to count for
    itself to behave like the thing it stands in for.
    """
    counter = {"calls": 0}

    def fake_ask(prompt):
        counter["calls"] += 1
        lc.CALLS_MADE += 1
        if counter["calls"] == 1:
            lc.LAST_PROVIDER = first
        else:
            lc.LAST_PROVIDER = "Groq"
        return reply(label)

    return fake_ask


def stop_after(counter, calls_allowed):
    """Build a fake AI that works, then reports the provider is out for the day.

    The count is bumped the way the real client bumps it, before the call is
    tried, so the number printed at the stop means the same thing here as it
    would in a real run.
    """
    def fake_ask(prompt):
        counter["calls"] += 1
        lc.CALLS_MADE += 1
        if counter["calls"] > calls_allowed:
            raise lc.DailyLimitReached(
                "Groq has no allowance left for today. tokens per day (TPD)")
        lc.LAST_PROVIDER = "Groq"
        return reply("REAL_BUG")

    return fake_ask


def measured_log(tmp_path, monkeypatch, text="# Prompt log\n\n- 13/14 (93%)\n"):
    """Point the refusal check at a log that says the scores are filled in."""
    log = tmp_path / "PROMPT_LOG.md"
    log.write_text(text, encoding="utf-8")
    monkeypatch.setattr(he, "PROMPT_LOG", log)
    return log


def unmeasured_log(tmp_path, monkeypatch, phrase):
    """Point the refusal check at a log that still carries the given phrase."""
    log = tmp_path / "PROMPT_LOG.md"
    log.write_text(f"# Prompt log\n\n- Tuning scores: {phrase}\n", encoding="utf-8")
    monkeypatch.setattr(he, "PROMPT_LOG", log)
    return log


def pretend_cases(monkeypatch, count=3, expected="REAL_BUG"):
    """Point the eval at a fixed number of pretend cases and a pretend log."""
    folders = [Path(f"keptback_number_{number}") for number in range(count)]
    monkeypatch.setattr(he, "case_folders", lambda: folders)
    monkeypatch.setattr(he, "read_expected",
                        lambda folder: {"label": expected, "reason": "x"})
    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *a, **k: {"old_code": "", "new_code": "",
                                         "diff": "", "test_code": "",
                                         "failure_message": "",
                                         "before_result": "passed",
                                         "after_result": "failed",
                                         "rerun": {"passes": 0, "fails": 4,
                                                   "verdict": "ALWAYS_FAILS"},
                                         "test_name": "t", "description": ""})
    return folders


def log_to(tmp_path, monkeypatch):
    """Send the log file somewhere harmless, so no test writes the real one."""
    log = tmp_path / "heldback_runs.log"
    monkeypatch.setattr(he, "LOG_FILE", log)
    return log


@pytest.fixture(autouse=True)
def clean_globals():
    """Every test starts and ends with the defaults back.

    main() sets ALLOW_FALLBACK and CALLS_MADE as module globals, and the fake AI
    reads LAST_PROVIDER. Left behind, one of these would decide another test's
    result.
    """
    saved = (lc.ALLOW_FALLBACK, lc.CALLS_MADE, lc.LAST_PROVIDER)
    lc.ALLOW_FALLBACK, lc.CALLS_MADE, lc.LAST_PROVIDER = True, 0, ""
    yield
    lc.ALLOW_FALLBACK, lc.CALLS_MADE, lc.LAST_PROVIDER = saved


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Nothing real: no test run, no real cases, no real log, no keys read."""
    monkeypatch.setattr(lc.time, "sleep", lambda seconds: None)
    log_to(tmp_path, monkeypatch)
    measured_log(tmp_path, monkeypatch)


def run_main():
    """Run main() and give back the exit code and everything it printed."""
    code = he.main()
    return code


# ---------------------------------------------------------------------------
# A valid Groq-only run prints the four parts and nothing per-case
# ---------------------------------------------------------------------------

def test_a_valid_run_succeeds(monkeypatch, offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_OK
    printed = capsys.readouterr().out

    assert "cases: 3" in printed
    assert "reruns per case: 12" in printed
    assert "classifiers: rule, llm_full, llm_full_v2" in printed


def test_a_valid_run_gives_one_accuracy_line_per_classifier(monkeypatch,
                                                            offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_OK
    printed = capsys.readouterr().out

    for name in he.CLASSIFIERS:
        assert name in printed
    # Three classifiers, so three score lines and nothing more.
    assert len([line for line in printed.splitlines()
                if line.startswith("rule") or line.startswith("llm_")]) == 3


def test_a_valid_run_prints_nothing_about_any_single_case(monkeypatch, offline,
                                                           capsys):
    """The whole reason the cases are kept back.

    A per-case table, a reason from the AI, or even a folder name would let
    somebody work out which case went wrong and rewrite the prompt against it.
    The cases may be looked at only after the score is in.
    """
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    folders = pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_OK
    printed = capsys.readouterr().out

    for folder in folders:
        assert folder.name not in printed
    # And nothing from the AI's own words.
    assert "because" not in printed


def test_a_valid_run_prints_no_case_names_at_all(monkeypatch, offline, capsys):
    """Checked against the real kept-back folder names as well."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_OK
    printed = capsys.readouterr().out

    for path in ce.case_folders():
        assert path.name not in printed


def test_a_valid_run_never_prints_a_provider_table(monkeypatch, offline, capsys):
    """The tuning eval prints one. This must not, so no model is ever named."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    assert run_main() == he.EXIT_OK
    printed = capsys.readouterr().out

    assert "Groq" not in printed
    assert "Gemini" not in printed


# ---------------------------------------------------------------------------
# A Gemini answer makes the run not valid
# ---------------------------------------------------------------------------

def test_one_gemini_answer_makes_the_run_not_valid(monkeypatch, offline, capsys):
    """One answer out of many is enough. Any mixing at all spoils the score."""
    monkeypatch.setattr(cl, "ask_llm", groq_then_gemini("Gemini"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_NOT_VALID
    printed = capsys.readouterr().out

    assert "RUN NOT VALID: answers came from more than one model" in printed


def test_a_mixed_run_prints_no_accuracy(monkeypatch, offline, capsys):
    """The important one. No number at all, not a number with a warning."""
    monkeypatch.setattr(cl, "ask_llm", groq_then_gemini("Gemini"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_NOT_VALID
    printed = capsys.readouterr().out

    assert "cases:" not in printed
    assert "reruns per case" not in printed
    assert "classifiers:" not in printed
    for name in he.CLASSIFIERS:
        assert f"{name} " not in printed.replace("classifiers", "")


def test_a_mixed_run_prints_no_percentage(monkeypatch, offline, capsys):
    """A percentage is the part that gets quoted, so none may appear."""
    monkeypatch.setattr(cl, "ask_llm", groq_then_gemini("Gemini"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_NOT_VALID
    printed = capsys.readouterr().out

    assert "%" not in printed
    assert "/3" not in printed


def test_the_not_valid_message_has_no_count_in_it(monkeypatch, offline, capsys):
    """The message itself is the required wording, with no count attached.

    The count is useful and it goes in the log file. Putting it on screen would
    invite reading a number off a run we are saying is not a run.
    """
    monkeypatch.setattr(cl, "ask_llm", groq_then_gemini("Gemini"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_NOT_VALID
    printed = capsys.readouterr().out

    first = printed.splitlines()[0]
    assert first == "RUN NOT VALID: answers came from more than one model"


def test_a_gemini_answer_everywhere_is_still_not_valid(monkeypatch, offline,
                                                       capsys):
    """Not a special case of one. Any Gemini answer at all does it."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Gemini"))
    pretend_cases(monkeypatch, count=2)

    assert run_main() == he.EXIT_NOT_VALID


def test_a_mixed_run_is_logged_as_not_valid_with_the_count(monkeypatch, offline):
    """The count is kept, in the log, where nobody will quote it as a result."""
    monkeypatch.setattr(cl, "ask_llm", groq_then_gemini("Gemini"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_NOT_VALID
    line = he.LOG_FILE.read_text(encoding="utf-8").strip()

    assert "NOT VALID" in line
    assert "gemini_answers=1" in line
    assert "NO SCORE" in line


# ---------------------------------------------------------------------------
# A daily limit stops the run
# ---------------------------------------------------------------------------

def test_a_daily_limit_stops_the_run(monkeypatch, offline, capsys):
    counter = {"calls": 0}
    monkeypatch.setattr(cl, "ask_llm", stop_after(counter, 2))
    pretend_cases(monkeypatch, count=4)

    assert run_main() == he.EXIT_DAILY_LIMIT
    printed = capsys.readouterr().out

    assert "RUN STOPPED. A provider is out for the day." in printed


def test_a_stopped_run_prints_no_accuracy(monkeypatch, offline, capsys):
    """The cases reached so far are a subset, so any score from them is wrong."""
    counter = {"calls": 0}
    monkeypatch.setattr(cl, "ask_llm", stop_after(counter, 2))
    pretend_cases(monkeypatch, count=4)

    assert run_main() == he.EXIT_DAILY_LIMIT
    printed = capsys.readouterr().out

    assert "cases:" not in printed
    assert "reruns per case" not in printed
    assert "%" not in printed


def test_a_stopped_run_says_how_many_calls_got_through(monkeypatch, offline,
                                                       capsys):
    """So it is obvious how much of the run there was."""
    counter = {"calls": 0}
    monkeypatch.setattr(cl, "ask_llm", stop_after(counter, 2))
    pretend_cases(monkeypatch, count=4)

    assert run_main() == he.EXIT_DAILY_LIMIT
    printed = capsys.readouterr().out

    assert "Model calls completed before the stop" in printed
    assert "3" in printed


def test_a_stopped_run_stops_promptly(monkeypatch, offline):
    """Four cases were offered and it must not have tried all of them."""
    counter = {"calls": 0}
    monkeypatch.setattr(cl, "ask_llm", stop_after(counter, 2))
    pretend_cases(monkeypatch, count=4)

    assert run_main() == he.EXIT_DAILY_LIMIT
    assert counter["calls"] == 3, "it kept going after the provider gave up"


def test_a_stopped_run_is_logged_as_stopped_with_no_score(monkeypatch, offline):
    counter = {"calls": 0}
    monkeypatch.setattr(cl, "ask_llm", stop_after(counter, 2))
    pretend_cases(monkeypatch, count=4)

    assert run_main() == he.EXIT_DAILY_LIMIT
    line = he.LOG_FILE.read_text(encoding="utf-8").strip()

    assert "STOPPED" in line
    assert "daily limit" in line
    assert "NO SCORE" in line


def test_the_real_daily_message_stops_this_run_too(monkeypatch, offline,
                                                   capsys):
    """Not just DailyLimitReached raised by hand.

    The message is fed through the real is_daily_limit_error check and the real
    retry path, so this proves the wording from a real provider is recognised and
    reaches the stop rather than being waited on.
    """
    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *a, **k: {"prompt": "x"})

    def groq_is_out(prompt, temperature=None):
        raise RuntimeError(GROQ_DAILY)

    with pytest.raises(lc.DailyLimitReached):
        lc.call_with_retry("Groq", groq_is_out, "hi")


def test_the_run_never_falls_back_at_all(monkeypatch, offline, capsys):
    """Set once in main(), with no flag, so it cannot be turned back on.

    If this ever became True mid-run, a score could be half Groq and half Gemini
    and nothing would stop it.
    """
    seen = []
    monkeypatch.setattr(cl, "ask_llm",
                        lambda prompt: seen.append(lc.ALLOW_FALLBACK)
                                       or reply("REAL_BUG"))
    pretend_cases(monkeypatch, count=2)

    assert run_main() == he.EXIT_OK
    assert seen, "no AI call was made"
    assert all(value is False for value in seen), \
        "fallback was allowed during a kept-back run"


def test_there_is_no_flag_to_turn_fallback_back_on():
    """No argument parser on this command, so there is nothing to pass."""
    import inspect

    source = inspect.getsource(he)
    assert "add_argument" not in source
    assert "--no-fallback" not in source


# ---------------------------------------------------------------------------
# Refusing to start while the tuning scores are unfilled
# ---------------------------------------------------------------------------

def test_an_unmeasured_log_stops_the_run(monkeypatch, offline, capsys,
                                         tmp_path):
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_REFUSED
    printed = capsys.readouterr().out

    assert "RUN REFUSED" in printed
    assert "not measured yet" in printed


def test_the_other_phrase_is_refused_too(monkeypatch, offline, capsys,
                                         tmp_path):
    """Both phrases, so a half-filled log cannot slip through."""
    unmeasured_log(tmp_path, monkeypatch, "not yet run")
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_REFUSED
    assert "not yet run" in capsys.readouterr().out


def test_the_refusal_explains_why(monkeypatch, offline, capsys, tmp_path):
    """It has to say enough that the reader agrees with the decision."""
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")
    pretend_cases(monkeypatch, count=2)

    run_main()
    printed = capsys.readouterr().out

    assert "PROMPT_LOG.md" in printed
    assert "tuning" in printed.lower()


def test_a_refused_run_asks_nobody(monkeypatch, offline, capsys, tmp_path):
    """No calls, so a refused run costs nothing."""
    asked = []
    monkeypatch.setattr(cl, "ask_llm", asked.append)
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_REFUSED
    assert asked == [], "it asked somebody after refusing to start"


def test_a_refused_run_touches_no_case(monkeypatch, offline, tmp_path):
    """Not even the evidence collection, which runs pytest 12 times per case."""
    collected = []
    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *a, **k: collected.append(a) or {})
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_REFUSED
    assert collected == [], "it collected evidence after refusing to start"


def test_a_refused_run_prints_no_accuracy(monkeypatch, offline, capsys,
                                          tmp_path):
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")
    pretend_cases(monkeypatch, count=3)

    assert run_main() == he.EXIT_REFUSED
    printed = capsys.readouterr().out

    assert "%" not in printed
    assert "cases:" not in printed


def test_a_missing_prompt_log_is_refused(monkeypatch, offline, capsys,
                                         tmp_path):
    """Absent rather than unmeasured, but the same decision."""
    monkeypatch.setattr(he, "PROMPT_LOG", tmp_path / "not_there.md")
    pretend_cases(monkeypatch, count=2)

    assert run_main() == he.EXIT_REFUSED
    printed = capsys.readouterr().out

    assert "missing" in printed


def test_a_refused_run_is_logged_as_refused(monkeypatch, offline, tmp_path):
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")
    pretend_cases(monkeypatch, count=2)

    assert run_main() == he.EXIT_REFUSED
    line = he.LOG_FILE.read_text(encoding="utf-8").strip()

    assert "REFUSED" in line
    assert "NO SCORE" in line


def test_a_measured_log_lets_the_run_start(monkeypatch, offline, capsys):
    """Otherwise the guard would stop everything forever."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    assert run_main() == he.EXIT_OK
    assert "RUN REFUSED" not in capsys.readouterr().out


def test_the_real_prompt_log_now_lets_the_run_start():
    """Checked against the file in the project, not a pretend one.

    If PROMPT_LOG.md ever goes back to saying it is unmeasured, this fails and we
    know before spending anything that the kept-back run would refuse.
    """
    assert he.prompt_log_is_measured() == "", \
        "the project's PROMPT_LOG.md still reads as unmeasured"


# ---------------------------------------------------------------------------
# The log file
# ---------------------------------------------------------------------------

def test_a_valid_run_appends_a_timestamp_line(monkeypatch, offline):
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    run_main()
    line = he.LOG_FILE.read_text(encoding="utf-8").strip()

    assert "UTC" in line
    assert line.startswith("20")
    assert "valid" in line


def test_a_valid_run_logs_its_scores(monkeypatch, offline):
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    run_main()
    line = he.LOG_FILE.read_text(encoding="utf-8").strip()

    assert "rule=2/2" in line
    assert "llm_full=2/2" in line
    assert "llm_full_v2=2/2" in line


def test_a_run_is_appended_not_overwritten(monkeypatch, offline):
    """Otherwise a later run could quietly erase an earlier one."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    run_main()
    first = he.LOG_FILE.read_text(encoding="utf-8")
    run_main()
    second = he.LOG_FILE.read_text(encoding="utf-8")

    assert second.startswith(first)
    assert len(second.strip().splitlines()) == 2


def test_only_a_valid_run_carries_a_score(monkeypatch, offline, tmp_path):
    """Checked across all three bad outcomes in one go."""
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")
    pretend_cases(monkeypatch, count=2)
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    run_main()

    measured_log(tmp_path, monkeypatch)
    monkeypatch.setattr(cl, "ask_llm", groq_then_gemini("Gemini"))
    run_main()
    lines = he.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()

    counter = {"calls": 0}
    monkeypatch.setattr(cl, "ask_llm", stop_after(counter, 2))
    run_main()
    lines = he.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) == 3
    for line in lines:
        assert "NO SCORE" in line
    # Nothing that could be read as an accuracy anywhere.
    for line in lines:
        assert "/2)" not in line
        assert "=" not in line.split("NO SCORE")[0].split("cases=")[-1]


# ---------------------------------------------------------------------------
# Exit codes, and what each one must not mean
# ---------------------------------------------------------------------------

def test_the_exit_codes_are_all_different():
    """0 must mean valid and nothing else, so no two outcomes can share a code."""
    codes = [he.EXIT_OK, he.EXIT_NO_CASES, he.EXIT_REFUSED, he.EXIT_DAILY_LIMIT,
             he.EXIT_NOT_VALID]

    assert len(set(codes)) == len(codes)
    assert he.EXIT_OK == 0


def test_no_cases_still_returns_one(monkeypatch, offline, capsys):
    """Unchanged from before, and it is not a valid run either."""
    monkeypatch.setattr(he, "case_folders", lambda: [])
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))

    assert run_main() == he.EXIT_NO_CASES


def test_only_a_valid_run_returns_zero(monkeypatch, offline, tmp_path):
    """The one thing a caller is guaranteed by the exit code."""
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")
    pretend_cases(monkeypatch, count=2)
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    assert run_main() != 0

    measured_log(tmp_path, monkeypatch)
    monkeypatch.setattr(cl, "ask_llm", groq_then_gemini("Gemini"))
    assert run_main() != 0

    counter = {"calls": 0}
    monkeypatch.setattr(cl, "ask_llm", stop_after(counter, 2))
    assert run_main() != 0

    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    assert run_main() == 0


# ---------------------------------------------------------------------------
# What the kept-back run is allowed to know
# ---------------------------------------------------------------------------

def test_this_is_still_the_only_file_naming_the_kept_back_folder():
    """That has not changed and must not."""
    import inspect

    assert "classifier_cases_heldback" in inspect.getsource(he)


def test_the_classifiers_are_exactly_the_three_that_were_measured():
    assert he.CLASSIFIERS == ("rule", "llm_full", "llm_full_v2")
    assert "llm_full_with_intent" not in he.CLASSIFIERS
    assert "llm_code_only" not in he.CLASSIFIERS


def test_the_rerun_count_is_still_twelve():
    """Same as the tuning set, so the two scores are measured the same way."""
    assert he.RERUN_TIMES == 12


def test_no_key_can_reach_any_of_this_output(monkeypatch, offline, capsys):
    """The loudest text this run prints is the stop and refusal messages."""
    counter = {"calls": 0}
    monkeypatch.setattr(cl, "ask_llm", stop_after(counter, 1))
    pretend_cases(monkeypatch, count=3)
    run_main()
    printed = capsys.readouterr().out

    for secret_word in ("API_KEY", "gsk_", "AIza"):
        assert secret_word not in printed


def test_the_answers_still_never_get_printed(monkeypatch, offline, capsys):
    """Even on the paths that do print something, no reply text leaks out."""
    monkeypatch.setattr(cl, "ask_llm",
                        lambda prompt: (setattr(lc, "LAST_PROVIDER", "Groq")
                                        or reply("BAD_TEST",
                                                 "a secret reason like gsk_abc")))
    pretend_cases(monkeypatch, count=2)

    run_main()
    printed = capsys.readouterr().out

    assert "a secret reason" not in printed
    assert "gsk_abc" not in printed
