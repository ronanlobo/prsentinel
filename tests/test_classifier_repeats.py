"""Tests for --repeats in `classifier_eval`.

The point of repeating is that one run of a small answer key is only a sample.
For the flaky cases the evidence is different every time as well, so a single
number can look steadier than it is.

Nothing here calls an AI or runs a real test. A fake `ask_llm` and a fixed
evidence dictionary stand in for both, so the tests are quick, offline, and give
the same answer every time.
"""

import inspect
import json
import sys
from pathlib import Path

import pytest

from prsentinel import classifier as cl
from prsentinel import classifier_eval as ce


def make_evidence(**changes):
    """Build evidence with every field filled in, so the prompt is complete."""
    evidence = {
        "old_code": "def add(a, b):\n    return a + b\n",
        "new_code": "def add(a, b):\n    return a + b + c\n",
        "diff": "--- before\n+++ after\n-    return a + b\n+    return a + b + c\n",
        "test_code": "def test_add():\n    assert add(2, 3) == 5\n",
        "failure_message": "assert 8 == 5\n",
        "before_result": "passed",
        "after_result": "failed",
        # No passes and no fails, so the rule does not call it flaky. That keeps
        # the rule's answers steady and leaves the variation to the AI, which is
        # what we are trying to measure.
        "rerun": {"passes": 0, "fails": 4, "verdict": "ALWAYS_FAILS"},
        "test_name": "test_case.py::test_add",
        "description": "",
    }
    evidence.update(changes)
    return evidence


def reply(label, reason="because"):
    """Build the JSON reply the AI would give."""
    return json.dumps({"label": label, "confidence": "high", "reason": reason})


class FakeAI:
    """A stand-in for the AI that hands out labels in a fixed order.

    The labels are given out in order and then start again, so a test can work
    out by hand exactly what every run should produce and check the report
    against that.
    """

    def __init__(self, labels):
        self.labels = list(labels)
        self.prompts = []
        self.at = 0

    def __call__(self, prompt):
        self.prompts.append(prompt)
        label = self.labels[self.at % len(self.labels)]
        self.at += 1
        return reply(label)


@pytest.fixture
def collected(monkeypatch):
    """Take the real test runner out of the picture and count the calls.

    The evidence is gathered afresh every repeat, so counting the calls is how
    we check that it really was gathered afresh.
    """
    seen = []

    def fake_collect_evidence(*args, **kwargs):
        seen.append((args, kwargs))
        return make_evidence()

    monkeypatch.setattr(cl, "collect_evidence", fake_collect_evidence)
    return seen


def use_cases(monkeypatch, count=2, expected="REAL_BUG"):
    """Point the eval at a fixed number of pretend cases."""
    folders = [Path(f"case_number_{number}") for number in range(count)]
    monkeypatch.setattr(ce, "case_folders", lambda: folders)
    monkeypatch.setattr(ce, "read_expected",
                        lambda folder: {"label": expected, "reason": "x"})
    return folders


def run_main(monkeypatch, repeats):
    """Run main() with the given --repeats value."""
    monkeypatch.setattr(sys, "argv", ["classifier_eval", "--repeats",
                                      str(repeats)])
    return ce.main()


# ---------------------------------------------------------------------------
# run_case really is called once per case per repeat
# ---------------------------------------------------------------------------

def test_run_all_cases_runs_every_case_once_per_repeat(monkeypatch, collected):
    """This is the loop the whole feature rests on, so it is checked directly.

    Counting collect_evidence would not prove it on its own, because that is a
    call inside run_case. Watching run_case itself is the honest check.
    """
    seen = []

    def fake_run_case(folder):
        seen.append(folder.name)
        return {"folder": folder.name,
                "results": {name: {"label": "REAL_BUG", "confidence": "",
                                   "reason": ""} for name in ce.CLASSIFIERS},
                "errors": {}}

    monkeypatch.setattr(ce, "run_case", fake_run_case)
    folders = use_cases(monkeypatch, count=3)

    runs = ce.run_all_cases(folders, 3)

    assert len(runs) == 3
    assert len(runs[0]) == 3
    # Three cases, three repeats, every case every time.
    assert seen == [f.name for f in folders] * 3


def test_run_all_cases_collects_the_evidence_again(monkeypatch, collected):
    """Reusing one set of results would make the runs agree for the wrong reason.

    The reruns are what show a test is flaky, and for a flaky case those results
    differ every time. Asking the AI the same fixed question three times would
    only measure the AI, not the case.
    """
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    folders = use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 3) == 0

    # Two cases, three repeats.
    assert len(collected) == 6


def test_one_repeat_collects_once_per_case(monkeypatch, collected):
    """The default still does the minimum work."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=3)

    assert run_main(monkeypatch, 1) == 0

    assert len(collected) == 3


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def test_repeats_defaults_to_one(monkeypatch):
    """Without the option, it runs once, which is how it has always behaved."""
    monkeypatch.setattr(sys, "argv", ["classifier_eval"])
    assert ce.parse_args().repeats == 1


@pytest.mark.parametrize("number", [0, -1, -5])
def test_repeats_must_be_at_least_one(monkeypatch, number):
    """Zero repeats would report on nothing, so it is refused."""
    monkeypatch.setattr(sys, "argv", ["classifier_eval", "--repeats",
                                      str(number)])
    with pytest.raises(SystemExit):
        ce.parse_args()


def test_repeats_accepts_a_normal_number(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["classifier_eval", "--repeats", "3"])
    assert ce.parse_args().repeats == 3


# ---------------------------------------------------------------------------
# One run looks exactly like it always did
# ---------------------------------------------------------------------------

def test_one_run_prints_the_same_headings_it_always_did(monkeypatch, collected,
                                                        capsys):
    """Nothing about repeats shows up when there is only one run."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG", "BAD_TEST"]))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 1) == 0
    printed = capsys.readouterr().out

    assert "=== Accuracy ===" in printed
    assert "=== Wrong answers ===" in printed
    assert f"=== Does any reason mention {ce.GIVEAWAY_PHRASE}? ===" in printed


def test_one_run_adds_no_repeat_reporting(monkeypatch, collected, capsys):
    """The repeat-only output must all be absent with a single run."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG", "BAD_TEST"]))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 1) == 0
    printed = capsys.readouterr().out

    assert "Running the whole set" not in printed
    assert "Run 1 of" not in printed
    assert "Accuracy, every run" not in printed
    assert "How many of the runs" not in printed
    assert "Wrong answers, run" not in printed
    assert "cases it got wrong" not in printed


def test_one_run_never_says_the_word_runs_about_the_report(monkeypatch, collected,
                                                          capsys):
    """The word itself is a giveaway that repeat machinery has leaked in."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG", "BAD_TEST"]))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 1) == 0
    printed = capsys.readouterr().out

    # "reruns" is fine, it is how we describe the flakiness check and it has
    # always been there. The plural "runs" on its own is not.
    for line in printed.splitlines():
        cleaned = line.replace("rerun 12 times", "").replace("reruns", "")
        assert " runs" not in cleaned, f"repeat wording leaked in: {line!r}"


def test_one_run_has_no_run_numbers_on_the_wrong_answers(monkeypatch, collected,
                                                         capsys):
    """With one run there is nothing to say about which run it was."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["BAD_TEST"]))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, 1) == 0
    printed = capsys.readouterr().out

    assert "=== Wrong answers ===" in printed
    assert "Wrong answers, run" not in printed


# ---------------------------------------------------------------------------
# More than one run
# ---------------------------------------------------------------------------

def test_repeated_run_prints_every_runs_accuracy(monkeypatch, collected, capsys):
    """One number per run, then the mean and the range."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG", "BAD_TEST"]))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 3) == 0
    printed = capsys.readouterr().out

    assert "=== Accuracy, every run ===" in printed
    for number in (1, 2, 3):
        assert f"run {number}:" in printed
    assert "mean" in printed
    assert "lowest" in printed
    assert "highest" in printed


def test_repeated_run_prints_the_case_table_only_once(monkeypatch, collected,
                                                      capsys):
    """The per-case labels are printed once, not once per run."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 3) == 0
    printed = capsys.readouterr().out

    # The heading is what we count. The case names also appear in the
    # wrong-answers list further down.
    assert printed.count("expected") == 1


def test_repeated_run_prints_how_often_each_case_was_wrong(monkeypatch, collected,
                                                           capsys):
    """A case wrong every time is not the same as one wrong once."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["BAD_TEST"]))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 3) == 0
    printed = capsys.readouterr().out

    assert "=== How many of the runs each case was wrong ===" in printed
    assert "3/3" in printed
    assert "A star means it was wrong at least once." in printed


def test_a_case_wrong_in_one_run_only_is_counted_as_one(monkeypatch, collected,
                                                        capsys):
    """The count has to be the real number, not the number of runs.

    The rule is right on every run here, so the only counts that move are the
    AI's. The rule column is the check that we are counting the AI's answers and
    not something else.
    """
    # With one case and three runs the AI classifiers are asked in CLASSIFIERS
    # order, three calls per run. llm_full gets the first call of each run.
    ai_names = list(ce.AI_CLASSIFIERS)
    first_of_run = ai_names[0]
    other_names = ai_names[1:]

    labels = []
    for run_number in (1, 2, 3):
        # llm_full is right, right, wrong across the three runs.
        labels.append("REAL_BUG" if run_number != 3 else "BAD_TEST")
        labels.extend(["REAL_BUG"] * len(other_names))

    assert len(labels) == 3 * len(ai_names)

    monkeypatch.setattr(cl, "ask_llm", FakeAI(labels))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, 3) == 0

    printed = capsys.readouterr().out
    table = printed.split("How many of the runs each case was wrong")[1]
    table = table.split("A star means")[0]

    row = [line for line in table.splitlines()
           if line.strip().startswith("case_number_0")][0]

    # The rule never saw the fake AI, so it is right every run: 0/3.
    assert "0/3" in row
    # llm_full was wrong in exactly one of the three runs.
    assert "1/3" in row
    assert "2/3" not in row
    assert "3/3" not in row
    assert first_of_run  # keeps the intent of the test readable


def test_repeated_run_prints_wrong_answers_for_every_run(monkeypatch, collected,
                                                        capsys):
    """Each run says which run it was, so reasons cannot be mixed up."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["BAD_TEST"]))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, 3) == 0
    printed = capsys.readouterr().out

    for number in (1, 2, 3):
        assert f"=== Wrong answers, run {number} ===" in printed
    assert (f"=== Does any reason mention {ce.GIVEAWAY_PHRASE}?, "
            f"run 1 ===") in printed


def test_repeated_run_prints_the_summary_for_the_classifier_being_tried(
        monkeypatch, collected, capsys):
    """The classifier under test gets its own short list at the end."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["BAD_TEST"]))
    use_cases(monkeypatch, count=2)
    # The classifier being tried is not in the set yet, so we point the summary
    # at one that is, to show the machinery works.
    monkeypatch.setattr(ce, "SUMMARY_CLASSIFIER", ce.AI_CLASSIFIERS[0])

    assert run_main(monkeypatch, 2) == 0
    printed = capsys.readouterr().out

    assert f"=== {ce.AI_CLASSIFIERS[0]}: cases it got wrong ===" in printed
    assert "wrong in 2 of 2 runs" in printed


def test_the_summary_says_when_nothing_was_wrong(monkeypatch, collected, capsys):
    """An empty summary has to say so, not print nothing at all."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=1)
    monkeypatch.setattr(ce, "SUMMARY_CLASSIFIER", ce.AI_CLASSIFIERS[0])

    assert run_main(monkeypatch, 2) == 0
    printed = capsys.readouterr().out

    assert "none, it got every case right in every run" in printed


def test_the_summary_stays_quiet_for_a_classifier_that_is_not_being_run(
        monkeypatch, collected, capsys):
    """Nothing to report about a classifier that is not in the set."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=1)
    monkeypatch.setattr(ce, "SUMMARY_CLASSIFIER", "not_a_classifier")

    assert run_main(monkeypatch, 2) == 0
    printed = capsys.readouterr().out

    assert "cases it got wrong" not in printed


def test_the_summary_only_names_the_classifier_it_was_pointed_at(
        monkeypatch, collected, capsys):
    """It is about one classifier, so it says nothing about the others."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["BAD_TEST"]))
    use_cases(monkeypatch, count=1)
    monkeypatch.setattr(ce, "SUMMARY_CLASSIFIER", "rule")

    assert run_main(monkeypatch, 2) == 0
    printed = capsys.readouterr().out

    assert "=== rule: cases it got wrong ===" in printed


# ---------------------------------------------------------------------------
# The model is still only asked one thing at a time
# ---------------------------------------------------------------------------

def test_calls_are_made_one_at_a_time(monkeypatch, collected):
    """Two things running together would hit the rate limits.

    We check the fake is never re-entered. If the code ever started two calls at
    once, the second would arrive while the first was still inside this
    function, and the counter would show it.
    """
    inside = {"now": 0, "overlapped": False}

    def careful_ask(prompt):
        inside["now"] += 1
        if inside["now"] > 1:
            inside["overlapped"] = True
        inside["now"] -= 1
        return reply("REAL_BUG")

    monkeypatch.setattr(cl, "ask_llm", careful_ask)
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 2) == 0
    assert not inside["overlapped"]


def test_every_classifier_is_asked_for_every_case_every_run(monkeypatch, collected):
    """A missing call would quietly shrink the answer key."""
    fake = FakeAI(["REAL_BUG"])
    monkeypatch.setattr(cl, "ask_llm", fake)
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, 3) == 0

    # Two cases, three runs, every AI classifier.
    assert fake.at == 2 * 3 * len(ce.AI_CLASSIFIERS)


# ---------------------------------------------------------------------------
# The AI answering badly must not stop the report
# ---------------------------------------------------------------------------

def test_an_unreadable_reply_is_still_reported(monkeypatch, collected, capsys):
    """A failure has to be visible rather than silently dropped."""
    monkeypatch.setattr(cl, "ask_llm", lambda prompt: "not json at all")
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, 2) == 0
    printed = capsys.readouterr().out

    assert "AI_ERROR" in printed
    assert "Wrong answers, run 1" in printed
    assert "Wrong answers, run 2" in printed


# ---------------------------------------------------------------------------
# The held-back command must not grow a --repeats
# ---------------------------------------------------------------------------

def test_the_heldback_command_has_no_repeats_option():
    """One score on cases we kept back, so there is nothing to average."""
    from prsentinel import heldback_eval as he

    source = inspect.getsource(he.main)
    assert "repeats" not in source
    assert "argparse" not in inspect.getsource(he)
