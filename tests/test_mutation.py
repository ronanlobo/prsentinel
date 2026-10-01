"""Tests for the mutation checker.

Everything here is hand written and tiny, and no AI is asked for anything. A
test writes a small module and a small test file into a temporary folder, then
asks the mutation checker what the tests catch.

The small module used below has two functions on purpose:

- add_one can be broken by "+ to -", and the tests catch that, so it is killed.
- is_big can be broken by "> to >=", and the tests miss that, so it survives.
"""

from prsentinel import mutation as mt
from prsentinel import pipeline as pl


MODULE = """
def add_one(n):
    return n + 1


def is_big(n):
    return n > 10
"""

GOOD_TESTS = """
from target import add_one, is_big


def test_add_one():
    assert add_one(2) == 3


def test_is_big():
    assert is_big(100) is True
"""

BAD_TESTS = """
from target import add_one


def test_wrong():
    assert add_one(2) == 999
"""

DUD_TESTS = """
from target import add_one


def test_kills_it():
    assert add_one(2) == 3


def test_touches_nothing():
    assert 1 + 1 == 2
"""

MANY_FAULTS = """
def many(n):
    a = n + 1
    b = n + 2
    c = n + 3
    return a - b - c
"""

PLAIN_MODULE = """
def label(value):
    return str(value)
"""

PLAIN_TESTS = """
from target import label


def test_label():
    assert label(3) == "3"
"""


def write_files(tmp_path, module_text, test_text):
    """Put a tiny module and its test file in a temporary folder."""
    module = tmp_path / "before.py"
    test = tmp_path / "test_small.py"
    module.write_text(module_text, encoding="utf-8")
    test.write_text(test_text, encoding="utf-8")
    return module, test


def one_function_report(mutation):
    """A report with a single changed function, for the section tests."""
    outcome = {
        "function": "add_one",
        "change_type": "modified",
        "path": "generated_tests/demo/test_add_one.py",
        "from_folder": "",
        "error": "",
        "skipped": False,
    }
    result = {
        "test_file": "test_add_one.py",
        "counts": {},
        "judgements": [],
        "needs_a_look": [],
    }
    return pl.make_report("before.py", "after.py", "demo", [outcome], [result],
                          mutation=mutation)


# ---------------------------------------------------------------------------
# One mutant killed
# ---------------------------------------------------------------------------

def test_a_mutant_the_tests_catch_is_killed(tmp_path):
    module, test = write_files(tmp_path, MODULE, GOOD_TESTS)
    result = mt.run_mutation(module, test, "add_one")
    assert result["defined"] is True
    assert result["found"] == 1
    assert result["killed"] == 1
    assert result["survived"] == 0
    assert result["score"] == 1.0


# ---------------------------------------------------------------------------
# One mutant survives
# ---------------------------------------------------------------------------

def test_a_mutant_the_tests_miss_survives(tmp_path):
    module, test = write_files(tmp_path, MODULE, GOOD_TESTS)
    result = mt.run_mutation(module, test, "is_big")
    assert result["defined"] is True
    assert result["found"] == 1
    assert result["killed"] == 0
    assert result["survived"] == 1
    assert result["score"] == 0.0


# ---------------------------------------------------------------------------
# One equivalent mutant (identical to the original)
# ---------------------------------------------------------------------------

def test_a_mutation_that_changes_nothing_is_counted_as_equivalent(tmp_path):
    module, test = write_files(tmp_path, MODULE, GOOD_TESTS)
    plain = mt.rebuild(MODULE)
    mutants = [{"operator": "no change", "source": plain, "identical": True}]
    result = mt.run_mutation(module, test, "add_one", mutants=mutants)
    assert result["defined"] is True
    assert result["equivalent"] == 1
    assert result["killed"] == 0
    assert result["survived"] == 0
    assert result["score"] is None


def test_a_real_mutant_is_not_marked_identical():
    built = mt.build_mutants(MODULE, "add_one")
    assert built["found"] == 1
    assert built["mutants"][0]["identical"] is False


# ---------------------------------------------------------------------------
# The score is not defined when the tests already fail
# ---------------------------------------------------------------------------

def test_tests_that_already_fail_mean_the_score_is_not_defined(tmp_path):
    module, test = write_files(tmp_path, MODULE, BAD_TESTS)
    result = mt.run_mutation(module, test, "add_one")
    assert result["defined"] is False
    assert result["score"] is None
    assert "un-mutated" in result["reason"]


# ---------------------------------------------------------------------------
# The cap
# ---------------------------------------------------------------------------

def test_the_cap_cuts_the_list_and_says_so():
    built = mt.build_mutants(MANY_FAULTS, "many", limit=2)
    assert built["found"] > 2
    assert built["capped"] is True
    assert len(built["mutants"]) == 2


# ---------------------------------------------------------------------------
# A test that killed nothing is a possible dud
# ---------------------------------------------------------------------------

def test_a_test_that_kills_nothing_is_flagged_as_a_dud(tmp_path):
    module, test = write_files(tmp_path, MODULE, DUD_TESTS)
    result = mt.run_mutation(module, test, "add_one")
    duds = {t["test"].split("::")[-1]: t["dud"] for t in result["tests"]}
    assert duds["test_touches_nothing"] is True
    assert duds["test_kills_it"] is False


def test_a_function_with_no_mutants_flags_no_duds(tmp_path):
    # label has none of the four operators in it, so there is nothing to
    # score. With nothing to score, no test should be called a dud.
    module, test = write_files(tmp_path, PLAIN_MODULE, PLAIN_TESTS)
    result = mt.run_mutation(module, test, "label")
    assert result["defined"] is True
    assert result["found"] == 0
    assert result["score"] is None
    assert result["tests"] == []


# ---------------------------------------------------------------------------
# Added and removed functions have no old version to mutate
# ---------------------------------------------------------------------------

def test_added_and_removed_functions_are_not_scored(tmp_path):
    outcomes = [
        {"function": "brand_new", "change_type": "added",
         "path": str(tmp_path / "nope.py")},
        {"function": "gone", "change_type": "removed", "path": None},
    ]
    results = pl.measure_mutation(tmp_path / "before.py", outcomes)
    assert results[0]["defined"] is False
    assert results[0]["reason"] == "not defined (no old version)"
    assert results[1]["defined"] is False
    assert results[1]["reason"] == "not defined (no old version)"


# ---------------------------------------------------------------------------
# The report only grows a mutation section when it is asked for
# ---------------------------------------------------------------------------

def test_an_ordinary_report_has_no_mutation_section():
    report = one_function_report(None)
    assert "mutation" not in report
    assert "Mutation" not in pl.format_report(report)


def test_the_report_shows_the_mutation_score_when_asked():
    entry = {
        "function": "add_one", "change_type": "modified",
        "defined": True, "version": "before.py",
        "found": 2, "cap": 30, "capped": False,
        "killed": 1, "survived": 1, "equivalent": 0,
        "timed_out": 0, "could_not_run": 0, "score": 0.5,
        "operators": [], "tests": [],
    }
    report = one_function_report([entry])
    assert report["mutation"] == [entry]
    text = pl.format_report(report)
    assert "--- Mutation" in text
    assert "50% (1 of 2)" in text
    assert "lower bound" in text


def test_a_function_with_no_old_version_reads_as_not_defined():
    entry = {
        "function": "brand_new", "change_type": "added",
        "defined": False, "reason": "not defined (no old version)",
    }
    report = one_function_report([entry])
    text = pl.format_report(report)
    assert "not defined (no old version)" in text
