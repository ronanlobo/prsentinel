"""Tests for the answer key in `examples/classifier_cases/`.

Each case folder holds four files:

    before.py       the correct version of a small module
    after.py        the changed version
    test_case.py    a hand-written pytest file that imports from `target`
    expected.json   the right answer, in {"label", "reason"}

The hard cases added later hold a fifth file, description.txt, which says what
the change was for. Only the llm_full_with_intent mode is ever shown it.

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

The hard cases are the ones the plain rules are meant to get wrong. Each breaks
one rule in a way a real project would, and is checked separately below. The
cases we keep back, in examples/classifier_cases_heldback/, are only checked
for their shape here. They are scored by heldback_eval.py, once, at the end.
"""

import json
from pathlib import Path

import pytest

from prsentinel import test_runner as tr

# Where the answer key lives.
CASES_FOLDER = Path(__file__).resolve().parent.parent / "examples" / "classifier_cases"

# The cases we keep back are scored by a separate command, and this file never
# looks at them. See SPLIT.md for the split, which must not change.
HELDBACK_FOLDER = (Path(__file__).resolve().parent.parent
                   / "examples" / "classifier_cases_heldback")

# The files every case folder must have.
REQUIRED_FILES = ("before.py", "after.py", "test_case.py", "expected.json")

# The three answers a case may have.
ALL_LABELS = ("REAL_BUG", "BAD_TEST", "FLAKY")

# How many times we rerun a flaky case. We use fewer than the usual five so the
# test suite stays quick. Our flaky cases fail on every even rerun, so four is
# always two passes and two fails.
CASE_RERUN_TIMES = 4

# The nine cases we started with. They are named here rather than counted, so
# that adding more cases later cannot quietly weaken the checks on these. They
# stay on four reruns, which is all their flaky cases need.
ORIGINAL_CASES = (
    "bad_test_invented_rule",
    "bad_test_wrong_assumption",
    "bad_test_wrong_expected_value",
    "flaky_current_time",
    "flaky_random_pick",
    "flaky_set_order",
    "real_bug_loop_skips_last",
    "real_bug_off_by_one",
    "real_bug_wrong_divisor",
)

# The hard cases added later. Their flakiness comes from set ordering, which
# comes out roughly half and half, so four reruns would come out all one way
# about one time in eight. Twelve brings that down to about one in a thousand,
# which is safe enough to keep in a suite that has to be reliable.
HARD_CASE_RERUN_TIMES = 12

# How many reruns the dedicated proof test uses, to be as sure as we can be.
PROOF_RERUN_TIMES = 20

# The words that would give the answer away if they turned up in a case file.
# A case file is shown to the AI, so a name like "flaky" in a docstring tells
# it the answer before it has read anything.
GIVEAWAY_WORDS = ("bug", "wrong", "flaky", "outdated", "random", "intentional",
                  "deprecated")

# The files in a case folder that the AI is shown, and therefore the ones we
# scan for giveaway words. The description counts, because full_with_intent
# puts it straight into the prompt.
#
# expected.json is the one file that cannot be scanned. It holds the answer
# itself, so it necessarily contains the words: a FLAKY case has to say
# "FLAKY", and an OUTDATED_TEST case has to say "OUTDATED_TEST". It is also
# never shown to any classifier, so there is nothing to leak.
SCANNED_FILES = ("before.py", "after.py", "test_case.py", "description.txt")

# The kinds of hard case we added, and the name each one records in expected.
HARD_KINDS = ("OUTDATED_TEST", "PRE_EXISTING_BUG", "FLAKY_REALISTIC")


def case_folders():
    """Return every case folder, sorted so the run order never changes."""
    return sorted(path for path in CASES_FOLDER.iterdir() if path.is_dir())


def read_expected(folder):
    """Read one case's answer key."""
    return json.loads((folder / "expected.json").read_text(encoding="utf-8"))


def case_ids():
    """Return the name of every case, for pytest to use as a test id."""
    return [folder.name for folder in case_folders()]


def hard_case_folders():
    """Return only the hard cases in the tuning set."""
    return [folder for folder in case_folders()
            if folder.name.startswith("hard_")]


def original_case_folders():
    """Return only the nine cases we started with."""
    return [folder for folder in case_folders()
            if folder.name in ORIGINAL_CASES]


def folders_with_label(label, only_original=False):
    """Return only the cases whose answer key says `label`.

    only_original leaves out the hard cases, which break the simple rules on
    purpose and so are checked by their own tests further down.
    """
    folders = original_case_folders() if only_original else case_folders()
    return [folder for folder in folders
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

def test_the_original_nine_cases_are_all_still_here():
    """The first nine are named, not counted, so none can quietly go missing."""
    names = {folder.name for folder in case_folders()}
    missing = [name for name in ORIGINAL_CASES if name not in names]
    assert missing == [], f"original cases are missing: {missing}"


def test_there_are_three_of_each_kind():
    """The key is balanced, so we cannot score well by guessing a label."""
    counts = {label: 0 for label in ALL_LABELS}
    for folder in original_case_folders():
        counts[read_expected(folder)["label"]] += 1

    assert counts == {"REAL_BUG": 3, "BAD_TEST": 3, "FLAKY": 3}


def test_there_are_fourteen_cases_in_the_tuning_set():
    """Nine to start with, plus five hard ones, all in the tuning folder."""
    assert len(case_folders()) == 14


def test_the_whole_tuning_key_is_balanced():
    """Across all fourteen, no label is common enough to guess."""
    counts = {label: 0 for label in ALL_LABELS}
    for folder in case_folders():
        counts[read_expected(folder)["label"]] += 1

    assert counts == {"REAL_BUG": 5, "BAD_TEST": 5, "FLAKY": 4}


@pytest.mark.parametrize("folder", case_folders(), ids=case_ids())
def test_every_case_has_all_four_files(folder):
    """A case with a missing file cannot be checked, so we catch it here."""
    for filename in REQUIRED_FILES:
        assert (folder / filename).is_file(), \
            f"{folder.name} is missing {filename}"


@pytest.mark.parametrize("folder", original_case_folders(),
                         ids=case_names(original_case_folders()))
def test_an_original_answer_key_holds_only_a_label_and_a_reason(folder):
    """The first nine keys stay exactly as they were: two fields, no more."""
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


def test_the_original_nine_have_no_kind_field():
    """Only the hard cases record their kind. The first nine are untouched."""
    for folder in original_case_folders():
        assert "kind" not in read_expected(folder), \
            f"{folder.name}: the original cases must not gain a 'kind' field"


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

REAL_BUG_FOLDERS = folders_with_label("REAL_BUG", only_original=True)
BAD_TEST_FOLDERS = folders_with_label("BAD_TEST", only_original=True)
FLAKY_FOLDERS = folders_with_label("FLAKY", only_original=True)


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


# ---------------------------------------------------------------------------
# The hard cases added in Step 7A
# ---------------------------------------------------------------------------
#
# These are the cases the plain rules are meant to get wrong. Each kind breaks
# a different rule:
#
#   OUTDATED_TEST    the change was made on purpose, so an older test now fails
#                    on the new code. Passes before, fails after, which is the
#                    exact shape of a real change breaking something.
#   PRE_EXISTING_BUG the code already had a problem before the change, so the
#                    test fails on both sides. Fails on both, which is the exact
#                    shape of a test that is simply wrong.
#   FLAKY_REALISTIC  the answer comes out of a set, so it changes from run to
#                    run. Nothing in these cases reads PRSENTINEL_RUN_INDEX, so
#                    the only way to spot them is the reruns.

HARD_FOLDERS = hard_case_folders()


@pytest.mark.parametrize("folder", HARD_FOLDERS, ids=case_names(HARD_FOLDERS))
def test_every_hard_case_records_its_kind(folder):
    """The kind is only for reporting, but it has to be one we know."""
    expected = read_expected(folder)
    assert set(expected) == {"label", "reason", "kind"}, \
        f"{folder.name}: a hard case holds 'label', 'reason' and 'kind'"
    assert expected["kind"] in HARD_KINDS, \
        f"{folder.name}: {expected['kind']!r} is not a kind we know"


@pytest.mark.parametrize("folder", HARD_FOLDERS, ids=case_names(HARD_FOLDERS))
def test_every_hard_case_has_a_description(folder):
    """full_with_intent reads a description, so every hard case needs one."""
    text = (folder / "description.txt").read_text(encoding="utf-8")
    assert text.strip(), f"{folder.name}: the description is empty"
    # A few plain sentences, not a paragraph.
    assert len(text.split()) < 80, \
        f"{folder.name}: the description should be short"


def hard_folders_of_kind(kind):
    """Return the hard cases that record the given kind."""
    return [folder for folder in HARD_FOLDERS
            if read_expected(folder)["kind"] == kind]


def test_each_hard_kind_appears_in_the_tuning_set():
    """We said two of two of one, and that is what should be here."""
    counts = {kind: len(hard_folders_of_kind(kind)) for kind in HARD_KINDS}
    assert counts == {"OUTDATED_TEST": 2, "PRE_EXISTING_BUG": 2,
                      "FLAKY_REALISTIC": 1}


OUTDATED_FOLDERS = hard_folders_of_kind("OUTDATED_TEST")
PRE_EXISTING_FOLDERS = hard_folders_of_kind("PRE_EXISTING_BUG")
HARD_FLAKY_FOLDERS = hard_folders_of_kind("FLAKY_REALISTIC")


@pytest.mark.parametrize("folder", OUTDATED_FOLDERS,
                         ids=case_names(OUTDATED_FOLDERS))
def test_an_outdated_case_passes_before_and_fails_after(folder):
    """The older test worked, and only stops working once the code changes."""
    assert read_expected(folder)["label"] == "BAD_TEST"

    for row in results_for(folder):
        assert row["before"] == tr.PASSED, \
            f"{folder.name}: it has to pass on the old code"
        assert row["after"] in (tr.FAILED, tr.TEST_ERROR), \
            f"{folder.name}: it has to fail on the new code"


@pytest.mark.parametrize("folder", PRE_EXISTING_FOLDERS,
                         ids=case_names(PRE_EXISTING_FOLDERS))
def test_a_pre_existing_case_fails_on_both_sides(folder):
    """The problem is in the code on both versions, so both runs fail."""
    assert read_expected(folder)["label"] == "REAL_BUG"

    for row in results_for(folder):
        assert row["before"] in (tr.FAILED, tr.TEST_ERROR), \
            f"{folder.name}: it has to fail on the old code as well"
        assert row["after"] in (tr.FAILED, tr.TEST_ERROR), \
            f"{folder.name}: it has to fail on the new code as well"


@pytest.mark.parametrize("folder", HARD_FLAKY_FOLDERS,
                         ids=case_names(HARD_FLAKY_FOLDERS))
def test_a_hard_flaky_case_is_mixed_across_twelve_reruns(folder):
    """Twelve reruns, and it still has to come out mixed.

    Set ordering comes out roughly half and half, so twelve runs come out all one
    way about one time in a thousand. If this ever fails, the case has stopped
    being a fair test and the words it uses need changing.
    """
    assert read_expected(folder)["label"] == "FLAKY"

    result = tr.rerun_failures(folder / "after.py",
                               folder / "test_case.py",
                               times=HARD_CASE_RERUN_TIMES)

    assert result["tests"], f"{folder.name}: no tests came back from the reruns"
    for name, row in result["tests"].items():
        assert row["passes"] and row["fails"], (
            f"{folder.name}: {name} gave {row['passes']} passes and "
            f"{row['fails']} fails over {HARD_CASE_RERUN_TIMES} reruns")


@pytest.mark.parametrize("folder", HARD_FLAKY_FOLDERS,
                         ids=case_names(HARD_FLAKY_FOLDERS))
def test_a_hard_flaky_case_is_mixed_across_twenty_reruns(folder):
    """The same check with twenty runs, which makes it near certain."""
    result = tr.rerun_failures(folder / "after.py",
                               folder / "test_case.py",
                               times=PROOF_RERUN_TIMES)

    assert result["tests"], f"{folder.name}: no tests came back from the reruns"
    for name, row in result["tests"].items():
        assert row["passes"] and row["fails"], (
            f"{folder.name}: {name} gave {row['passes']} passes and "
            f"{row['fails']} fails over {PROOF_RERUN_TIMES} reruns")


@pytest.mark.parametrize("folder", HARD_FLAKY_FOLDERS,
                         ids=case_names(HARD_FLAKY_FOLDERS))
def test_a_hard_flaky_case_does_not_read_the_rerun_number(folder):
    """The old flaky cases read PRSENTINEL_RUN_INDEX. These must not.

    That number is ours, not the test's, and a test that reads it is not
    behaving the way a real test would.
    """
    text = (folder / "test_case.py").read_text(encoding="utf-8")
    assert "PRSENTINEL_RUN_INDEX" not in text, \
        f"{folder.name}: must not read the rerun number"
    assert "RUN_INDEX" not in text, \
        f"{folder.name}: must not mention the rerun number at all"


@pytest.mark.parametrize("folder", HARD_FOLDERS, ids=case_names(HARD_FOLDERS))
def test_no_hard_case_file_gives_the_answer_away(folder):
    """No file the AI is shown may name the kind of case it is.

    A docstring saying "this is flaky" tells the AI the answer before it has
    read anything, so the whole case would measure nothing. The answer key is
    the only file not scanned, because it holds the answer by definition and is
    never shown to a classifier.
    """
    assert_no_giveaway_words(folder)


def assert_no_giveaway_words(folder):
    """Fail if any file the AI is shown names the kind of case it is."""
    for filename in SCANNED_FILES:
        text = (folder / filename).read_text(encoding="utf-8").lower()
        found = [word for word in GIVEAWAY_WORDS if word in text]
        assert found == [], \
            f"{folder.name}/{filename} gives the answer away: {found}"


@pytest.mark.parametrize("folder", HARD_FOLDERS, ids=case_names(HARD_FOLDERS))
def test_a_hard_case_has_all_five_files(folder):
    """The four we always had, plus the description the intent mode reads."""
    for filename in ("before.py", "after.py", "test_case.py", "expected.json",
                     "description.txt"):
        assert (folder / filename).is_file(), \
            f"{folder.name} is missing {filename}"


def test_every_outdated_description_says_it_was_on_purpose():
    """The description is the only signal that a change was deliberate.

    Two of the three are in the tuning set and one is kept back, and all three
    need it, because the full_with_intent mode gets nothing else to go on.
    """
    folders = OUTDATED_FOLDERS + heldback_of_kind("OUTDATED_TEST")

    assert len(folders) == 3
    for folder in folders:
        text = (folder / "description.txt").read_text(encoding="utf-8")
        assert "purpose" in text.lower(), \
            f"{folder.name}: the description should say this was on purpose"


def heldback_of_kind(kind):
    """Return only the kept-back cases that record the given kind."""
    return [folder for folder in HELDBACK_FOLDERS
            if read_expected(folder)["kind"] == kind]


# ---------------------------------------------------------------------------
# The kept-back set
# ---------------------------------------------------------------------------

HELDBACK_FOLDERS = sorted(path for path in HELDBACK_FOLDER.iterdir()
                          if path.is_dir())


def test_there_are_four_kept_back_cases():
    """We said four, one of each kind plus a second flaky one."""
    assert len(HELDBACK_FOLDERS) == 4
    kinds = sorted(json.loads((folder / "expected.json")
                              .read_text(encoding="utf-8"))["kind"]
                   for folder in HELDBACK_FOLDERS)
    assert kinds == sorted(["OUTDATED_TEST", "PRE_EXISTING_BUG",
                            "FLAKY_REALISTIC", "FLAKY_REALISTIC"])


@pytest.mark.parametrize("folder", HELDBACK_FOLDERS,
                         ids=case_names(HELDBACK_FOLDERS))
def test_no_kept_back_case_file_gives_the_answer_away(folder):
    """The kept-back cases get the same check, so they measure something real.

    Reading the text of a kept-back file cannot leak a tuning answer. A
    giveaway word is just an ordinary English word, and knowing that a case's
    files are clean says nothing about which label it holds.
    """
    assert_no_giveaway_words(folder)


def test_no_kept_back_case_shares_a_module_with_a_tuning_case():
    """A shared before.py would carry the answer across the line.

    This file only compares the text, it never scores anything, so reading the
    kept-back module text cannot leak a tuning answer. It does mean this test
    has seen the kept-back modules, which is why nothing here uses them.
    """
    tuning = {}
    for folder in case_folders():
        for filename in ("before.py", "after.py"):
            text = (folder / filename).read_text(encoding="utf-8")
            tuning.setdefault(text, []).append(f"{folder.name}/{filename}")

    for folder in HELDBACK_FOLDERS:
        for filename in ("before.py", "after.py"):
            text = (folder / filename).read_text(encoding="utf-8")
            assert text not in tuning, \
                f"{folder.name}/{filename} is the same text as a tuning case"


def test_the_split_file_exists_and_lists_every_case():
    """SPLIT.md is the record of the split, and it has to be complete."""
    split = Path(__file__).resolve().parent.parent / "SPLIT.md"
    assert split.is_file(), "SPLIT.md is missing"

    text = split.read_text(encoding="utf-8")
    for folder in case_folders():
        assert folder.name in text, f"{folder.name} is not in SPLIT.md"
    for folder in HELDBACK_FOLDERS:
        assert folder.name in text, f"{folder.name} is not in SPLIT.md"


def test_every_new_case_is_in_exactly_one_of_the_two_folders():
    """No case may sit in both folders, or it would be scored twice."""
    tuning_names = {folder.name for folder in case_folders()}
    heldback_names = {folder.name for folder in HELDBACK_FOLDERS}
    both = tuning_names & heldback_names
    assert both == set(), f"these cases are in both folders: {both}"
