"""Run the whole thing with one command.

    python -m prsentinel.pipeline before.py after.py
    python -m prsentinel.pipeline before.py after.py --name my_run
    python -m prsentinel.pipeline before.py after.py --ai-second-opinion
    python -m prsentinel.pipeline before.py after.py --reuse-tests

The steps, in order:

1. Look at the two versions of the module and find the functions that were
   added or changed. Functions that were removed are skipped, because there is
   nothing left to test.
2. Ask the AI to write tests for each of those functions, and save them under
   generated_tests/<name>/.
3. Run each generated test file against both versions of the module, and label
   every test.
4. For every test that fails on the new code, work out whether it is pointing
   at a real bug, is itself wrong, or cannot be trusted. This uses the plain
   rule classifier, which needs no AI.
5. Only if --ai-second-opinion is given, also ask the AI for its opinion on each
   failing test, and flag it when the two disagree. Without that flag this
   step makes no calls at all.
6. Print a report in plain words. The report says whether the tests were freshly
   generated or reused, so a saved report always says where its tests came from.
7. Save the same report to reports/<name>.md and reports/<name>.json.

Two flags change what happens:

--ai-second-opinion   also ask the AI about each failing test, and say when it
                      disagrees with the rule. Without it, no extra AI call is
                      made at all.
--reuse-tests         do not ask the AI for any new tests. Run the test files
                      already saved in generated_tests/<name>/. With this flag
                      the whole run makes no AI calls, so the same tests can be
                      run again and compared.

One function failing does not stop the others. A failure to write a test, or a
failure to read one, is recorded and carried on from.

An older copy of a test file is never overwritten. The first is kept as .bak,
the next as .bak.2, then .bak.3, and so on.

The exit code is 0 whenever the pipeline itself ran, even when it found bugs,
because finding bugs is the job. It is non-zero only when the pipeline could
not do its work at all.

Nothing here ever writes an API key or any other secret. The report holds
results only.
"""

import argparse
import json
import shutil
from pathlib import Path

from prsentinel import classifier as cl
from prsentinel import test_generator as tg
from prsentinel import test_runner as tr
from prsentinel.diff_extractor import extract_changes_from_files

# Where generated tests and reports are kept.
GENERATED_DIR = "generated_tests"
REPORTS_DIR = "reports"

# The file extension used when we keep an older copy of a generated test.
BACKUP_SUFFIX = ".bak"

# The counts we show for each function, in this order.
COUNT_LABELS = (tr.CATCHES_CHANGE, tr.TEST_WRONG_ON_BEFORE, tr.NO_SIGNAL, tr.ODD)


# ---------------------------------------------------------------------------
# Step 2: writing the test files
# ---------------------------------------------------------------------------

def free_backup_path(path: Path) -> Path:
    """Find a backup name that is not taken yet.

    The first backup is called test_x.py.bak, the next one test_x.py.bak.2, then
    test_x.py.bak.3, and so on. We never write over an existing backup, because
    doing that is how an earlier version gets lost for good.
    """
    first = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if not first.exists():
        return first

    number = 2
    while True:
        numbered = first.with_name(first.name + f".{number}")
        if not numbered.exists():
            return numbered
        number += 1


def write_with_backup(path: Path, code: str):
    """Write a generated test file, keeping any older copy as a backup.

    Returns a pair: the backup path, or None if there was nothing to keep, and
    True if a backup was made. Nothing is ever deleted or overwritten.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    backup = None
    if path.is_file():
        backup = free_backup_path(path)
        shutil.copyfile(path, backup)

    path.write_text(code, encoding="utf-8")
    return backup, backup is not None


def reuse_test_files(before_file, after_file, name) -> list:
    """Use the test files already in generated_tests/<name>/, and ask nobody.

    This makes no call to any AI at all. It is what --reuse-tests does, so the
    same tests can be run again and the results compared.

    Returns the same shape of list as generate_test_files. A function we have
    no test file for is recorded as a failure, so it shows up in the report.
    """
    changes = extract_changes_from_files(before_file, after_file)
    folder = Path(GENERATED_DIR) / name
    outcomes = []

    for change in changes:
        function = change["name"]
        change_type = change["change_type"]

        if change_type not in tg.WANTED_CHANGE_TYPES:
            outcomes.append({"function": function, "change_type": change_type,
                             "path": None, "error": "",
                             "skipped": True, "backed_up": False,
                             "backup": ""})
            continue

        path = folder / f"test_{tg.safe_file_name(function)}.py"
        if not path.is_file():
            print(f"[prsentinel] no saved test for {function} at {path}")
            outcomes.append({"function": function, "change_type": change_type,
                             "path": None,
                             "error": "there is no saved test file to reuse",
                             "skipped": False, "backed_up": False,
                             "backup": ""})
            continue

        print(f"[prsentinel] reusing the saved test for {function}: {path}")
        outcomes.append({"function": function, "change_type": change_type,
                         "path": str(path), "error": "",
                         "skipped": False, "backed_up": False, "backup": ""})

    return outcomes


def generate_test_files(before_file, after_file, name) -> list:
    """Write one test file per changed function. Uses the AI.

    Returns a list of dictionaries, one per function we tried. Each has
    "function", "path" (None if it failed) and "error" ("" if it worked).
    A failure here does not stop the next function.
    """
    changes = extract_changes_from_files(before_file, after_file)
    folder = Path(GENERATED_DIR) / name
    outcomes = []

    for change in changes:
        function = change["name"]
        change_type = change["change_type"]

        # Only added or changed functions are worth testing. A removed
        # function has nothing left to call.
        if change_type not in tg.WANTED_CHANGE_TYPES:
            print(f"[prsentinel] skipping {function}: it was {change_type}, "
                  f"not added or changed.")
            outcomes.append({"function": function, "change_type": change_type,
                             "path": None, "error": "",
                             "skipped": True, "backed_up": False})
            continue

        print(f"[prsentinel] asking for tests for {function} ({change_type})...")
        try:
            code = tg.generate_tests(change)
        except Exception as error:
            # One function failing must not lose us the others.
            print(f"[prsentinel] could not write tests for {function}: {error}")
            outcomes.append({"function": function, "change_type": change_type,
                             "path": None, "error": str(error),
                             "skipped": False, "backed_up": False})
            continue

        path = folder / f"test_{tg.safe_file_name(function)}.py"
        backup, kept_old = write_with_backup(path, code)

        if backup is not None:
            print(f"[prsentinel] kept the old copy as {backup.name}")
        print(f"[prsentinel] saved {path}")

        outcomes.append({
            "function": function,
            "change_type": change_type,
            "path": str(path),
            "error": "",
            "skipped": False,
            "backed_up": kept_old,
            "backup": backup.name if backup else "",
        })

    return outcomes


# ---------------------------------------------------------------------------
# Steps 3 to 5: running the tests and judging the failures
# ---------------------------------------------------------------------------

def run_all_three(before_file, after_file, test_file):
    """Run a test file on both versions and then rerun it on the new one.

    This is done once per test file, not once per test, because every test in
    the file shares the same three runs. Running them again for each test would
    mean starting pytest over and over for no new information.

    Returns the three runs, in the order before, after, rerun.
    """
    before_run = tr.run_tests(before_file, test_file)
    after_run = tr.run_tests(after_file, test_file)
    rerun_run = tr.rerun_failures(after_file, test_file)
    return before_run, after_run, rerun_run


def judge_one_test(before_run, after_run, rerun_run,
                   before_file, after_file, test_file, test_name,
                   label="", ai_second_opinion=False) -> dict:
    """Work out what one failing test means.

    Takes runs that have already happened, so nothing is run again here. The
    rule classifier does the deciding. If asked, the AI is asked for a second
    opinion and any disagreement is recorded.

    label is the runner's own label for this test. It is only carried along so
    the report can say what kind of test this was.
    """
    evidence = cl.build_evidence(before_run, after_run, rerun_run,
                                 before_file, after_file, test_file,
                                 test_name=test_name)

    verdict = cl.rule_classify(evidence)
    result = {
        "test": test_name,
        "label": label,
        "verdict": verdict["label"],
        "reason": verdict["reason"],
        "before": evidence["before_result"],
        "after": evidence["after_result"],
        "rerun": evidence["rerun"],
    }

    if ai_second_opinion:
        # Only reached when the flag is on. Without it there is no extra call.
        second = cl.llm_classify(evidence, cl.MODE_FULL)
        result["ai_verdict"] = second["label"]
        result["ai_confidence"] = second["confidence"]
        result["ai_reason"] = second["reason"]
        result["ai_agrees"] = (second["label"] == verdict["label"])
    else:
        result["ai_verdict"] = ""
        result["ai_confidence"] = ""
        result["ai_reason"] = ""
        result["ai_agrees"] = None

    return result


def unknown_judgement(row, error):
    """A placeholder for a test we could not work out, so we still list it."""
    return {
        "test": row["name"],
        "label": row["label"],
        "verdict": "UNKNOWN",
        "reason": f"we could not work this out: {error}",
        "before": row["before"],
        "after": row["after"],
        "rerun": {},
        "ai_verdict": "",
        "ai_confidence": "",
        "ai_reason": "",
        "ai_agrees": None,
    }


def check_one_file(before_file, after_file, test_file,
                   ai_second_opinion=False) -> dict:
    """Run one generated test file on both versions and judge the failures."""
    rows = tr.evaluate_tests(before_file, after_file, test_file)

    counts = {label: 0 for label in COUNT_LABELS}
    for row in rows:
        counts[row["label"]] = counts.get(row["label"], 0) + 1

    # Two kinds of test are worth judging.
    #
    # A test that fails on the new code, because something about the change
    # matters to it. That includes every TEST_WRONG_ON_BEFORE row, which by
    # definition fails on the new code too, and which we still want a verdict
    # on so we can say plainly that the test itself is the problem.
    #
    # A test that fails on the old code and passes on the new one is ODD. We do
    # not judge it, we just point at it, because a rule cannot tell whether the
    # test is wrong or the change simply added behaviour.
    to_judge = [row for row in rows
                if row["after"] in (tr.FAILED, tr.TEST_ERROR)
                or row["label"] == tr.TEST_WRONG_ON_BEFORE]
    odd = [row for row in rows if row["label"] == tr.ODD]

    judgements = []

    if to_judge:
        # One set of runs, shared by every test in this file.
        before_run, after_run, rerun_run = run_all_three(before_file,
                                                        after_file,
                                                        test_file)
        for row in to_judge:
            print(f"[prsentinel] judging {row['display']}...")
            try:
                judgements.append(
                    judge_one_test(before_run, after_run, rerun_run,
                                   before_file, after_file, test_file,
                                   row["name"], label=row["label"],
                                   ai_second_opinion=ai_second_opinion))
            except Exception as error:
                # A judgement we cannot make is worth reporting, not worth
                # crashing the whole run over.
                print(f"[prsentinel] could not judge {row['display']}: {error}")
                judgements.append(unknown_judgement(row, error))

    return {
        "test_file": Path(test_file).name,
        "counts": counts,
        "judgements": judgements,
        "needs_a_look": [row["name"] for row in odd],
    }


def check_all_files(before_file, after_file, outcomes, ai_second_opinion) -> list:
    """Run every generated test file we managed to write."""
    results = []
    for outcome in outcomes:
        if outcome["path"] is None:
            continue
        results.append(check_one_file(before_file, after_file, outcome["path"],
                                      ai_second_opinion))
    return results


# ---------------------------------------------------------------------------
# Step 6: the report
# ---------------------------------------------------------------------------

def build_summary_line(report: dict) -> str:
    """Write the one plain sentence that says what we found.

    Only tests that caught the change AND were judged a real bug are counted,
    because a test that was itself wrong is not evidence of a bug.
    """
    parts = []
    for function in report["functions"]:
        # Counted row by row, not per function, so only a test that both caught
        # the change and was judged a real bug is counted. A test that was
        # itself wrong is not evidence of a bug.
        real_bugs = sum(1 for judgement in function["judgements"]
                        if judgement["label"] == tr.CATCHES_CHANGE
                        and judgement["verdict"] == cl.REAL_BUG)
        if real_bugs == 0:
            continue

        name = function["function"]
        if real_bugs == 1:
            parts.append(f"1 test points to a real bug in {name}")
        else:
            parts.append(f"{real_bugs} tests point to a real bug in {name}")

    if not parts:
        return "No test points to a real bug in the code."

    sentence = "; ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def make_report(before_file, after_file, name, outcomes, results,
                tests_source="generated") -> dict:
    """Put everything we found into one dictionary, ready to save."""
    functions = []
    for outcome, result in zip([o for o in outcomes if o["path"]],
                               results):
        functions.append({
            "function": outcome["function"],
            "change_type": outcome["change_type"],
            "test_file": result["test_file"],
            "counts": result["counts"],
            "judgements": result["judgements"],
            "needs_a_look": result["needs_a_look"],
        })

    report = {
        "name": name,
        "before": Path(before_file).name,
        "after": Path(after_file).name,
        "tests_source": tests_source,
        "functions": functions,
        "generation_failed": [
            {"function": o["function"], "error": o["error"]}
            for o in outcomes if o["path"] is None and not o["skipped"]
        ],
        "skipped": [
            {"function": o["function"], "change_type": o["change_type"]}
            for o in outcomes if o["skipped"]
        ],
    }
    report["summary"] = build_summary_line(report)
    return report


def format_report(report: dict) -> str:
    """Write the whole report out in plain words, for the screen."""
    lines = []
    lines.append("=" * 72)
    lines.append(f"PRSentinel report for {report['name']}")
    lines.append("=" * 72)
    lines.append(f"Old file: {report['before']}")
    lines.append(f"New file: {report['after']}")
    lines.append(f"Tests: {report.get('tests_source', 'generated')} "
                 f"in generated_tests/{report['name']}/")
    lines.append("")

    if not report["functions"]:
        lines.append("No test files were produced, so there is nothing to report.")
        lines.append("")
        return "\n".join(lines)

    lines.append("--- Per function ---")
    for function in report["functions"]:
        lines.append("")
        lines.append(f"{function['function']}  ({function['change_type']})")
        lines.append(f"  test file: {function['test_file']}")
        for label in COUNT_LABELS:
            lines.append(f"  {label:<24} {function['counts'].get(label, 0)}")

        if not function["judgements"] and not function["needs_a_look"]:
            lines.append("  No test failed on the new code, so there is "
                         "nothing to judge.")
            continue

        if function["judgements"]:
            lines.append("  Tests we judged:")
            for judgement in function["judgements"]:
                lines.append(f"    {judgement['test']}  "
                             f"({judgement['label']})")
                lines.append(f"      verdict : {judgement['verdict']}")
                lines.append(f"      why     : {judgement['reason']}")

                if judgement["ai_verdict"]:
                    mark = "agrees" if judgement["ai_agrees"] else "DISAGREES"
                    lines.append(f"      AI says : {judgement['ai_verdict']} "
                                 f"({judgement['ai_confidence']}) - {mark}")
                    lines.append(f"                {judgement['ai_reason']}")

        if function["needs_a_look"]:
            lines.append("  Tests that need a human look:")
            for name in function["needs_a_look"]:
                lines.append(f"    {name} - needs a human look "
                             "(fails on the old code, passes on the new one)")

    if report["generation_failed"]:
        lines.append("")
        lines.append("--- Functions we could not write tests for ---")
        for item in report["generation_failed"]:
            lines.append(f"  {item['function']}: {item['error']}")

    if report["skipped"]:
        lines.append("")
        lines.append("--- Functions we skipped ---")
        for item in report["skipped"]:
            lines.append(f"  {item['function']}: {item['change_type']}")

    lines.append("")
    lines.append("--- Summary ---")
    lines.append(report["summary"])
    return "\n".join(lines)


def print_report(report: dict) -> None:
    """Print the report, with a blank line either side."""
    print()
    print(format_report(report))


# ---------------------------------------------------------------------------
# Step 7: saving
# ---------------------------------------------------------------------------

def save_report(report: dict, reports_dir: str = REPORTS_DIR) -> dict:
    """Write the report to reports/<name>.md and reports/<name>.json.

    Returns the two paths. Nothing secret is ever written, because the report
    only holds results and names.
    """
    folder = Path(reports_dir)
    folder.mkdir(parents=True, exist_ok=True)

    markdown_path = folder / f"{report['name']}.md"
    json_path = folder / f"{report['name']}.json"

    markdown_path.write_text(format_report(report) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return {"markdown": str(markdown_path), "json": str(json_path)}


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def run_pipeline(before_file, after_file, name=None,
                 ai_second_opinion=False, reuse_tests=False) -> dict:
    """Do all seven steps and return the report.

    With reuse_tests we skip writing tests and use the ones already saved. That
    makes no call to any AI. The report says which of the two happened, so a
    saved report always says where its tests came from.
    """
    before_path = Path(before_file)
    after_path = Path(after_file)

    if name is None:
        # The folder the old file sits in, which is how the examples are named.
        name = before_path.resolve().parent.name

    print(f"[prsentinel] pipeline for {name}")

    # Steps 1 and 2.
    if reuse_tests:
        print("[prsentinel] --reuse-tests was given, so no AI is asked for "
              "new tests. Using the saved ones.")
        outcomes = reuse_test_files(before_path, after_path, name)
    else:
        outcomes = generate_test_files(before_path, after_path, name)

    # Steps 3, 4 and 5.
    results = check_all_files(before_path, after_path, outcomes,
                              ai_second_opinion)

    # Step 6.
    report = make_report(before_path, after_path, name, outcomes, results,
                         tests_source=("reused" if reuse_tests else "generated"))
    print_report(report)

    # Step 7.
    saved = save_report(report)
    print()
    print(f"[prsentinel] saved the report to {saved['markdown']}")
    print(f"[prsentinel] saved the full data to {saved['json']}")

    return report


def main() -> int:
    """Let us run this from the terminal."""
    parser = argparse.ArgumentParser(
        description="Generate tests for a changed module, run them, and say "
                    "what they found.")
    parser.add_argument("before_file", help="path to the old version of the module")
    parser.add_argument("after_file", help="path to the new version of the module")
    parser.add_argument("--name", default=None,
                        help="folder name to use under generated_tests and "
                             "reports. Defaults to the folder the old file is in.")
    parser.add_argument("--ai-second-opinion", action="store_true",
                        help="also ask the AI what it thinks of each failing "
                             "test, and flag any disagreement with the rule")
    parser.add_argument("--reuse-tests", action="store_true",
                        help="do not ask the AI for new tests. Use the test "
                             "files already in generated_tests/<name>/, which "
                             "makes no AI calls at all.")
    args = parser.parse_args()

    for path in (args.before_file, args.after_file):
        if not Path(path).is_file():
            print(f"Cannot read that file: {path}")
            return 1

    try:
        run_pipeline(args.before_file, args.after_file, args.name,
                     args.ai_second_opinion, args.reuse_tests)
    except Exception as error:
        # The pipeline could not do its job, which is the one thing that is
        # worth a non-zero exit.
        print(f"[prsentinel] the pipeline broke: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
