"""Tests for the mutation checker.

Everything here is hand written and tiny, and no AI is asked for anything. A
test writes a small module and a small test file into a temporary folder, then
asks the mutation checker what the tests catch.

The small module used below has two functions on purpose:

- add_one can be broken by "+ to -", and the tests catch that, so it is killed.
- is_big can be broken by "> to >=", and the tests miss that, so it survives.

Because the operator set is wide now, most of these tests check the outcome of
one named operator rather than a raw total, so a later operator cannot quietly
break an older test.
"""

from prsentinel import mutation as mt
from prsentinel import pipeline as pl
from prsentinel import test_runner as tr


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

# A bare "return None" and nothing else, so there is nothing to mutate at all.
PLAIN_MODULE = """
def label(value):
    return None
"""

PLAIN_TESTS = """
from target import label


def test_label():
    assert label(3) is None
"""

# One tiny module per new operator, so each can be offered on its own.
EQUALS_MODULE = "def same(a, b):\n    return a == b\n"
NOTEQUALS_MODULE = "def differ(a, b):\n    return a != b\n"
IS_NONE_MODULE = "def blank(x):\n    return x is None\n"
IS_NOT_NONE_MODULE = "def solid(x):\n    return x is not None\n"
AND_MODULE = "def both(a, b):\n    return a and b\n"
OR_MODULE = "def either(a, b):\n    return a or b\n"
INDEX_MODULE = "def first(values):\n    return values[0]\n"
RETURN_MODULE = "def answer():\n    return 42\n"

# Default arguments. The first is a None default, the second a list default.
DEFAULT_NONE_MODULE = "def fill(item, bucket=None):\n    return bucket\n"
DEFAULT_LIST_MODULE = "def fill(item, bucket=[]):\n    return bucket\n"

# A default on a nested function, which we must leave alone.
NESTED_DEFAULT_MODULE = (
    "def outer(items):\n"
    "    def inner(bucket=None):\n"
    "        return bucket\n"
    "    return inner\n"
)

# "is" with something that is not None, which we must also leave alone.
PLAIN_IS_MODULE = "def same_object(a, b):\n    return a is b\n"


def write_files(tmp_path, module_text, test_text):
    """Put a tiny module and its test file in a temporary folder."""
    module = tmp_path / "before.py"
    test = tmp_path / "test_small.py"
    module.write_text(module_text, encoding="utf-8")
    test.write_text(test_text, encoding="utf-8")
    return module, test


def offered(code, function):
    """The operator names this function offers a fault for."""
    built = mt.build_mutants(code, function)
    return {m["operator"] for m in built["mutants"]}


def outcomes_of(result):
    """The outcome for each named operator, from a real run."""
    return {row["operator"]: row["outcome"] for row in result["operators"]}


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
    assert outcomes_of(result)["+ to -"] == mt.KILLED
    assert result["killed"] == result["found"]
    assert result["survived"] == 0


# ---------------------------------------------------------------------------
# One mutant survives
# ---------------------------------------------------------------------------

def test_a_mutant_the_tests_miss_survives(tmp_path):
    module, test = write_files(tmp_path, MODULE, GOOD_TESTS)
    result = mt.run_mutation(module, test, "is_big")
    assert result["defined"] is True
    assert outcomes_of(result)["> to >="] == mt.SURVIVED
    assert result["survived"] >= 1


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
    assert built["found"] == 3
    assert all(m["identical"] is False for m in built["mutants"])


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


def test_the_cap_cuts_the_wider_operator_set():
    # Three "+ to -", three "n to n + 1", two "- to +" and one "return".
    built = mt.build_mutants(MANY_FAULTS, "many", limit=3)
    assert built["found"] == 9
    assert built["capped"] is True
    assert len(built["mutants"]) == 3


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
# One mutant for each new operator
# ---------------------------------------------------------------------------

def test_equal_can_become_not_equal():
    assert "== to !=" in offered(EQUALS_MODULE, "same")


def test_not_equal_can_become_equal():
    assert "!= to ==" in offered(NOTEQUALS_MODULE, "differ")


def test_is_none_can_become_is_not_none():
    assert "is None to is not None" in offered(IS_NONE_MODULE, "blank")


def test_is_not_none_can_become_is_none():
    assert "is not None to is None" in offered(IS_NOT_NONE_MODULE, "solid")


def test_and_can_become_or():
    assert "and to or" in offered(AND_MODULE, "both")


def test_or_can_become_and():
    assert "or to and" in offered(OR_MODULE, "either")


def test_a_number_can_become_one_more():
    assert "n to n + 1" in offered(INDEX_MODULE, "first")


def test_return_expression_can_become_return_none():
    assert "return expr to return None" in offered(RETURN_MODULE, "answer")


# ---------------------------------------------------------------------------
# "is None" means the literal None, nothing else
# ---------------------------------------------------------------------------

def test_an_is_comparison_to_something_else_is_left_alone():
    names = offered(PLAIN_IS_MODULE, "same_object")
    assert "is None to is not None" not in names
    assert "is not None to is None" not in names


# ---------------------------------------------------------------------------
# Default arguments: the changed function's own, and both directions
# ---------------------------------------------------------------------------

def test_a_none_default_can_become_an_empty_list():
    assert "None default to []" in offered(DEFAULT_NONE_MODULE, "fill")


def test_an_empty_list_default_can_become_none():
    assert "[] default to None" in offered(DEFAULT_LIST_MODULE, "fill")


def test_a_nested_functions_default_is_left_alone():
    names = offered(NESTED_DEFAULT_MODULE, "outer")
    assert "None default to []" not in names


def test_the_none_default_mutant_runs_and_is_killed(tmp_path):
    module, test = write_files(
        tmp_path,
        DEFAULT_NONE_MODULE,
        "from target import fill\n\n\ndef test_default_is_none():\n"
        "    assert fill(1) is None\n",
    )
    result = mt.run_mutation(module, test, "fill")
    assert outcomes_of(result)["None default to []"] == mt.KILLED


def test_the_empty_list_default_mutant_runs_and_is_killed(tmp_path):
    module, test = write_files(
        tmp_path,
        DEFAULT_LIST_MODULE,
        "from target import fill\n\n\ndef test_default_is_a_list():\n"
        "    assert fill(1) == []\n",
    )
    result = mt.run_mutation(module, test, "fill")
    assert outcomes_of(result)["[] default to None"] == mt.KILLED


# ---------------------------------------------------------------------------
# A test that raises is a kill. Only an import failure is "could not run".
# ---------------------------------------------------------------------------

def test_a_test_that_raises_counts_as_killed(tmp_path):
    module, test = write_files(
        tmp_path,
        INDEX_MODULE,
        "from target import first\n\n\ndef test_first():\n"
        "    assert first([10]) == 10\n",
    )
    result = mt.run_mutation(module, test, "first")
    # values[0] becomes values[1], which raises IndexError. The mutant still
    # imported, so it is a kill and not a "could not run".
    assert outcomes_of(result)["n to n + 1"] == mt.KILLED
    assert result["could_not_run"] == 0


def test_an_import_failure_is_the_only_thing_called_could_not_run():
    run = {"status": tr.ERROR, "tests": {}, "error": "boom"}
    assert mt.classify_run(run) == (mt.COULD_NOT_RUN, [])


def test_a_test_that_errored_is_a_kill():
    run = {"status": tr.OK, "tests": {"test_small::test_a": tr.TEST_ERROR}}
    assert mt.classify_run(run) == (mt.KILLED, ["test_small::test_a"])


# ---------------------------------------------------------------------------
# Kills are counted per operator
# ---------------------------------------------------------------------------

def test_kills_are_counted_per_operator(tmp_path):
    module, test = write_files(tmp_path, MODULE, GOOD_TESTS)
    result = mt.run_mutation(module, test, "is_big")
    totals = {row["operator"]: row for row in result["operator_totals"]}
    assert totals["> to >="]["survived"] == 1
    assert totals["> to >="]["killed"] == 0
    assert totals["return expr to return None"]["killed"] == 1


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
        "operators": [], "operator_totals": [], "tests": [],
    }
    report = one_function_report([entry])
    assert report["mutation"] == [entry]
    text = pl.format_report(report)
    assert "--- Mutation" in text
    assert "50% (1 of 2)" in text
    assert "lower bound" in text
    assert "Operators tried" in text
    assert "== to !=" in text
    assert "return expr to return None" in text
    assert "can push the score up" in text


def test_the_report_shows_kills_per_operator():
    entry = {
        "function": "add_one", "change_type": "modified",
        "defined": True, "version": "before.py",
        "found": 2, "cap": 30, "capped": False,
        "killed": 1, "survived": 1, "equivalent": 0,
        "timed_out": 0, "could_not_run": 0, "score": 0.5,
        "operators": [],
        "operator_totals": [
            {"operator": "+ to -", "killed": 1, "survived": 0,
             "equivalent": 0, "timed_out": 0, "could_not_run": 0},
            {"operator": "n to n + 1", "killed": 0, "survived": 1,
             "equivalent": 0, "timed_out": 0, "could_not_run": 0},
        ],
        "tests": [],
    }
    report = one_function_report([entry])
    text = pl.format_report(report)
    assert "kills per operator" in text
    assert "+ to -" in text
    assert "n to n + 1" in text


def test_a_function_with_no_old_version_reads_as_not_defined():
    entry = {
        "function": "brand_new", "change_type": "added",
        "defined": False, "reason": "not defined (no old version)",
    }
    report = one_function_report([entry])
    text = pl.format_report(report)
    assert "not defined (no old version)" in text