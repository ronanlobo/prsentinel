r"""The cheapest honest baseline: one plain LLM call per case, and score it.

Run it like this:

    .venv\Scripts\python.exe -u scripts\baseline_single_prompt.py

What this is for
----------------
PRSentinel is a pipeline: it finds the changed functions, asks for tests, runs
them against both versions, labels every test, judges them, reruns the failures
to check for flakiness, mutates the code to see how strong the tests are, and
writes a report. The fair question is how much of its result comes from the model
and how much comes from the machinery around the model.

This script answers that with the smallest thing on the other side of the
comparison: one call to the same model, the same before file, the same after
file, and the same one changed function's old and new source. No pipeline, no
mutation, no rerun loop, no judge. One prompt, one reply, then the reply is run
through prsentinel.test_runner and scored with test_runner's own labels.

The two arms are therefore given the same model, the same code and the same
scorer. The only thing that differs is the machinery, which is the thing being
measured.

The prompt, and why it says what it says
-----------------------------------------
PROMPT_TEMPLATE below was written once, on 2026-10-02, before any run, and is
frozen. tests/test_real_cases.py asserts its exact text, so it cannot be quietly
improved after seeing a result. An evaluation whose baseline can be rewritten
once the numbers are in is not an evaluation.

It is a plain task with no advice in it: write pytest tests that check the new
code still behaves like the old code. No edge cases are suggested, no "look for
anything the change could have made worse", no list of things to check. The
pipeline prompt has all of that, and that difference is deliberate and is part of
what is being compared.

One line in the prompt does say that the old code is the behaviour the function
is supposed to have. That is there so the task is not ambiguous about which side
is the reference. The pipeline prompt says the same thing; without it in both,
part of any difference between the arms would be down to that one sentence rather
than to the machinery.

What this script will not do
----------------------------
It has no command line. Fallback is switched off inside main(), before the first
call, so no case can accidentally be answered by the second model. If Groq runs
out for the day the whole run stops, prints the per-case line for each case that
finished, prints no table at all, and exits 6. A result made of part one model
and part another is not a result.

It never overwrites anything. If a case already has a saved reply, or a saved
PRSentinel report is missing so the other half of the comparison could not be
printed, the run is refused with exit 2 before a single model call is made. The
five PRSentinel reports it reads are the ones already committed under reports/.

What the numbers mean
---------------------
"tests" counts pytest test items, the same thing eval_real_cases.py counts: one
per test function, plus one per parametrized case.

"caught: yes" means at least one test carries the runner's CATCHES_CHANGE label.
It passes on before.py and fails on after.py. That is the same rule that scored
PRSentinel on the real cases, and it is applied by the same function, imported
from scripts/eval_real_cases.py rather than copied, so the two arms cannot be
scored by two different rules.

The PRSentinel half of the table is read from the saved reports. No number in
that half is typed in here. Where a report turns out not to carry the
provenance keys, the row says "older report" and the run says which ones, rather
than printing a blank that would read as a zero.

Nothing here ever prints or writes an API key.
"""

import importlib.util
import json
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent

sys.path.insert(0, str(PROJECT / "src"))

from prsentinel import config  # noqa: E402
from prsentinel import llm_client  # noqa: E402
from prsentinel import pipeline as pl  # noqa: E402
from prsentinel import test_generator as tg  # noqa: E402
from prsentinel import test_runner as tr  # noqa: E402
from prsentinel.diff_extractor import extract_changes_from_files  # noqa: E402

# The exit code for a run that was refused before it could do its work. pipeline
# uses 2 for its own refusal, so this reuses the same number and the same
# meaning rather than inventing a new one.
EXIT_REFUSED = 2

RULE = "=" * 74

# ---------------------------------------------------------------------------
# The frozen prompt
# ---------------------------------------------------------------------------
# Written on this date, before any run, and not to be changed afterwards. The
# date is here as well as in the test so that somebody reading the file knows
# which run the text belongs to.

FROZEN_ON = "2026-10-02"

# <<NAME>>, <<OLD CODE>> and <<NEW CODE>> are the only things that change. They
# are spelled with angle brackets rather than curly braces so that the text below
# is exactly the text that gets sent, with nothing to escape and nothing a
# stray brace in a code sample could break.
PROMPT_TEMPLATE = """\
You are writing pytest tests for a Python function named <<NAME>>.

A developer has just changed this function.

OLD CODE:
```python
<<OLD CODE>>
```

NEW CODE:
```python
<<NEW CODE>>
```

The OLD CODE is the behaviour the function is supposed to have.

Please write pytest tests that check the new code still behaves like the old \
code.

Rules for your answer:
- Import the function from a module named `target`, for example: \
`from target import <<NAME>>`
- Reply with pytest code only.
- Put all of it in one single code block.
- Do not explain anything.
"""


def build_prompt(change: dict) -> str:
    """The frozen prompt, with the one changed function dropped into it.

    Only the name, the old code and the new code. Nothing else about the case
    goes in, and nothing about the project, the bug or the folder is named.
    """
    return (PROMPT_TEMPLATE
            .replace("<<NAME>>", change["name"])
            .replace("<<OLD CODE>>", change["old_code"] or "")
            .replace("<<NEW CODE>>", change["new_code"] or ""))


# ---------------------------------------------------------------------------
# The two other scripts, imported rather than copied
# ---------------------------------------------------------------------------
# Both of these already know something this script needs to agree with.
# eval_real_cases.py holds read_report_numbers, the one function that turns a
# finished report into the three numbers that get printed, and it is the same
# function that scored PRSentinel on the real cases. check_real_cases.py holds
# the four-label rule for a project's own test and the list of real case folders.
# Two copies of either rule would eventually disagree, and a comparison where the
# two arms were scored by different code would be worthless.

def load_sibling(name: str):
    """Import a sibling script from scripts/, which is not a package."""
    path = HERE / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = load_sibling("eval_real_cases")
check = load_sibling("check_real_cases")


class RefusedRun(RuntimeError):
    """The run was refused before it could do its work."""


# ---------------------------------------------------------------------------
# The five cases
# ---------------------------------------------------------------------------

REPORTS = PROJECT / "reports"
REAL_REPORTS = REPORTS / "real_cases"

# The two synthetic rounds. examples/round1_off_by_one and
# examples/round2_mutable_default hold before.py, after.py and diff.patch and
# nothing else, so there is no project test for either of them.
SYNTHETIC_FOLDERS = (
    PROJECT / "examples" / "round1_off_by_one",
    PROJECT / "examples" / "round2_mutable_default",
)

# Where each reply's test file is saved. Tracked in git, the way baselines/ is,
# because after the live run these are the only record of what the baseline arm
# actually answered.
OUTPUT_DIR = PROJECT / "baselines_single_prompt"

# The keys a saved report has to carry for its row to be trusted. A report
# without them was written before they were being recorded, and its row says so
# rather than showing blanks that read as zeros.
PROVENANCE_KEYS = ("fallback", "gemini_answers")

# How tests_source in a saved report is shown in the "tests from" column.
TESTS_FROM = {
    "generated": "generated",
    "reused from baselines": "baseline copy",
}


def the_cases() -> list:
    """The five cases: the three real bugs, then the two synthetic rounds.

    The real case folders come from check_real_cases.py, so this script and that
    one cannot end up disagreeing about which real cases exist.
    """
    cases = []
    for folder in check.case_folders():
        cases.append({"name": folder.name, "group": "real", "folder": folder,
                      "report": REAL_REPORTS / f"{folder.name}.json"})
    for folder in SYNTHETIC_FOLDERS:
        cases.append({"name": folder.name, "group": "synthetic", "folder": folder,
                      "report": REPORTS / f"{folder.name}.json"})
    return cases


def saved_test_file(case: dict, change: dict) -> Path:
    """Where this case's reply is saved, named after the changed function.

    The same name the pipeline gives its test file, so the two arms are run the
    same way and a reader can see at a glance which file is which.
    """
    return OUTPUT_DIR / case["name"] / f"test_{change['name']}.py"


# ---------------------------------------------------------------------------
# Everything that is checked before a single model call is spent
# ---------------------------------------------------------------------------

def the_modified_change(case: dict) -> dict:
    """The one changed function this case has, or a refusal.

    The prompt shows an old version and a new version, so it needs a function
    that has both. A function that was added has no old version and one that was
    removed has no new version, so neither can be asked about here. If a case has
    anything other than exactly one modified function there is no single honest
    thing to put in the prompt, and guessing would be worse than stopping.

    Costs no model call.
    """
    folder = case["folder"]
    changes = extract_changes_from_files(str(folder / "before.py"),
                                         str(folder / "after.py"))
    modified = [change for change in changes
                if change["change_type"] == "modified"]

    if len(modified) != 1:
        raise RefusedRun(
            f"{case['name']} has {len(modified)} modified functions, and this "
            f"baseline sends exactly one prompt per case. It cannot be run "
            f"without guessing which function the prompt should be about. "
            f"No model calls were made.")

    change = modified[0]
    if not change["old_code"]:
        raise RefusedRun(
            f"{case['name']}: the old version of {change['name']} could not be "
            f"read out of before.py, so the prompt would be missing half of what "
            f"it needs. No model calls were made.")

    return change


def check_case(case: dict) -> dict:
    """Everything about one case that can be checked before the model is asked.

    Returns the one changed function, so run_case does not have to find it twice.
    """
    folder = case["folder"]
    name = case["name"]

    if not folder.is_dir():
        raise RefusedRun(f"there is no case folder at {folder}. No model calls "
                         f"were made.")

    # The seven files every real case folder must hold, checked with the same
    # list check_real_cases.py uses. The synthetic folders hold only the three
    # they have always held, so the list is applied to the real cases only.
    if case["group"] == "real":
        missing = [one for one in check.REQUIRED_FILES
                   if not (folder / one).is_file()]
        if missing:
            raise RefusedRun(
                f"{name} is missing {', '.join(missing)}. No model calls were "
                f"made.")

    for needed in ("before.py", "after.py"):
        if not (folder / needed).is_file():
            raise RefusedRun(
                f"{name} is missing {needed}. No model calls were made.")

    change = the_modified_change(case)

    # The other half of the comparison has to exist before this half is spent.
    # A row with a baseline number and no PRSentinel number beside it is half a
    # table, and it is easier to notice the refusal now than after the allowance
    # has gone.
    if not case["report"].is_file():
        raise RefusedRun(
            f"{case['report']} is not there, so there is nothing to put beside "
            f"the baseline's number for {name}. Run the evaluation first. No "
            f"model calls were made.")

    target = saved_test_file(case, change)
    if target.exists():
        raise RefusedRun(
            f"{target} is already there, and this script never overwrites a "
            f"saved reply. That file is the only record of one live run. Move "
            f"or delete it before running the baseline again.")

    return change


# ---------------------------------------------------------------------------
# Reading PRSentinel's side out of what already happened. No AI, nothing run.
# ---------------------------------------------------------------------------

def read_prsentinel(report: dict) -> dict:
    """What PRSentinel got, read out of a report that was already saved.

    read_report_numbers is imported from eval_real_cases.py, so this is the same
    code that produced the 1-of-3 headline for the real cases. The two arms are
    counted the same way or the comparison means nothing.

    "tests from" is taken from the report's own tests_source, so a reader can see
    that the synthetic rows were scored on frozen baseline tests rather than on
    a fresh generation.
    """
    numbers = ev.read_report_numbers(report)

    missing = [key for key in PROVENANCE_KEYS if key not in report]
    source = report.get("tests_source")

    return {
        "tests": numbers["tests"],
        "catches_change": numbers["catches_change"],
        "caught": ev.caught_the_bug(numbers),
        "tests_from": TESTS_FROM.get(source, source or "unknown"),
        "fallback": ("older report" if missing
                     else ("on" if report["fallback"] else "off")),
        "gemini": ("older report" if missing
                   else str(report["gemini_answers"])),
        "older": missing,
    }


def is_older(row: dict) -> bool:
    """True when this row's PRSentinel report did not carry its provenance."""
    return bool(row["prs"]["older"])


# ---------------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------------

def project_test_result(folder: Path) -> str:
    """Run the project's own test on both versions and label it.

    check_real_cases.py's own four-label rule, imported rather than copied, so
    the two scripts cannot print different verdicts for one case. Only the three
    real cases have an existing_test.py; the other two report n/a.

    Called only after ask_llm has returned and the reply has been scored. By then
    the generator is finished and has written its file, so nothing here can reach
    it.
    """
    if not (folder / "existing_test.py").is_file():
        return "n/a"

    before_result = tr.run_tests(str(folder / "before.py"),
                                 str(folder / "existing_test.py"))
    after_result = tr.run_tests(str(folder / "after.py"),
                                str(folder / "existing_test.py"))
    label, _meaning = check.test_label(before_result, after_result)
    return label


def score_reply(results: list) -> dict:
    """Count the runner's labels for the tests the model wrote.

    Returns the four numbers printed per case. "stopped" is set instead when
    there is no measurement to be had, because a zero would read as "the model
    looked and found nothing", which is a different thing.
    """
    if not results:
        return {"stopped": "pytest found no tests in the reply, so there is "
                           "nothing to score"}

    # One row named after the whole file means pytest could not load it, so
    # there are no test results at all. That is not a score of zero.
    if len(results) == 1 and results[0]["name"] == tr.WHOLE_FILE:
        detail = results[0].get("detail") or "no detail given"
        return {"stopped": f"the reply's test file could not be run at all "
                           f"({detail})"}

    catches = 0
    wrong_on_before = 0
    for result in results:
        if result["label"] == tr.CATCHES_CHANGE:
            catches += 1
        elif result["label"] == tr.TEST_WRONG_ON_BEFORE:
            wrong_on_before += 1

    return {"stopped": "", "tests": len(results), "catches_change": catches,
            "wrong_on_before": wrong_on_before,
            "caught": "yes" if catches else "no"}


def run_case(case: dict, change: dict) -> dict:
    """One plain call for one case, then score the reply the pipeline's way.

    Exactly one ask_llm call. There is no retry here beyond the one llm_client
    does for every call, no second opinion, no repair and no mutation.

    The order inside this function matters and is checked by a test. The model is
    asked first, its reply is scored second, and the project's own test is read
    last. By then the generator has finished and written its file, so there is no
    path from existing_test.py back to the prompt even in principle.
    """
    before_file = str(case["folder"] / "before.py")
    after_file = str(case["folder"] / "after.py")

    # Read once, from the file that was already committed. A local read of a
    # saved report cannot reach the model, which has not been called yet and will
    # not be given this dict.
    prs = read_prsentinel(
        json.loads(case["report"].read_text(encoding="utf-8")))

    # The same two files and the same one function's old and new source that the
    # pipeline is given. existing_test.py, witness.md and source.md are not
    # passed here and cannot be: the prompt is built from the change alone.
    reply = llm_client.ask_llm(build_prompt(change),
                               config.GENERATION_TEMPERATURE)

    saved = ""
    try:
        code = tg.extract_code(reply)
    except ValueError:
        base = {"stopped": "the reply had no code block in it, so there were "
                           "no tests to score"}
    else:
        target = saved_test_file(case, change)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, encoding="utf-8")
        saved = str(target.relative_to(PROJECT))

        # test_runner's own function, the one the pipeline uses, so both arms are
        # labelled by the same code.
        base = score_reply(tr.evaluate_tests(before_file, after_file, str(target)))

    return {"case": case["name"], "group": case["group"], "stopped": "",
            "base": base, "prs": prs, "saved": saved,
            # Read last, on purpose. See the docstring.
            "project_test": project_test_result(case["folder"])}


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def case_line(row: dict) -> str:
    """One line saying everything about one case.

    A case with no measurement prints no numbers at all. A run that did not
    finish has nothing in it, and a zero or a blank reads too easily as a real
    result.
    """
    base = row["base"]
    head = f"{row['case']}  ({row['group']})"

    if base["stopped"]:
        return f"{head}  STOPPED: {base['stopped']}  (no score from this case)"

    prs = row["prs"]
    older = "  [older report]" if is_older(row) else ""
    return (f"{head}  base: tests {base['tests']}  "
            f"CATCHES_CHANGE {base['catches_change']}  "
            f"TEST_WRONG_ON_BEFORE {base['wrong_on_before']}  "
            f"caught {base['caught']}   |   "
            f"PRSentinel: tests {prs['tests']}  "
            f"CATCHES_CHANGE {prs['catches_change']}  caught {prs['caught']}  "
            f"from {prs['tests_from']}  fallback {prs['fallback']}  "
            f"gemini {prs['gemini']}   |   "
            f"project test: {row['project_test']}{older}")


# The first four columns are the single-prompt baseline arm. The ones marked PRS
# are PRSentinel, read from the saved reports. The last column is the project's
# own test, which is the same for both arms.
TABLE_HEADERS = (
    "case",
    "tests", "CATCHES", "WRONG_ON_BEFORE", "caught",
    "PRS tests", "PRS CATCHES", "PRS caught",
    "PRS tests from", "PRS fallback", "PRS gemini",
    "project test",
)

BLANK = "-"


def table_cells(row: dict) -> tuple:
    """One row of the table, in TABLE_HEADERS order."""
    base = row["base"]
    prs = row["prs"]

    if base["stopped"]:
        first_four = (BLANK, BLANK, BLANK, BLANK)
    else:
        first_four = (str(base["tests"]), str(base["catches_change"]),
                      str(base["wrong_on_before"]), base["caught"])

    return ((row["case"],) + first_four +
            (str(prs["tests"]), str(prs["catches_change"]), prs["caught"],
             prs["tests_from"], prs["fallback"], prs["gemini"],
             row["project_test"]))


def print_table(rows: list) -> None:
    """The final table, with both arms side by side. Only when all cases ran."""
    body = [table_cells(row) for row in rows]

    # Every column is as wide as the widest thing in it, headings included. Sized
    # from the headings alone a value like WRONG_ON_BEFORE runs straight into the
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
    print("BOTH ARMS, SIDE BY SIDE")
    print(RULE)
    print("The first four number columns are the single-prompt baseline, from "
          "this run.")
    print("The PRS columns are read out of the saved reports. No number there "
          "was typed in.")
    print()
    print(rendered(TABLE_HEADERS))
    print(rule)
    for cells in body:
        print(rendered(cells))
    print(rule)

    print()
    print(subtotal("real cases", rows, "real"))
    print(subtotal("synthetic cases", rows, "synthetic"))

    # The footnote the synthetic rows need. Without it a reader sees two rows
    # where PRSentinel did well and has no way to know that its side of those two
    # rows was scored on tests frozen in an earlier step, while the baseline's
    # side is a fresh call on all five.
    synthetic = [row["case"] for row in rows if row["group"] == "synthetic"]
    if synthetic:
        print()
        print("  Footnote on the two synthetic rows: PRSentinel's side of " +
              ", ".join(synthetic))
        print("  was scored on frozen hand-checked baseline tests saved in an "
              "earlier step,")
        print("  not on a fresh generation. The baseline side is a fresh call on "
              "all five cases.")
        print("  Those two rows are therefore not a like-for-like comparison, "
              "and are not")
        print("  evidence that PRSentinel's generator beats one plain call.")

    older = [row["case"] for row in rows if is_older(row)]
    if older:
        print()
        print("  Older report: " + ", ".join(older))
        print("  These saved reports do not carry the keys this table needs, so "
              "their")
        print("  fallback and Gemini columns say 'older report' rather than "
              "showing a blank")
        print("  that would read as a zero. Those rows were produced before the "
              "keys were")
        print("  being recorded, so nothing is claimed about them.")


def subtotal(label: str, rows: list, group: str) -> str:
    """One labelled subtotal, and an honest word if a case was not measured.

    A stopped case is not a case where the model looked and found nothing, so it
    is counted and named separately rather than folded into the denominator as
    though it had been measured and missed.
    """
    mine = [row for row in rows if row["group"] == group]
    measured = [row for row in mine if not row["base"]["stopped"]]
    caught = sum(1 for row in measured if row["base"]["caught"] == "yes")
    unmeasured = len(mine) - len(measured)

    text = f"  {label}: {caught} of {len(mine)} caught the bug"
    if unmeasured:
        text += (f", with {unmeasured} of those not measured at all, so this is "
                 f"not a rate")
    return text


def print_stopped_notice(rows: list, error) -> None:
    """Say the run stopped, then give only the cases that finished.

    No table, on purpose. A table with one case filled in and four blank looks
    like a run that found nothing in those four, when in fact it never asked.
    """
    print()
    print("!" * 74)
    print("! THE RUN STOPPED EARLY. A PROVIDER IS OUT FOR THE DAY.")
    print("!")
    print(f"! {error}")
    print("!")
    print("! No table is printed, and no subtotal is given. The cases below are")
    print("! the ones that finished. The rest were never asked, so nothing is")
    print("! known about them.")
    print("!" * 74)
    print()
    print("  The cases that finished:")
    for row in rows:
        print(f"    {case_line(row)}")
    print()
    print("  Stopping here is on purpose. Fallback is off, so the whole run ends "
          "rather")
    print("  than quietly answering the rest from the second model. Wait for the "
          "daily")
    print("  allowance to reset and run it again.")


# ---------------------------------------------------------------------------
# The whole run
# ---------------------------------------------------------------------------

HOW_TO_READ = (
    ("tests", "pytest test items: one per test function, plus one"),
    ("", "per parametrized case. Not files, not functions."),
    ("CATCHES", "tests that pass on before.py and fail on after.py"),
    ("WRONG_ON_BEFORE", "tests that fail on before.py as well, so"),
    ("", "they cannot show the change did anything"),
    ("caught", "yes when CATCHES is 1 or more"),
    ("PRS tests from", "generated = fresh generation in that run"),
    ("", "baseline copy = frozen hand-checked tests"),
    ("PRS fallback", "whether fallback was permitted in that run"),
    ("PRS gemini", "answers that came from Gemini in that run"),
    ("project test", "the project's own test, run the same way. It is"),
    ("", "the same for both arms and belongs to neither."),
)


def print_header(cases: list) -> None:
    """Say what is about to happen, and what the numbers mean."""
    count = len(cases)
    print(RULE)
    print("One plain prompt per case, against the saved PRSentinel reports")
    print(RULE)
    print(f"Python {sys.version.split()[0]}")
    print(f"prompt frozen on {FROZEN_ON}, character for character, by a test")
    print(f"{count} case folder{'' if count == 1 else 's'}: "
          f"{sum(1 for case in cases if case['group'] == 'real')} real, "
          f"{sum(1 for case in cases if case['group'] == 'synthetic')} synthetic")
    print()
    print("Settings, fixed and not changeable from the command line:")
    print("  no fallback      stop the whole run if Groq runs out, so a result "
          "is never")
    print("                   part Groq and part Gemini")
    print(f"  temperature {config.GENERATION_TEMPERATURE!s:<5} the pipeline's "
          f"generation setting, from")
    print("                   config.GENERATION_TEMPERATURE, so both arms ask "
          "the model")
    print("                   the same way")
    print(f"  one call per case, model {config.GROQ_MODEL}")
    print()
    print("How to read it:")
    for label, meaning in HOW_TO_READ:
        print(f"  {label:<18}{meaning}")
    print()
    print("The model is shown one function's old code and new code and nothing "
          "else.")
    print("The project's own test is read after each case is scored, and only to "
          "print")
    print("the project test column.")
    print()


def main() -> int:
    cases = the_cases()
    if not cases:
        print("No cases were found.")
        return 1

    print_header(cases)

    # Everything checkable is checked now, before one call is spent. A refusal
    # here has cost nothing.
    try:
        changes = {case["name"]: check_case(case) for case in cases}
    except RefusedRun as error:
        print()
        print("!" * 74)
        print("! THE RUN WAS REFUSED AND NOTHING WAS ASKED.")
        print("!")
        print(f"! {error}")
        print("!" * 74)
        return EXIT_REFUSED

    # Fallback off, set once before the first call, so no case can accidentally be
    # answered by the second model. This is --no-fallback, done the same way
    # pipeline.main() does it.
    llm_client.ALLOW_FALLBACK = False

    rows = []

    try:
        for position, case in enumerate(cases, start=1):
            print(f"[{position}/{len(cases)}] {case['name']}")
            row = run_case(case, changes[case["name"]])
            rows.append(row)
            print(f"  {case_line(row)}")
            if row["saved"]:
                print(f"  saved: {row['saved']}")
            print()

    except llm_client.DailyLimitReached as error:
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
        print(f"[baseline_single_prompt] the run broke: {error}")
        traceback.print_exc()
        return 1

    print_table(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())