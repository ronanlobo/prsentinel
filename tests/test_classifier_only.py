"""Tests for --only in `classifier_eval`.

--only exists so a comparison can be made when the daily allowance is tight.
That makes it the option most likely to be used under pressure, which is exactly
when a quiet mistake is most dangerous: a misspelled name that gets skipped looks
identical to a classifier nobody asked anything.

So the tests here care most about the two ways this can go wrong quietly:
a name we do not recognise must be refused, and a classifier left out must
appear nowhere in the report.

Nothing here calls an AI or runs a real test.
"""

import inspect
import json
import sys
from pathlib import Path

import pytest

from prsentinel import classifier as cl
from prsentinel import classifier_eval as ce
from prsentinel import llm_client as lc

from test_classifier_providers import answer_from
from test_classifier_repeats import FakeAI, make_evidence, reply, use_cases


@pytest.fixture(autouse=True)
def reset_choice():
    """Every test starts and ends with every classifier chosen."""
    ce.CHOSEN = None
    ce.reset_provider_tally()
    yield
    ce.CHOSEN = None
    ce.reset_provider_tally()


@pytest.fixture
def offline(monkeypatch):
    """Take the real test runner and the real AI out of the picture."""
    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *args, **kwargs: make_evidence())


def run_main(monkeypatch, only=None, repeats=1):
    argv = ["classifier_eval", "--repeats", str(repeats)]
    if only is not None:
        argv += ["--only", only]
    monkeypatch.setattr(sys, "argv", argv)
    return ce.main()


def choose(only):
    """Set the choice directly, the way main() would after parsing."""
    ce.CHOSEN = only
    return ce.chosen()


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def test_without_the_option_every_classifier_runs():
    """Today's behaviour has to be exactly what it was."""
    monkey_argv = ["classifier_eval"]
    old = sys.argv
    try:
        sys.argv = monkey_argv
        assert ce.parse_args().only is None
    finally:
        sys.argv = old

    assert ce.chosen() == ce.CLASSIFIERS


def test_a_list_is_accepted():
    old = sys.argv
    try:
        sys.argv = ["classifier_eval", "--only", "rule,llm_full_v2"]
        assert ce.parse_args().only == ("rule", "llm_full_v2")
    finally:
        sys.argv = old


def test_spaces_around_names_do_not_matter():
    """A human types spaces. They should not be treated as part of a name."""
    old = sys.argv
    try:
        sys.argv = ["classifier_eval", "--only", " rule , llm_full "]
        assert ce.parse_args().only == ("rule", "llm_full")
    finally:
        sys.argv = old


def test_the_order_asked_for_does_not_move_the_columns():
    """Columns stay where they always were, whatever order was asked for.

    A column jumping about makes two reports hard to read side by side, which is
    the whole reason for printing a table at all.
    """
    assert choose(("llm_full_v2", "rule")) == ("rule", "llm_full_v2")
    assert choose(("rule", "llm_full_v2")) == ("rule", "llm_full_v2")


def test_a_repeated_name_is_only_run_once():
    """Asking twice must not double the cost or duplicate a column."""
    assert choose(("rule", "llm_full", "rule")) == ("rule", "llm_full")


@pytest.mark.parametrize("name", ["llm_fullv2", "LLM_FULL", "llm-flags", "llm",
                                  "full", "intent", "v2", "rule,llm_fullv2",
                                  ""])
def test_an_unknown_name_is_refused(monkeypatch, name):
    """A name we do not know is refused, never quietly skipped.

    Silently skipping would look exactly like a classifier that was never asked
    anything, and the report would then be wrong without saying so.
    """
    monkeypatch.setattr(sys, "argv", ["classifier_eval", "--only", name])
    with pytest.raises(SystemExit):
        ce.parse_args()


def test_a_refused_name_says_which_and_what_is_allowed(monkeypatch, capsys):
    """The message has to be enough to fix it without reading the source."""
    monkeypatch.setattr(sys, "argv", ["classifier_eval", "--only", "nope"])
    with pytest.raises(SystemExit):
        ce.parse_args()

    message = capsys.readouterr().err
    assert "nope" in message
    for name in ce.CLASSIFIERS:
        assert name in message


def test_every_unknown_name_is_listed_at_once(monkeypatch, capsys):
    """One go should be enough to fix them all."""
    monkeypatch.setattr(sys, "argv",
                        ["classifier_eval", "--only", "rule,aaa,bbb"])
    with pytest.raises(SystemExit):
        ce.parse_args()

    message = capsys.readouterr().err
    assert "aaa" in message
    assert "bbb" in message


def test_one_bad_name_stops_the_whole_list(monkeypatch):
    """Four good names and one bad one is still refused.

    Running four of them and forgetting the fifth would produce a report that
    looks complete and is not.
    """
    monkeypatch.setattr(sys, "argv",
                        ["classifier_eval", "--only",
                         "rule,llm_full,llm_full_v2,llm_code_only,typo"])
    with pytest.raises(SystemExit):
        ce.parse_args()


@pytest.mark.parametrize("text", ["", " ", ",", " , , "])
def test_a_list_with_nothing_in_it_is_refused(monkeypatch, text):
    """Running no classifiers at all would report on nothing."""
    monkeypatch.setattr(sys, "argv", ["classifier_eval", "--only", text])
    with pytest.raises(SystemExit):
        ce.parse_args()


def test_the_refusal_happens_before_any_work_is_done(monkeypatch):
    """Nothing is collected and nobody is asked if the names are wrong."""
    collected = []
    monkeypatch.setattr(cl, "collect_evidence",
                        lambda *a, **k: collected.append(a) or make_evidence())
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    monkeypatch.setattr(sys, "argv", ["classifier_eval", "--only", "typo"])
    use_cases(monkeypatch, count=2)

    with pytest.raises(SystemExit):
        ce.main()

    assert collected == [], "it collected evidence before checking the names"


# ---------------------------------------------------------------------------
# Only the chosen ones are asked
# ---------------------------------------------------------------------------

def test_only_the_chosen_classifiers_are_asked(monkeypatch, offline):
    fake = FakeAI(["REAL_BUG"])
    monkeypatch.setattr(cl, "ask_llm", fake)
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, only="llm_full,llm_full_v2") == 0

    # Two cases, two classifiers. The rule asks nobody.
    assert fake.at == 4


def test_the_rule_costs_nothing_when_it_is_chosen(monkeypatch, offline):
    fake = FakeAI(["REAL_BUG"])
    monkeypatch.setattr(cl, "ask_llm", fake)
    use_cases(monkeypatch, count=3)

    assert run_main(monkeypatch, only="rule,llm_full") == 0

    assert fake.at == 3


def test_asking_the_rule_alone_makes_no_model_calls(monkeypatch, offline):
    """That is the whole point of it being plain Python."""
    fake = FakeAI(["REAL_BUG"])
    monkeypatch.setattr(cl, "ask_llm", fake)
    use_cases(monkeypatch, count=3)

    assert run_main(monkeypatch, only="rule") == 0

    assert fake.at == 0


# ---------------------------------------------------------------------------
# Only the chosen ones are printed
# ---------------------------------------------------------------------------

def test_the_table_has_a_column_for_each_chosen_one_only(
        monkeypatch, offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, only="llm_full,llm_full_v2") == 0
    printed = capsys.readouterr().out

    table = printed.split("Columns:")[1].splitlines()[0].strip()
    assert table == "full is llm_full, v2 is llm_full_v2"

    # The two we did not choose must not be named as columns.
    header = printed.split("case")[1].splitlines()[0]
    for absent in ("intent", "code_only"):
        assert absent not in header


def names_listed_in(block):
    """Which classifiers a report section actually names.

    Read word by word rather than by substring, because "llm_full" is inside
    "llm_full_v2" and "llm_full_with_intent". A substring check would say the
    wrong thing and quietly pass.
    """
    names = []
    for line in block.splitlines():
        head = line.split()
        if head and head[0] in ce.CLASSIFIERS:
            names.append(head[0])
    return names


def test_the_accuracy_list_covers_only_the_chosen(monkeypatch, offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, only="llm_full_v2") == 0
    printed = capsys.readouterr().out

    accuracy = printed.split("=== Accuracy ===")[1]
    accuracy = accuracy.split("=== Wrong answers ===")[0]

    assert names_listed_in(accuracy) == ["llm_full_v2"]


def test_a_wrong_answer_from_a_classifier_left_out_is_not_printed(
        monkeypatch, offline, capsys):
    """The saving is real: we are not shown what we did not ask for."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["BAD_TEST"]))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, only="rule") == 0
    printed = capsys.readouterr().out

    wrong = printed.split("=== Wrong answers ===")[1]
    wrong = wrong.split("===")[0]
    assert "llm_full" not in wrong
    assert "none, every classifier got every case right" in wrong


def test_the_provider_counts_carry_only_the_chosen(monkeypatch, offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", answer_from("Groq"))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, only="llm_full_v2") == 0
    printed = capsys.readouterr().out

    table = printed.split("=== Where the answers came from ===")[1]
    # The last line is a sentence about the rule classifier, not a row.
    rows = "\n".join(table.splitlines()[:-1])
    assert names_listed_in(rows) == ["llm_full_v2"]


def test_the_repeat_tables_carry_only_the_chosen(monkeypatch, offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["BAD_TEST"]))
    use_cases(monkeypatch, count=2)

    assert run_main(monkeypatch, only="llm_full,llm_full_v2", repeats=2) == 0
    printed = capsys.readouterr().out

    accuracy = printed.split("=== Accuracy, every run ===")[1]
    accuracy = accuracy.split("=== How many")[0]
    assert names_listed_in(accuracy) == ["llm_full", "llm_full_v2"]

    counts = printed.split("=== How many of the runs each case was wrong ===")[1]
    counts = counts.split("A star means")[0]
    assert names_listed_in(counts) == []  # a table of case names, not columns
    assert "intent" not in counts and "code_only" not in counts
    assert "full" in counts and "v2" in counts


def test_the_giveaway_check_covers_only_the_chosen(monkeypatch, offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, only="llm_full_v2") == 0
    printed = capsys.readouterr().out

    check = printed.split(ce.GIVEAWAY_PHRASE + "? ===")[1]
    check = check.split("===")[0]
    assert "llm_full_v2: no" in check
    assert "llm_code_only" not in check


def test_the_rule_is_skipped_in_the_giveaway_check(monkeypatch, offline, capsys):
    """It writes no reason, so reporting it as clean would be a false all-clear."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["REAL_BUG"]))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, only="rule,llm_full") == 0
    printed = capsys.readouterr().out

    check = printed.split(ce.GIVEAWAY_PHRASE + "? ===")[1]
    check = check.split("===")[0]
    assert "rule:" not in check


def test_the_summary_is_quiet_when_its_classifier_is_left_out(
        monkeypatch, offline, capsys):
    """Otherwise the summary would report on a classifier that never ran."""
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["BAD_TEST"]))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, only="llm_full", repeats=2) == 0
    printed = capsys.readouterr().out

    assert "cases it got wrong" not in printed


def test_the_summary_appears_when_its_classifier_is_chosen(
        monkeypatch, offline, capsys):
    monkeypatch.setattr(cl, "ask_llm", FakeAI(["BAD_TEST"]))
    use_cases(monkeypatch, count=1)

    assert run_main(monkeypatch, only="llm_full_v2", repeats=2) == 0
    printed = capsys.readouterr().out

    assert f"=== {ce.SUMMARY_CLASSIFIER}: cases it got wrong ===" in printed


# ---------------------------------------------------------------------------
# The held-back command must not grow it
# ---------------------------------------------------------------------------

def test_the_heldback_command_has_no_only_option():
    """One score on cases we kept back, and it is not a tuning decision.

    Choosing what to run is something you do while tuning. It must not appear
    on the command that scores the cases we kept back, because then the score
    could be taken on a flattering subset.
    """
    from prsentinel import heldback_eval as he

    assert "--only" not in inspect.getsource(he)


def test_choosing_nothing_does_not_change_the_heldback_classifier_list():
    from prsentinel import heldback_eval as he

    assert he.CLASSIFIERS == ("rule", "llm_full", "llm_full_with_intent",
                              "llm_code_only")