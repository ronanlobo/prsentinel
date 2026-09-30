"""Tests for the answer key in `examples/classifier_cases/`.

Each case folder holds four files:

    before.py       the correct version of a small module
    after.py        the changed version
    test_case.py    a hand-written pytest file that imports from `target`
    expected.json   the right answer, in {"label", "reason"}

Nothing here calls an AI and nothing touches the internet. The expected.json
files are only ever read by this test file. No part of PRSentinel is given
them, because a classifier must never see the answer key.

The three kinds of case:

    REAL_BUG  the changed code is wrong, and the test catches it, so the test
              passes on before.py and fails on after.py
    BAD_TEST  the code is fine on both sides and the test is wrong, so it
              fails on before.py and on after.py
    FLAKY     the code is fine on both sides and the test passes or fails
              depending on which rerun it is, so rerun_failures calls it
              FLAKY

A flaky test cannot be checked with a single run, because one run only tells
you one half of the story. So for the FLAKY cases we check the reruns instead
and say nothing about the single run.
"""

import json
from pathlib import Path

import pytest

from prsentinel import test_runner as tr

# Where the answer key lives.
CASES_FOLDER = Path(__file__).resolve().parent.parent / "examples" / "classifier_cases"

# The files every case folder must have.
REQUIRED_FILES = ("before.py", "after.py", "test_case.py", "expected.json")

# The three answers a case may have.
ALL_LABELS = ("REAL_BUG", "BAD_TEST", "FLAKY")

# How many times we rerun a flaky case. We use fewer than the usual five so the
# test suite stays quick. Our flaky cases fail on every even rerun, so four is
# always two passes and two fails.
CASE_RERUN_TIMES = 4


def case_folders():
    """Return every case folder, sorted so the run order never changes."""
    return sorted(path for path in CASES_FOLDER.iterdir() if path.is_dir())


def read_expected(folder):
    """Read one case's answer key."""
    return json.loads((folder / "expected.json").read_text(encoding="utf-8"))


def case_ids():
    """Return the name of every case, for pytest to use as a test id."""
    return [folder.name for folder in case_folders()]


def folders_with_label(label):
    """Return only the cases whose answer key says `label`."""
    return [folder for folder in case_folders()
            if read_expected(folder)["label"] == label]


def case_names(folders):
    """Turn a list of folders into a list of short names for pytest."""
    return [folder.name for folder in folders]


def results_for(folder):
    """Run a case's test file against both versions, keeping it quiet."""
    rows = tr.evaluate_tests(folder / "before.py",
                             folder / "after.py",
                             folder / "test_case.py")
    assert rows, f"{folder.name}: no results came back at all"
    return rows


# ---------------------------------------------------------------------------
# The shape of the answer key
# ---------------------------------------------------------------------------

def test_there_are_nine_cases():
    """We agreed on nine cases, three of each kind."""
    assert len(case_folders()) == 9


def test_there_are_three_of_each_kind():
    """The key is balanced, so we cannot score well by guessing a label."""
    counts = {label: 0 for label in ALL_LABELS}
    for folder in case_folders():
        counts[read_expected(folder)["label"]] += 1

    assert counts == {"REAL_BUG": 3, "BAD_TEST": 3, "FLAKY": 3}


@pytest.mark.parametrize("folder", case_folders(), ids=case_ids())
def test_every_case_has_all_four_files(folder):
    """A case with a missing file cannot be checked, so we catch it here."""
    for filename in REQUIRED_FILES:
        assert (folder / filename).is_file(), \
            f"{folder.name} is missing {filename}"


@pytest.mark.parametrize("folder", case_folders(), ids=case_ids())
def test_every_answer_key_holds_only_a_label_and_a_reason(folder):
    """expected.json must be small and easy to read."""
    expected = read_expected(folder)

    assert set(expected) == {"label", "reason"}, \
        f"{folder.name}: expected.json may only hold 'label' and 'reason'"
    assert expected["label"] in ALL_LABELS, \
        f"{folder.name}: {expected['label']!r} is not one we know"
    assert isinstance(expected["reason"], str)
    assert expected["reason"].strip(), f"{folder.name}: the reason is empty"
    # One plain sentence, so it ends with a full stop.
    assert expected["reason"].strip().endswith("."), \
        f"{folder.name}: the reason should be a sentence"


@pytest.mark.parametrize("folder", case_folders(), ids=case_ids())
def test_the_two_versions_are_not_the_same_file(folder):
    """A case needs a change, otherwise there is nothing to classify."""
    before = (folder / "before.py").read_text(encoding="utf-8")
    after = (folder / "after.py").read_text(encoding="utf-8")
    assert before != after, f"{folder.name}: before.py and after.py are identical"


@pytest.mark.parametrize("folder", case_folders(), ids=case_ids())
def test_every_case_holds_exactly_one_test(folder):
    """One test per case keeps the answer key easy to read and to score."""
    text = (folder / "test_case.py").read_text(encoding="utf-8")
    assert text.count("\ndef test_") == 1, \
        f"{folder.name}: a case should hold exactly one test"


# ---------------------------------------------------------------------------
# REAL_BUG: passes on the old code, fails on the new code
# ---------------------------------------------------------------------------

REAL_BUG_FOLDERS = folders_with_label("REAL_BUG")
BAD_TEST_FOLDERS = folders_with_label("BAD_TEST")
FLAKY_FOLDERS = folders_with_label("FLAKY")


@pytest.mark.parametrize("folder", REAL_BUG_FOLDERS,
                         ids=case_names(REAL_BUG_FOLDERS))
def test_a_real_bug_case_passes_before_and_fails_after(folder):
    """The test works, so it only fails once the code is broken."""
    for row in results_for(folder):
        assert row["before"] == tr.PASSED, \
            f"{folder.name}: the test must pass on the correct code"
        assert row["after"] in (tr.FAILED, tr.TEST_ERROR), \
            f"{folder.name}: the test must fail on the broken code"
        assert row["label"] == tr.CATCHES_CHANGE, \
            f"{folder.name}: a test that catches the change should say so"


# ---------------------------------------------------------------------------
# BAD_TEST: fails on both the old code and the new code
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("folder", BAD_TEST_FOLDERS,
                         ids=case_names(BAD_TEST_FOLDERS))
def test_a_bad_test_case_fails_on_both_sides(folder):
    """The test is wrong, so it fails even when the code is correct."""
    for row in results_for(folder):
        assert row["before"] in (tr.FAILED, tr.TEST_ERROR), \
            f"{folder.name}: a wrong test must fail on the correct code"
        assert row["after"] in (tr.FAILED, tr.TEST_ERROR), \
            f"{folder.name}: a wrong test must fail on the changed code too"
        assert row["label"] == tr.TEST_WRONG_ON_BEFORE, \
            f"{folder.name}: the runner should spot that the test was wrong"


# ---------------------------------------------------------------------------
# FLAKY: mixed across the reruns
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("folder", FLAKY_FOLDERS,
                         ids=case_names(FLAKY_FOLDERS))
def test_a_flaky_case_gives_a_mixed_result_across_reruns(folder):
    """A test that flips between passing and failing is flaky."""
    # We rerun the new code, because that is the side the test is meant to be
    # judging. One run cannot show flakiness, so we insist on a mix.
    result = tr.rerun_failures(folder / "after.py",
                               folder / "test_case.py",
                               times=CASE_RERUN_TIMES)

    assert result["tests"], f"{folder.name}: no tests came back from the reruns"
    for name, row in result["tests"].items():
        assert row["verdict"] == tr.FLAKY, \
            f"{folder.name}: {name} should be flaky, but it was {row['verdict']}"
        assert row["passes"] and row["fails"], \
            f"{folder.name}: {name} must both pass and fail to be flaky"
