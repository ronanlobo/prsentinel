"""Tests for the once-only guard on the kept-back run.

The four kept-back cases are the one measurement in this project that cannot be
repeated, because repeating it is exactly what would make it worthless. The AI
answers differently each time, so a second score is not a better score, it is a
different sample of the same thing. And a second score is easy to produce by
accident and easy to quote later as though it were the first.

So the guard is not a warning. It refuses, it exits with its own code, it costs
nothing, and it writes down that the refusal happened. Spending the set again is
still possible, but only by asking for it by name, and everything about that run
says it was not the first.

Nothing here runs the kept-back command for real, calls a model, or touches a
real case. The log is a pretend file in a temporary folder and the AI is a fake,
so the real heldback_runs.log is never written by these tests.
"""

import inspect

import pytest

from prsentinel import classifier as cl
from prsentinel import heldback_eval as he
from prsentinel import llm_client as lc

# Reused from the guard tests written in the previous step, so both sets of
# tests drive the same fakes and cannot drift apart.
from test_heldback_guard import (answer_from, clean_globals,  # noqa: F401
                                 groq_then_gemini, offline, pretend_cases,
                                 stop_after, unmeasured_log)


# A log line as the real one looks, so these tests are checked against the shape
# the code actually writes rather than a shape invented here.
def scored_line(outcome="valid",
                detail="cases=4  rule=2/4  llm_full=3/4  llm_full_v2=2/4"):
    return f"2026-10-01 06:57:14 UTC  {outcome}  {detail}\n"


def log_with(tmp_path, monkeypatch, *lines):
    """Give the guard a pretend log holding exactly these lines."""
    path = tmp_path / "heldback_runs.log"
    path.write_text("".join(lines), encoding="utf-8")
    monkeypatch.setattr(he, "LOG_FILE", path)
    return path


@pytest.fixture(autouse=True)
def nothing_real(monkeypatch):
    """Make a live call impossible, so a broken guard fails the test.

    Two of the things these tests check are refusals. If a guard stopped working,
    the command would carry on into the real cases and ask a real model, and the
    test would pass while doing exactly what it exists to prevent. So both doors
    are bolted shut by default here and every test that wants a door open opens
    it in its own body, which happens after this.
    """
    def no_asking(prompt):
        raise AssertionError("the AI was asked during a kept-back test")

    def no_cases():
        raise AssertionError("the real kept-back cases were reached")

    monkeypatch.setattr(cl, "ask_llm", no_asking)
    monkeypatch.setattr(he, "case_folders", no_cases)


def outcome_of(line):
    """Read the outcome word out of a log line.

    The timestamp is three words ("2026-10-01 06:57:14 UTC"), so the outcome is
    the fourth. Written once here so the four tests below cannot each get it
    wrong in their own way.
    """
    return line.split()[3]


def with_spent_log():
    """Write one valid line into the pretend log the offline fixture set up."""
    path = he.LOG_FILE
    path.write_text(scored_line("valid"), encoding="utf-8")
    return path


@pytest.fixture
def spent(offline):
    """Offline, and the set already scored once."""
    return with_spent_log()


def no_case_touched(monkeypatch):
    """Replace case_folders with one that complains if it is called."""
    called = []

    def folders():
        called.append(1)
        return []

    monkeypatch.setattr(he, "case_folders", folders)
    return called


def asks_nobody(monkeypatch):
    """Replace ask_llm with one that complains if it is called."""
    asked = []
    monkeypatch.setattr(cl, "ask_llm", asked.append)
    return asked


# ---------------------------------------------------------------------------
# A set that has been scored refuses to run
# ---------------------------------------------------------------------------

def test_a_scored_set_refuses_to_run(spent, capsys):
    assert he.main([]) == he.EXIT_ALREADY_SCORED
    assert "RUN REFUSED. The kept-back set has already been scored." in capsys.readouterr().out


def test_the_refusal_explains_how_it_knows(spent, capsys):
    he.main([])
    printed = capsys.readouterr().out

    assert "heldback_runs.log" in printed
    assert "valid" in printed


def test_the_refusal_names_the_way_out(spent, capsys):
    """The flag has to be discoverable from the message, or nobody finds it."""
    he.main([])
    printed = capsys.readouterr().out

    assert "--allow-rerun" in printed
    assert "RERUN" in printed


def test_a_refusal_for_this_reason_prints_no_accuracy(spent, capsys):
    """No number at all, not a number with a warning above it."""
    he.main([])
    printed = capsys.readouterr().out

    assert "cases:" not in printed
    assert "reruns per case" not in printed
    assert "classifiers:" not in printed
    assert "%" not in printed


def test_a_refusal_for_this_reason_asks_nobody(monkeypatch, spent):
    """Costs nothing. Nobody is asked and no case is collected."""
    asked = asks_nobody(monkeypatch)
    called = no_case_touched(monkeypatch)

    he.main([])

    assert asked == [], "it called the AI after refusing to run"
    assert called == [], "it went looking for cases after refusing to run"


def test_a_refusal_for_this_reason_is_logged_as_already_scored(spent):
    he.main([])
    line = he.LOG_FILE.read_text(encoding="utf-8").strip()

    assert "REFUSED already scored" in line
    assert "NO SCORE" in line


def test_a_refusal_for_this_reason_appends_rather_than_replaces(spent):
    """So somebody cannot delete the score and pretend it never happened."""
    before = he.LOG_FILE.read_text(encoding="utf-8")

    he.main([])

    after = he.LOG_FILE.read_text(encoding="utf-8")
    assert after.startswith(before)
    assert len(after.strip().splitlines()) == 2


# ---------------------------------------------------------------------------
# Which log lines count as a score
# ---------------------------------------------------------------------------

def test_a_valid_line_counts_as_scored(tmp_path, monkeypatch):
    log_with(tmp_path, monkeypatch, scored_line("valid"))

    assert he.scored_already() is True


def test_a_rerun_line_counts_as_scored(tmp_path, monkeypatch):
    log_with(tmp_path, monkeypatch, scored_line("RERUN"))

    assert he.scored_already() is True


def test_a_second_valid_line_still_counts(tmp_path, monkeypatch):
    """Later lines do not cancel earlier ones."""
    log_with(tmp_path, monkeypatch, scored_line("RERUN"), scored_line("valid"))

    assert he.scored_already() is True


@pytest.mark.parametrize("outcome", ["NOT VALID", "STOPPED daily limit",
                                     "REFUSED", "REFUSED already scored"])
def test_a_line_with_no_score_does_not_count(outcome, tmp_path, monkeypatch):
    """These runs produced nothing, so they must not cost the next attempt.

    Otherwise one daily limit would put the kept-back set permanently out of
    reach, which is the opposite of what the guard is for.
    """
    log_with(tmp_path, monkeypatch, scored_line(outcome, "cases=4  NO SCORE"))

    assert he.scored_already() is False


def test_not_valid_is_not_read_as_valid(tmp_path, monkeypatch):
    """The one line that could go wrong by accident.

    "NOT VALID" contains the word "valid" if the match ignores case, and a case
    insensitive match would throw the set away for a run that never scored.
    """
    log_with(tmp_path, monkeypatch, scored_line("NOT VALID",
                                                "cases=4  gemini_answers=1  NO SCORE"))

    assert he.scored_already() is False


def test_a_missing_log_means_not_scored(tmp_path, monkeypatch):
    """A fresh checkout has no log, and that is not an error."""
    monkeypatch.setattr(he, "LOG_FILE", tmp_path / "not_there.log")

    assert he.scored_already() is False


def test_an_empty_log_means_not_scored(tmp_path, monkeypatch):
    log_with(tmp_path, monkeypatch)

    assert he.scored_already() is False


def test_blank_lines_in_the_log_are_harmless(tmp_path, monkeypatch):
    log_with(tmp_path, monkeypatch, "\n", scored_line("valid"), "\n")

    assert he.scored_already() is True


def test_only_word_wins_never_match(tmp_path, monkeypatch):
    """The log is split on spaces and each word compared whole.

    A line carrying a phrase like "invalid=1" must not read as the "valid" the
    guard looks for.
    """
    log_with(tmp_path, monkeypatch,
             "2026-10-01 UTC  refused  invalid=1  cases=4  NO SCORE\n")

    assert he.scored_already() is False


def test_a_run_with_no_score_still_goes_through(tmp_path, monkeypatch, offline,
                                                capsys):
    """The practical version of the tests above: it runs."""
    log_with(tmp_path, monkeypatch, scored_line("NOT VALID", "cases=4  NO SCORE"))
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    assert he.main([]) == he.EXIT_OK


# ---------------------------------------------------------------------------
# --allow-rerun spends the set again, and says so everywhere
# ---------------------------------------------------------------------------

def test_allow_rerun_runs_the_command(tmp_path, monkeypatch, offline, capsys):
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    assert he.main(["--allow-rerun"]) == he.EXIT_OK
    assert "cases: 2" in capsys.readouterr().out


def test_a_rerun_says_it_is_not_the_first_run(tmp_path, monkeypatch, offline,
                                              capsys):
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main(["--allow-rerun"])
    printed = capsys.readouterr().out

    assert "RUN NOT FIRST" in printed
    assert "not the held-back result" in printed


def test_a_rerun_says_where_the_real_result_is(tmp_path, monkeypatch, offline,
                                               capsys):
    """So a reader who only sees this output knows which number to use."""
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main(["--allow-rerun"])

    assert "PROMPT_LOG.md" in capsys.readouterr().out


def test_the_rerun_line_comes_above_the_numbers(tmp_path, monkeypatch, offline,
                                                capsys):
    """If the notice were below the accuracy, it would read as a footnote."""
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main(["--allow-rerun"])
    printed = capsys.readouterr().out

    assert printed.index("RUN NOT FIRST") < printed.index("cases:")


def test_a_rerun_still_prints_the_accuracy(tmp_path, monkeypatch, offline,
                                           capsys):
    """Asked for by name, so it is run in full rather than half reported."""
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main(["--allow-rerun"])
    printed = capsys.readouterr().out

    assert "classifiers: rule, llm_full, llm_full_v2" in printed
    assert "%" in printed


def test_a_rerun_is_logged_as_a_rerun(tmp_path, monkeypatch, offline):
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main(["--allow-rerun"])
    lines = he.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) == 2
    assert outcome_of(lines[0]) == "valid"
    assert outcome_of(lines[1]) == "RERUN"


def test_a_rerun_line_carries_no_score(tmp_path, monkeypatch, offline):
    """The log holds exactly one scored line, and it is the first one.

    A rerun happened and is written down, but its numbers are not kept. A second
    score sitting in the file is precisely the thing someone would quote later,
    and the on-screen numbers from a rerun are enough to show the model moved.
    """
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main(["--allow-rerun"])
    lines = he.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()

    assert "NO SCORE" in lines[1]
    assert "llm_full=2/2" not in lines[1]
    # And the first line is untouched, so the real result still reads as it did.
    assert lines[0] == scored_line("valid").strip()


def test_a_rerun_still_prints_its_accuracy_on_screen(tmp_path, monkeypatch,
                                                     offline, capsys):
    """Not kept in the file, but not hidden either. The run is still useful."""
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main(["--allow-rerun"])
    printed = capsys.readouterr().out

    assert "rule                   2/2  (100%)" in printed
    assert "llm_full               2/2  (100%)" in printed
    assert "llm_full_v2            2/2  (100%)" in printed


def test_a_first_run_is_not_marked_a_rerun(tmp_path, monkeypatch, offline,
                                           capsys):
    """Passing the flag on an unspent set is an ordinary first run.

    Marking that RERUN would put a false doubt into the log, and the log is what
    the paper counts from.
    """
    log_with(tmp_path, monkeypatch)
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    assert he.main(["--allow-rerun"]) == he.EXIT_OK
    assert "RUN NOT FIRST" not in capsys.readouterr().out


def test_a_first_run_is_logged_as_valid(tmp_path, monkeypatch, offline):
    """The other half of the same rule, checked in the log rather than on screen."""
    log_with(tmp_path, monkeypatch)
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main(["--allow-rerun"])
    line = he.LOG_FILE.read_text(encoding="utf-8").strip()

    assert outcome_of(line) == "valid"


def test_two_reruns_both_marked(monkeypatch, offline):
    """Counting reruns means being able to find them all."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main([])
    he.main(["--allow-rerun"])
    he.main(["--allow-rerun"])

    lines = he.LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    assert [outcome_of(line) for line in lines] == ["valid", "RERUN", "RERUN"]


def test_a_second_rerun_is_still_allowed(monkeypatch, offline):
    """The flag is not spent by being used. It stays a deliberate choice."""
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)

    he.main([])
    he.main(["--allow-rerun"])

    assert he.main(["--allow-rerun"]) == he.EXIT_OK


def test_a_rerun_of_a_mixed_run_is_still_not_valid(monkeypatch, offline):
    """Allowing a second run does not allow a bad one to score."""
    from test_heldback_guard import groq_then_gemini

    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)
    he.main([])

    monkeypatch.setattr(cl, "ask_llm", groq_then_gemini("Gemini"))

    assert he.main(["--allow-rerun"]) == he.EXIT_NOT_VALID


def test_a_rerun_still_never_falls_back(monkeypatch, offline):
    """The flag is about repetition, not about models."""
    seen = []
    monkeypatch.setattr(cl, "ask_llm",
                        lambda prompt: seen.append(lc.ALLOW_FALLBACK)
                                       or '{"label": "REAL_BUG"}')
    pretend_cases(monkeypatch, count=2)

    he.main([])
    he.main(["--allow-rerun"])

    assert seen and all(value is False for value in seen)


# ---------------------------------------------------------------------------
# Which refusal wins
# ---------------------------------------------------------------------------

def test_already_scored_is_checked_before_the_prompt_log(tmp_path, monkeypatch,
                                                         offline, capsys):
    """Both are true here, and the once-only one is the more important fact."""
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")

    assert he.main([]) == he.EXIT_ALREADY_SCORED
    printed = capsys.readouterr().out

    assert "already been scored" in printed
    assert "tuning scores have not been measured" not in printed


def test_allow_rerun_does_not_get_past_the_prompt_log_check(tmp_path,
                                                            monkeypatch,
                                                            offline, capsys):
    """It spends the set, it does not remove the other guards."""
    log_with(tmp_path, monkeypatch, scored_line("valid"))
    unmeasured_log(tmp_path, monkeypatch, "not measured yet")

    assert he.main(["--allow-rerun"]) == he.EXIT_REFUSED


def test_allow_rerun_still_loses_to_the_daily_limit(tmp_path, monkeypatch,
                                                    offline):
    from test_heldback_guard import stop_after

    log_with(tmp_path, monkeypatch, scored_line("valid"))
    pretend_cases(monkeypatch, count=4)
    monkeypatch.setattr(cl, "ask_llm", stop_after({"calls": 0}, 2))

    assert he.main(["--allow-rerun"]) == he.EXIT_DAILY_LIMIT


# ---------------------------------------------------------------------------
# The flag itself
# ---------------------------------------------------------------------------

def test_the_exit_code_is_five():
    assert he.EXIT_ALREADY_SCORED == 5


def test_every_exit_code_is_different():
    codes = [he.EXIT_OK, he.EXIT_NO_CASES, he.EXIT_REFUSED, he.EXIT_DAILY_LIMIT,
             he.EXIT_NOT_VALID, he.EXIT_ALREADY_SCORED]

    assert len(set(codes)) == len(codes)


def test_only_a_valid_run_returns_zero(monkeypatch, offline):
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    pretend_cases(monkeypatch, count=2)
    assert he.main([]) == 0

    # A second run without the flag is not valid, whatever the first one was.
    assert he.main([]) != 0


def test_the_flag_is_off_by_default():
    assert he.parse_args([]).allow_rerun is False


def test_the_flag_takes_no_value():
    """--allow-rerun=yes must be an error, not a quietly accepted truth."""
    with pytest.raises(SystemExit):
        he.parse_args(["--allow-rerun=yes"])


def test_an_unknown_flag_is_refused(capsys):
    """argparse says what the flag was and lists the one that exists."""
    with pytest.raises(SystemExit):
        he.parse_args(["--allow-second-run"])
    printed = capsys.readouterr().err

    assert "--allow-rerun" in printed


def test_the_only_flag_is_about_rerunning():
    """Checked from the source, so a future flag has to be a decision."""
    parser_source = inspect.getsource(he.parse_args)

    assert parser_source.count("add_argument") == 1
    assert "--allow-rerun" in parser_source


def test_main_passes_its_arguments_on():
    """So a caller in a test, or another program, can pass a list."""
    assert "argv" in inspect.signature(he.main).parameters


def test_this_is_still_the_only_file_naming_the_kept_back_folder():
    assert "classifier_cases_heldback" in inspect.getsource(he)


def test_no_key_can_reach_any_of_this_output(spent, capsys):
    """The loudest things this command prints are its refusals."""
    he.main([])
    printed = capsys.readouterr().out

    for secret_word in ("API_KEY", "gsk_", "AIza"):
        assert secret_word not in printed


def test_the_answers_still_never_get_printed(tmp_path, monkeypatch, offline,
                                             capsys):
    """Even on a rerun, which is the run most likely to be written up."""
    monkeypatch.setattr(cl, "ask_llm",
                        lambda prompt: (setattr(lc, "LAST_PROVIDER", "Groq")
                                        or '{"label": "BAD_TEST", "reason": "a secret"}'))
    pretend_cases(monkeypatch, count=2)

    he.main([])
    he.main(["--allow-rerun"])
    printed = capsys.readouterr().out

    assert "a secret" not in printed
