r"""Run the existing pipeline on the three real bug cases, and print what it found.

Run it like this:

    .venv\Scripts\python.exe -u scripts\eval_real_cases.py

This script calls prsentinel.pipeline.run_pipeline, which is the very function
python -m prsentinel.pipeline calls, so a result here means what it would mean
there. It adds no steps of its own and changes nothing in the pipeline.

Two settings are fixed and cannot be changed from the command line, because they
are what makes a result mean anything:

  --no-fallback  llm_client.ALLOW_FALLBACK is set to False and the report is
                 told fallback_allowed=False. If Groq runs out for the day the
                 whole evaluation stops, prints the per-case line for each case
                 that finished, prints no final table at all, and exits 6.
                 Results made from part of one model and part of another are
                 not results.

  --mutation    mutation=True, so each changed function is also checked against
                 small deliberate faults to see how many the tests catch. This
                 asks no AI. The scores are in the report files and in the final
                 table.

There is deliberately no command line here at all. An evaluation run that can be
reconfigured by accident is not an evaluation run.

What the generator is allowed to see
------------------------------------
Only before.py and after.py, and only the one changed function's old and new
source. existing_test.py, witness.md and source.md are never passed to the
pipeline. existing_test.py is read once per case, and only AFTER run_pipeline has
returned, purely to print one comparison number for the reader. It cannot reach
the generator, because by the time it is read the generator has finished and
written its file. tests/test_real_cases.py checks both of those claims.

What the numbers mean
---------------------
"tests" counts pytest test items. One per test function, plus one per
parametrized case. A parametrized test with five cases counts as five, because
that is what pytest reports and what the runner labels. It is not a count of
files and not a count of functions.

"caught: yes" means at least one generated test carries the runner's
CATCHES_CHANGE label: it passes on before.py and fails on after.py. Next to it,
REAL_BUG is how many of those CATCHES_CHANGE tests were also judged to be
pointing at a real bug by the plain rule classifier, which needs no AI.

Where the reports go
--------------------
run_pipeline saves to reports/<case>.md and reports/<case>.json. This script then
moves both into reports/real_cases/. If either file is already there, the script
refuses, moves neither, and says so. Nothing is ever overwritten, so a second
live run needs the first run's reports moved or deleted first.

Nothing here ever prints or writes an API key.
"""

import importlib.util
import shutil
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

sys.path.insert(0, str(PROJECT / "src"))

from prsentinel import classifier as cl  # noqa: E402
from prsentinel import llm_client  # noqa: E402
from prsentinel import pipeline as pl  # noqa: E402
from prsentinel import test_runner as tr  # noqa: E402
from prsentinel.diff_extractor import extract_changes_from_files  # noqa: E402

# The exit code for a run that was refused before it could do its work. pipeline
# uses 2 for its own refusal (--repair with --reuse-tests), so this reuses the
# same number and the same meaning rather than inventing a new one.
EXIT_REFUSED = 2

RULE = "=" * 74


# ---------------------------------------------------------------------------
# check_real_cases.py, imported rather than copied
# ---------------------------------------------------------------------------
# The four-label verdict for a project's own test already exists in
# scripts/check_real_cases.py. It is imported instead of copied, because both
# scripts print a number about the same case and two copies of the same rule
# would eventually disagree. Importing also means the list of case folders and
# the list of required files are defined in exactly one place.

def load_check_script():
    """Import the sibling script, which is not a package member."""
    path = HERE / "check_real_cases.py"
    spec = importlib.util.spec_from_file_location("check_real_cases", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = load_check_script()


class RefusedRun(RuntimeError):
    """The run was refused before it could do its work."""


# ---------------------------------------------------------------------------
# Reading numbers out of what already happened. No AI, nothing run.
# ---------------------------------------------------------------------------

def count_changes(before_file, after_file) -> dict:
    """How many functions diff_extractor found, broken down by change type.

    Read straight from the two files rather than from the report, because the
    report only holds the functions that ended up with a test file. A removed
    function, or one whose test file could not be written, is still a function
    diff_extractor found. Costs no model call.
    """
    changes = extract_changes_from_files(before_file, after_file)

    counts = {"modified": 0, "added": 0, "removed": 0, "other": 0}
    for change in changes:
        kind = change["change_type"]
        if kind in counts:
            counts[kind] += 1
        else:
            counts["other"] += 1

    counts["total"] = len(changes)
    return counts


def read_report_numbers(report: dict) -> dict:
    """Pull the three counts we print out of a finished report.

    "tests" is pytest test items: one per test function, plus one per
    parametrized case.

    "real_bug" is counted out of the CATCHES_CHANGE tests, not out of all tests.
    Only a test that caught the change and was judged a real bug is evidence of
    a bug; a test that failed on both versions is a statement about the test.
    """
    tests = 0
    catches_change = 0
    real_bug = 0

    for function in report["functions"]:
        tests += sum(function["counts"].values())
        catches_change += function["counts"].get(tr.CATCHES_CHANGE, 0)
        for judgement in function["judgements"]:
            if (judgement["label"] == tr.CATCHES_CHANGE
                    and judgement["verdict"] == cl.REAL_BUG):
                real_bug += 1

    return {"tests": tests, "catches_change": catches_change,
            "real_bug": real_bug}


def caught_the_bug(numbers: dict) -> str:
    """yes when at least one generated test carries the CATCHES_CHANGE label."""
    return "yes" if numbers["catches_change"] > 0 else "no"


def no_tests_produced(report: dict, numbers: dict) -> bool:
    """True when the run finished but there is nothing to score.

    Two ways this happens: no test file was written at all, or a file was written
    that pytest found no tests in. Either way there is no measurement, so the
    case reports no score rather than a zero, which would read as "the AI looked
    and found nothing".
    """
    return not report["functions"] or numbers["tests"] == 0


def mutation_summary(report: dict) -> str:
    """The mutation score in one short cell, or why there is not one."""
    section = report.get("mutation")
    if not section:
        return "not run"

    scored = [item for item in section if item.get("score") is not None]
    if not scored:
        return "not defined"

    low = round(min(item["score"] for item in scored) * 100)
    high = round(max(item["score"] for item in scored) * 100)
    return f"{low}%" if low == high else f"{low}-{high}%"


# ---------------------------------------------------------------------------
# The report files. Never overwritten.
# ---------------------------------------------------------------------------

REPORTS_SUBDIR = Path("reports") / "real_cases"


def move_report(name: str) -> dict:
    """Move the two files run_pipeline saved into reports/real_cases/.

    Both destinations are checked before either file is moved, so a refusal
    never leaves half a report moved. An existing destination is a refusal, not
    something to overwrite: these files are the only record of a live
    evaluation, and silently replacing one would destroy the run it came from.
    """
    pairs = {}
    for suffix in (".md", ".json"):
        source = Path(pl.REPORTS_DIR) / f"{name}{suffix}"
        target = REPORTS_SUBDIR / f"{name}{suffix}"
        if not source.is_file():
            raise RefusedRun(
                f"the pipeline did not save {source}, so there is nothing to "
                f"move.")
        if target.exists():
            raise RefusedRun(
                f"{target} is already there, and this script never overwrites a "
                f"report. Nothing has been moved. Move or delete the earlier "
                f"run's report before running the evaluation again.")
        pairs[suffix] = (source, target)

    REPORTS_SUBDIR.mkdir(parents=True, exist_ok=True)
    for source, target in pairs.values():
        shutil.move(str(source), str(target))

    return {suffix: str(target) for suffix, (_, target) in pairs.items()}


# ---------------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------------

def project_test_result(folder: Path) -> tuple:
    """Run the project's own test on both versions and label it.

    This is check_real_cases.py's own four-label rule, imported rather than
    copied, so the two scripts cannot print different verdicts for one case.

    It is called only after run_pipeline has returned. By then the generator has
    already written its tests and is finished, so nothing here can reach it.
    """
    before_result = tr.run_tests(str(folder / "before.py"),
                                 str(folder / "existing_test.py"))
    after_result = tr.run_tests(str(folder / "after.py"),
                                str(folder / "existing_test.py"))
    return check.test_label(before_result, after_result)


def run_case(folder: Path) -> dict:
    """Run the pipeline on one case and gather everything we print about it."""
    before_file = str(folder / "before.py")
    after_file = str(folder / "after.py")
    name = folder.name

    # The seven files every case folder must hold, checked with the same list
    # check_real_cases.py uses and before any model call is spent. Running an
    # evaluation on an incomplete case would waste the daily allowance.
    missing = [n for n in check.REQUIRED_FILES
               if not (folder / n).is_file()]
    if missing:
        raise RefusedRun(
            f"{name} is missing {', '.join(missing)}. No model calls were made.")

    # The same two arguments and only those two. existing_test.py, witness.md and
    # source.md are not passed here and cannot be, because the pipeline is only
    # ever handed a before file and an after file.
    report = pl.run_pipeline(before_file, after_file, name,
                             fallback_allowed=False, mutation=True)

    numbers = read_report_numbers(report)

    saved = move_report(name)

    project_label, _meaning = project_test_result(folder)

    return {
        "case": name,
        "stopped": "",
        "functions": count_changes(before_file, after_file),
        "numbers": numbers,
        "caught": caught_the_bug(numbers),
        "project_label": project_label,
        "mutation": mutation_summary(report),
        "gemini_answers": report.get("gemini_answers", 0),
        "reports": saved,
        "has_tests": not no_tests_produced(report, numbers),
    }


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def case_line(row: dict) -> str:
    """One line saying everything about one case.

    A stopped case prints no numbers at all. A run that did not finish has no
    measurement in it, and a zero or a blank in a table reads too easily as a
    real result.
    """
    if row["stopped"]:
        return (f"{row['case']}  STOPPED: {row['stopped']}  "
                f"(no score from this case)")

    funcs = row["functions"]
    change_text = (f"funcs {funcs['total']} "
                   f"(mod {funcs['modified']} add {funcs['added']} "
                   f"rem {funcs['removed']})")
    if funcs["other"]:
        change_text += f" other {funcs['other']}"

    numbers = row["numbers"]
    return (f"{row['case']}  {change_text}  tests {numbers['tests']}  "
            f"CATCHES_CHANGE {numbers['catches_change']} of which "
            f"REAL_BUG {numbers['real_bug']}  catches: {row['caught']}  "
            f"project test: {row['project_label']}")


TABLE_HEADERS = ("case", "funcs", "tests", "CATCHES_CHANGE", "REAL_BUG", "caught",
                 "project test", "mutation")


def table_row(row: dict) -> tuple:
    """One row of the final table, in TABLE_HEADERS order."""
    numbers = row["numbers"]
    return (row["case"],
            str(row["functions"]["total"]),
            str(numbers["tests"]),
            str(numbers["catches_change"]),
            str(numbers["real_bug"]),
            row["caught"],
            row["project_label"],
            row["mutation"])


def print_table(rows: list) -> None:
    """The final table. Only printed when every case finished."""
    body = [table_row(row) for row in rows]

    # Every column is as wide as the widest thing in it, headings included. Sized
    # from the headings alone a value like CATCHES_CHANGE runs straight into the
    # next column and the table becomes unreadable.
    widths = [max([len(heading)] + [len(line[position]) for line in body])
              for position, heading in enumerate(TABLE_HEADERS)]

    def rendered(cells):
        return "  ".join(
            cell.ljust(widths[position]) if position == 0
            else cell.rjust(widths[position])
            for position, cell in enumerate(cells)).rstrip()

    rule = "-" * len(rendered(TABLE_HEADERS))

    print()
    print(RULE)
    print("SUMMARY")
    print(RULE)
    print(rendered(TABLE_HEADERS))
    print(rule)
    for cells in body:
        print(rendered(cells))
    print(rule)

    caught = sum(1 for row in rows if row["caught"] == "yes")
    print(f"  at least one generated test caught the bug in {caught} of "
          f"{len(rows)} case{'' if len(rows) == 1 else 's'}")

    # The number that says whether the run is worth anything at all. --no-fallback
    # is given, so this has to be 0; if it is not, answers came from the second
    # model and the table above is a mixture of two.
    gemini = sum(row.get("gemini_answers", 0) for row in rows)
    print(f"  answers from Gemini across every case: {gemini}"
          f"{' (must be 0)' if gemini else ''}")
    print(f"  a report for each case is in {REPORTS_SUBDIR.as_posix()}/")


def print_stopped_notice(rows: list, error) -> None:
    """Say the evaluation stopped, then give only the finished cases.

    No table, on purpose. A table with one case filled in and two blank looks
    like a run that found nothing in those two, when in fact it never asked.
    """
    print()
    print("!" * 74)
    print("! THE EVALUATION STOPPED EARLY. A PROVIDER IS OUT FOR THE DAY.")
    print("!")
    print(f"! {error}")
    print("!")
    print("! No table is printed, and no total is given. The cases below are")
    print("! the ones that finished. The rest were never asked, so nothing is")
    print("! known about them.")
    print("!" * 74)
    print()
    print("  The cases that finished:")
    for row in rows:
        print(f"    {case_line(row)}")
    print()
    print("  Stopping here is on purpose. --no-fallback is given, so the whole")
    print("  evaluation ends rather than quietly answering the rest from the")
    print("  second model. Wait for the daily allowance to reset and run it")
    print("  again.")


# ---------------------------------------------------------------------------
# The whole evaluation
# ---------------------------------------------------------------------------

def print_header(folders) -> None:
    """Say what is about to happen, and what the numbers mean."""
    count = len(folders)
    print(RULE)
    print("PRSentinel on the real bug cases")
    print(RULE)
    print(f"Python {sys.version.split()[0]}")
    print(f"{count} case folder{'' if count == 1 else 's'} in "
          f"examples/real_cases/")
    print()
    print("The cases were chosen before this was written, and nothing in the")
    print("pipeline, the prompts or the operators has been touched since. That")
    print("is what makes what comes out an evaluation rather than a tuning")
    print("result.")
    print()
    print("Settings, fixed and not changeable from the command line:")
    print("  --no-fallback   stop the whole evaluation if Groq runs out, so a")
    print("                  result is never part Groq and part Gemini")
    print("  --mutation      also measure how many small deliberate faults the")
    print("                  tests catch (asks no AI)")
    print()
    print("How to read it:")
    for label, meaning in HOW_TO_READ:
        print(f"  {label:<16}{meaning}")
    print()
    print("The generator sees before.py and after.py only. existing_test.py is")
    print("read after each run finishes, and only to print project test.")
    print()


HOW_TO_READ = (
    ("funcs", "functions diff_extractor found, with how many"),
    ("", "were modified, added or removed"),
    ("tests", "pytest test items: one per test function, plus one"),
    ("", "per parametrized case. Not files, not functions."),
    ("CATCHES_CHANGE", "generated tests that pass on before.py and"),
    ("", "fail on after.py"),
    ("REAL_BUG", "how many of those CATCHES_CHANGE tests were"),
    ("", "also judged to be pointing at a real bug"),
    ("", "(rule classifier only, no AI)"),
    ("catches", "yes when CATCHES_CHANGE is 1 or more"),
    ("project test", "the project's own test, run the same way, so"),
    ("", "the generated tests can be compared against it"),
    ("mutation", "how many deliberate faults the tests killed"),
)


def main() -> int:
    folders = check.case_folders()
    if not folders:
        print(f"No case folders found in {check.CASES}")
        return 1

    print_header(folders)

    # --no-fallback, set exactly as pipeline.main() sets it. Done once, before
    # the first call, so no case can accidentally be run with fallback on.
    llm_client.ALLOW_FALLBACK = False

    rows = []

    try:
        for position, folder in enumerate(folders, start=1):
            print(f"[{position}/{len(folders)}] {folder.name}")
            row = run_case(folder)

            if not row["has_tests"]:
                # The run finished, but there is nothing to measure. Saying so
                # keeps it from reading as a case where the AI looked and found
                # no bug, which is a different thing.
                row["stopped"] = ("the run finished but no tests were produced, "
                                  "so there is nothing to score")
                row["caught"] = "-"
                row["mutation"] = "no tests"

            rows.append(row)
            print(f"  {case_line(row)}")
            print(f"  reports: {row['reports']['.md']} and "
                  f"{row['reports']['.json']}")
            print()

    except pl.DailyLimitStop as error:
        # pipeline.print_stopped_on_daily_limit has already printed its notice in
        # full. Nothing is added to it except the cases that did finish.
        print_stopped_notice(rows, error)
        return pl.EXIT_DAILY_LIMIT

    except RefusedRun as error:
        print()
        print("!" * 74)
        print("! THE RUN WAS REFUSED AND NOTHING WAS OVERWRITTEN.")
        print("!")
        print(f"! {error}")
        print("!" * 74)
        return EXIT_REFUSED

    except Exception as error:  # noqa: BLE001
        print()
        print(f"[eval_real_cases] the evaluation broke: {error}")
        traceback.print_exc()
        return 1

    print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())