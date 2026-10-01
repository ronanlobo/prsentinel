"""Measure how many faults in the changed function the tests really catch.

A "mutant" is a copy of one function with a single small deliberate fault in
it: "+ changed to -", "< changed to <=", "is None changed to is not None", "a
number changed to one more", and the same the other way round. We run the test
file against each mutant.

- If a test fails on the mutant, the mutant is "killed": the tests caught it.
  A test that fails by raising an exception counts as a kill.
- If every test still passes, the mutant "survived": the tests missed it.

Mutation score = killed / (killed + survived).

The score is a lower bound. Some mutants do not change what the code does (an
"equivalent mutant"), and no test could ever kill one of those, so a low score
can mean "weak tests" or just "the tests were never asked the right question".
The report says this out loud next to the number.

Three rules keep this safe and small:

1. Only the changed function is mutated, and only in the version the tests
   pass on (the old file). A survivor is then a weak test, not a broken one.
2. Every mutant is built and run in a throwaway temporary folder. Nothing is
   ever written into examples/ or generated_tests/.
3. A mutant that cannot run at all (a syntax or import failure), or that leaves
   the function exactly as it was, is counted on its own and kept out of the
   score. A test that fails by raising an exception is a kill.

The tests are run through the ordinary test runner, so they get the same
allow-listed child environment: no API key ever reaches a mutant.
"""

import ast
import copy
import shutil
import tempfile
import textwrap
from pathlib import Path

from prsentinel import config
from prsentinel import test_runner as tr

# Every fault we know how to make. Each direction is listed on its own so the
# report can name exactly what was changed. This list is fixed: widen it only on
# purpose, because every entry here changes what a score means.
KIND_LABELS = {
    "add_to_sub": "+ to -",
    "sub_to_add": "- to +",
    "lt_to_le": "< to <=",
    "le_to_lt": "<= to <",
    "gt_to_ge": "> to >=",
    "ge_to_gt": ">= to >",
    "true_to_false": "True to False",
    "false_to_true": "False to True",
    "eq_to_noteq": "== to !=",
    "noteq_to_eq": "!= to ==",
    "is_none_to_is_not_none": "is None to is not None",
    "is_not_none_to_is_none": "is not None to is None",
    "and_to_or": "and to or",
    "or_to_and": "or to and",
    "int_to_int_plus_one": "n to n + 1",
    "default_none_to_empty_list": "None default to []",
    "default_empty_list_to_none": "[] default to None",
    "return_to_none": "return expr to return None",
}

# The buckets a mutant can land in. Only KILLED and SURVIVED go into the score.
KILLED = "killed"
SURVIVED = "survived"
EQUIVALENT = "equivalent"
TIMED_OUT = "timed out"
COULD_NOT_RUN = "could not run"

# How each outcome is spelled in the per-operator tally.
BUCKET_KEYS = {
    KILLED: "killed",
    SURVIVED: "survived",
    EQUIVALENT: "equivalent",
    TIMED_OUT: "timed_out",
    COULD_NOT_RUN: "could_not_run",
}


def find_function(tree, dotted_name):
    """Find one function in a parsed module, or return None.

    The name can be dotted for a method, the same way the diff reader names
    them: "Cart.add_item" is the method add_item inside the class Cart.
    """
    node = tree
    for part in dotted_name.split("."):
        found = None
        for child in ast.iter_child_nodes(node):
            looks_like_a_function = isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            if looks_like_a_function and child.name == part:
                found = child
                break
        if found is None:
            return None
        node = found

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node
    return None


def _is_none(node) -> bool:
    """True when a tree node is the literal None."""
    return isinstance(node, ast.Constant) and node.value is None


def _is_empty_list(node) -> bool:
    """True when a tree node is an empty list literal, []."""
    return isinstance(node, ast.List) and not node.elts


def _comparison_point(op, node, index):
    """Name the fault for one comparison, or None if we leave it alone.

    "is None" is only worth changing when the other side really is the literal
    None. "a is b" is left alone, because changing it is a different question.
    """
    right = node.comparators[index]
    if isinstance(op, ast.Lt):
        return "lt_to_le"
    if isinstance(op, ast.LtE):
        return "le_to_lt"
    if isinstance(op, ast.Gt):
        return "gt_to_ge"
    if isinstance(op, ast.GtE):
        return "ge_to_gt"
    if isinstance(op, ast.Eq):
        return "eq_to_noteq"
    if isinstance(op, ast.NotEq):
        return "noteq_to_eq"
    if isinstance(op, ast.Is) and _is_none(right):
        return "is_none_to_is_not_none"
    if isinstance(op, ast.IsNot) and _is_none(right):
        return "is_not_none_to_is_none"
    return None


def find_mutation_points(function_node) -> list:
    """List the little faults we can make in one function, in a fixed order.

    Each point is a pair of (kind, target). The kind is the fault's name, and
    the target is the tree node to change. The order is fixed: the function's
    own parameter defaults first, then ast.walk over the body. The same
    function always offers the same list of mutants.

    Only the function's OWN parameter defaults are changed. A default on a
    nested function inside it is left alone, so the score stays about the
    changed function.
    """
    points = []

    # The function's own parameters. "None default to []" and "[] default to
    # None" only look at this function's signature, never a nested function's.
    for field in ("defaults", "kw_defaults"):
        for index, default in enumerate(getattr(function_node.args, field)):
            if default is None:
                continue
            if _is_none(default):
                points.append(("default_none_to_empty_list",
                               (function_node.args, field, index)))
            elif _is_empty_list(default):
                points.append(("default_empty_list_to_none",
                               (function_node.args, field, index)))

    for node in ast.walk(function_node):
        if isinstance(node, ast.BinOp):
            if isinstance(node.op, ast.Add):
                points.append(("add_to_sub", node))
            elif isinstance(node.op, ast.Sub):
                points.append(("sub_to_add", node))
        elif isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                points.append(("and_to_or", node))
            elif isinstance(node.op, ast.Or):
                points.append(("or_to_and", node))
        elif isinstance(node, ast.Compare):
            for index, op in enumerate(node.ops):
                kind = _comparison_point(op, node, index)
                if kind is not None:
                    points.append((kind, (node, index)))
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                if node.value:
                    points.append(("true_to_false", node))
                else:
                    points.append(("false_to_true", node))
            elif type(node.value) is int:
                points.append(("int_to_int_plus_one", node))
        elif isinstance(node, ast.Return):
            if node.value is not None and not _is_none(node.value):
                points.append(("return_to_none", node))
    return points


# The comparison operators and what each one swaps for.
COMPARE_SWAPS = {
    "lt_to_le": ast.LtE,
    "le_to_lt": ast.Lt,
    "gt_to_ge": ast.GtE,
    "ge_to_gt": ast.Gt,
    "eq_to_noteq": ast.NotEq,
    "noteq_to_eq": ast.Eq,
    "is_none_to_is_not_none": ast.IsNot,
    "is_not_none_to_is_none": ast.Is,
}


def apply_mutation(target, kind) -> None:
    """Change one node in place to make one small fault."""
    if kind == "add_to_sub":
        target.op = ast.Sub()
    elif kind == "sub_to_add":
        target.op = ast.Add()
    elif kind == "and_to_or":
        target.op = ast.Or()
    elif kind == "or_to_and":
        target.op = ast.And()
    elif kind in COMPARE_SWAPS:
        node, index = target
        node.ops[index] = COMPARE_SWAPS[kind]()
    elif kind == "true_to_false":
        target.value = False
    elif kind == "false_to_true":
        target.value = True
    elif kind == "int_to_int_plus_one":
        target.value = target.value + 1
    elif kind == "default_none_to_empty_list":
        arguments, field, index = target
        getattr(arguments, field)[index] = ast.List(elts=[], ctx=ast.Load())
    elif kind == "default_empty_list_to_none":
        arguments, field, index = target
        getattr(arguments, field)[index] = ast.Constant(value=None)
    elif kind == "return_to_none":
        target.value = ast.Constant(value=None)


def operator_lines(width=66) -> list:
    """The names of every fault we try, wrapped so the report reads well."""
    names = ", ".join(KIND_LABELS.values())
    return textwrap.wrap(names, width=width)


def rebuild(code: str) -> str:
    """Turn code back into plain text, dropping comments and blank lines.

    Mutants are made by rewriting the tree, so the tests are also run against a
    plain rebuild of the unchanged file. Then the only difference between the
    two runs is the fault, and not a change in how the file was written.
    """
    return ast.unparse(ast.parse(code))


def build_mutants(code, function_name, limit=None) -> dict:
    """Make the mutants for one function inside a block of code.

    Returns the number of faults found, whether the cap cut the list, and the
    mutants themselves. Each mutant carries its operator name, its rebuilt
    source, and whether it left the function exactly as it was.
    """
    if limit is None:
        limit = config.MAX_MUTANTS_PER_FUNCTION

    tree = ast.parse(code)
    function_node = find_function(tree, function_name)
    if function_node is None:
        return {"found": 0, "capped": False, "cap": limit, "mutants": []}

    points = find_mutation_points(function_node)
    found = len(points)
    capped = found > limit
    chosen = points[:limit]

    original_dump = ast.dump(function_node)
    mutants = []
    for index, (kind, _) in enumerate(chosen):
        mutant_tree = copy.deepcopy(tree)
        mutant_function = find_function(mutant_tree, function_name)
        # The copy has the same shape, so the fault at the same place in the
        # list is the same fault.
        mutant_target = find_mutation_points(mutant_function)[index][1]
        apply_mutation(mutant_target, kind)
        mutants.append({
            "operator": KIND_LABELS[kind],
            "source": ast.unparse(mutant_tree),
            "identical": ast.dump(mutant_function) == original_dump,
        })

    return {"found": found, "capped": capped, "cap": limit, "mutants": mutants}


def baseline_problem(baseline: dict) -> str:
    """Say why the un-mutated run cannot be a starting point, or return "".

    A mutation score only means something if the tests pass to begin with. If
    they already fail, there is nothing to measure from, so we say so instead
    of counting every mutant as killed.
    """
    if baseline["status"] == tr.TIMEOUT:
        return ("the tests took too long on the un-mutated code, so there is "
                "no green starting point")
    if baseline["status"] == tr.ERROR:
        return (f"the tests could not run on the un-mutated code "
                f"({baseline['error']})")
    for result in baseline["tests"].values():
        if result in (tr.FAILED, tr.TEST_ERROR):
            return ("the tests already fail on the un-mutated code, so there "
                    "is no green starting point")
    return ""


def classify_run(run: dict):
    """Say what one mutant did, and which tests killed it."""
    if run["status"] == tr.TIMEOUT:
        return TIMED_OUT, []
    if run["status"] == tr.ERROR:
        return COULD_NOT_RUN, []

    killed_by = [name for name, result in run["tests"].items()
                 if result in (tr.FAILED, tr.TEST_ERROR)]
    if killed_by:
        return KILLED, killed_by
    return SURVIVED, []


def run_mutation(before_file, test_file, function_name, mutants=None,
                 timeout_seconds=None, limit=None) -> dict:
    """Run the test file against every mutant of one function.

    before_file is the version the tests pass on. Only that one function is
    changed. Returns a dictionary with the counts, the score, and which tests
    killed what.

    mutants is only for tests: when it is given, that fixed list is used
    instead of building one, so a test can put an exact case in front of it.
    """
    if timeout_seconds is None:
        timeout_seconds = config.MUTATION_TIMEOUT_SECONDS

    code = Path(before_file).read_text(encoding="utf-8")
    plain_source = rebuild(code)

    if mutants is None:
        built = build_mutants(code, function_name, limit=limit)
        mutants = built["mutants"]
        found = built["found"]
        capped = built["capped"]
        cap = built["cap"]
    else:
        found = len(mutants)
        capped = False
        cap = limit if limit is not None else config.MAX_MUTANTS_PER_FUNCTION

    result = {
        "function": function_name,
        "version": Path(before_file).name,
        "found": found,
        "cap": cap,
        "capped": capped,
        "defined": False,
        "reason": "",
        "killed": 0,
        "survived": 0,
        "equivalent": 0,
        "timed_out": 0,
        "could_not_run": 0,
        "score": None,
        "operators": [],
        "operator_totals": [],
        "tests": [],
    }

    work_dir = Path(tempfile.mkdtemp(prefix="prsentinel_mutation_"))
    try:
        # The plain rebuild, unchanged, must pass every test. If it does not,
        # there is no green starting point and we do not run a single mutant.
        baseline_file = work_dir / "plain.py"
        baseline_file.write_text(plain_source, encoding="utf-8")
        baseline = tr.run_tests(baseline_file, test_file,
                                timeout_seconds=timeout_seconds)

        problem = baseline_problem(baseline)
        if problem:
            result["reason"] = problem
            return result

        result["defined"] = True
        test_names = list(baseline["tests"].keys())
        kills = {name: 0 for name in test_names}

        # Count kills per operator name, so the report can say which kinds of
        # fault the tests catch and which they miss.
        totals = {}

        def note(operator, outcome):
            row = totals.setdefault(operator, {
                "killed": 0, "survived": 0, "equivalent": 0,
                "timed_out": 0, "could_not_run": 0,
            })
            row[BUCKET_KEYS[outcome]] += 1

        for number, mutant in enumerate(mutants, start=1):
            if mutant["identical"]:
                result["equivalent"] += 1
                result["operators"].append({
                    "operator": mutant["operator"],
                    "outcome": EQUIVALENT,
                    "killed_by": [],
                })
                note(mutant["operator"], EQUIVALENT)
                continue

            mutant_file = work_dir / f"mutant_{number}.py"
            mutant_file.write_text(mutant["source"], encoding="utf-8")
            run = tr.run_tests(mutant_file, test_file,
                               timeout_seconds=timeout_seconds)

            outcome, killed_by = classify_run(run)
            result["operators"].append({
                "operator": mutant["operator"],
                "outcome": outcome,
                "killed_by": killed_by,
            })
            note(mutant["operator"], outcome)

            if outcome == KILLED:
                result["killed"] += 1
                for name in killed_by:
                    kills[name] = kills.get(name, 0) + 1
            elif outcome == SURVIVED:
                result["survived"] += 1
            elif outcome == TIMED_OUT:
                result["timed_out"] += 1
            else:
                result["could_not_run"] += 1

        result["operator_totals"] = []
        for label in KIND_LABELS.values():
            if label in totals:
                row = {"operator": label}
                row.update(totals[label])
                result["operator_totals"].append(row)

        counted = result["killed"] + result["survived"]
        if counted:
            result["score"] = result["killed"] / counted
        else:
            result["reason"] = ("no mutant could be scored for this function")

        # A test that killed nothing is a possible dud, but only when some
        # mutant was actually scored. With nothing to score, every test would
        # look like a dud for no good reason.
        if counted:
            result["tests"] = [
                {"test": name, "kills": kills[name], "dud": kills[name] == 0}
                for name in test_names
            ]
        return result
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
