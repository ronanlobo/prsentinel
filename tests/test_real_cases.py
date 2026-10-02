"""Tests for the real bug cases in examples/real_cases.

Two things are guarded here, and both guard against the same failure: the cases
quietly ceasing to be real evidence.

1. Nothing in src/prsentinel may reach into examples/real_cases. These three
   cases are for evaluation only. If the pipeline could read them, then a run
   could be pointed at them, and every number from that run would stop being an
   evaluation and start being a tuning result. The only things allowed to name
   the folder are the three scripts that exist to check or measure them: the check
   script, the evaluation script that runs the pipeline over the cases, and the
   single-prompt baseline that scores one plain call against the saved reports.
   All three are named in ALLOWED_ELSEWHERE below, so the exception is a
   deliberate line in this file rather than a gap in it.

2. Each case folder must hold all seven files. A case missing its witness or its
   provenance cannot be checked, and a case that cannot be checked is not
   evidence of anything.

Neither test runs a case, runs pytest, or calls a model. They read files.
"""

import ast
import importlib.util
import re
from pathlib import Path

import pytest

from prsentinel import (classifier, llm_client, pipeline, test_generator,
                        test_runner)

PROJECT = Path(__file__).resolve().parent.parent
SRC = PROJECT / "src" / "prsentinel"
CASES = PROJECT / "examples" / "real_cases"

# The seven files every case folder must hold.
REQUIRED_FILES = (
    "before.py",
    "after.py",
    "diff.patch",
    "existing_test.py",
    "existing_test_original.py",
    "source.md",
    "witness.md",
)

# The only places outside src/ that are allowed to name the real cases.
#
# Three, and all three are named here on purpose. If a fourth ever appears it has
# to be added to this tuple in the same commit that created it, so that widening
# the exception is something somebody chose rather than something that happened.
ALLOWED_ELSEWHERE = (
    "scripts/check_real_cases.py",
    "scripts/eval_real_cases.py",
    "scripts/baseline_single_prompt.py",
)


# ---------------------------------------------------------------------------
# Nothing in the pipeline may read the real cases
# ---------------------------------------------------------------------------

def source_files():
    """Every .py file in the package, sorted so failures come out in order."""
    return sorted(SRC.glob("*.py"))


def test_the_package_has_source_files():
    """If this ever comes back empty the guard below would pass for the wrong
    reason, which is the one way a guard like this is worse than no guard."""
    assert source_files(), f"no .py files found in {SRC}"


def test_no_source_file_names_the_real_case_folder():
    """The important one.

    Read as plain text first, so a mention inside a comment or a docstring is
    caught too. An import buried in a string is still a mention, and a mention in
    a docstring is still a sign somebody was thinking about wiring it up.
    """
    offenders = []
    for path in source_files():
        text = path.read_text(encoding="utf-8")
        if "real_cases" in text or "real_youtube" in text or "real_PySnooper" in text:
            offenders.append(path.name)

    assert not offenders, (
        f"these files mention the real cases: {', '.join(offenders)}. The real "
        f"cases in examples/real_cases are evaluation only. Nothing in "
        f"src/prsentinel may read them, not even to run the pipeline on them. "
        f"Only {', '.join(ALLOWED_ELSEWHERE)} may.")


def test_the_pipeline_does_not_import_a_script_from_scripts():
    """Every script in scripts/ is a tool, not a package member.

    If the pipeline could import any of them, the guard above would be the only
    thing stopping them from becoming entangled. The names come from
    ALLOWED_ELSEWHERE, so this test grows with that tuple instead of having to be
    remembered separately.
    """
    names = [Path(name).stem for name in ALLOWED_ELSEWHERE]

    offenders = []
    for path in source_files():
        text = path.read_text(encoding="utf-8")
        for name in names:
            if name in text:
                offenders.append(f"{path.name} names {name}")

    assert not offenders, (
        f"these files name a script from scripts/: {', '.join(offenders)}. "
        f"Those scripts stand outside the package on purpose.")


def test_every_allowed_script_really_is_a_script():
    """So the guard above cannot pass because ALLOWED_ELSEWHERE is all lies."""
    for name in ALLOWED_ELSEWHERE:
        assert (PROJECT / name).is_file(), f"{name} does not exist"


def test_the_check_script_is_where_it_says_it_is():
    """So the guard above is guarding a file that exists."""
    script = PROJECT / "scripts" / "check_real_cases.py"
    assert script.is_file()


def test_the_check_script_calls_no_model():
    """No AI in the check. It reads files and runs pytest.

    Checked by parsing it, so a stray import of the client is caught even if the
    name happens not to appear on one particular code path.
    """
    script = PROJECT / "scripts" / "check_real_cases.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
            for alias in node.names:
                imported.add(f"{node.module}.{alias.name}" if node.module
                             else alias.name)

    for forbidden in ("prsentinel.llm_client", "prsentinel.classifier",
                      "prsentinel.heldback_eval", "prsentinel.llm_full",
                      "llm_client", "classifier", "heldback_eval", "urllib",
                      "requests", "http.client"):
        assert forbidden not in imported, \
            f"check_real_cases.py imports {forbidden}, and it must use no AI"


def test_the_check_script_reads_no_api_key():
    """It must not even name the two key variables it would need."""
    text = (PROJECT / "scripts" / "check_real_cases.py").read_text(
        encoding="utf-8")

    assert "GROQ_API_KEY" not in text
    assert "GEMINI_API_KEY" not in text


# ---------------------------------------------------------------------------
# Each case folder is complete
# ---------------------------------------------------------------------------

def case_folders():
    return sorted(path for path in CASES.iterdir() if path.is_dir())


def test_there_are_three_cases():
    """Two is not enough to say anything. More than three was out of scope."""
    folders = case_folders()

    assert len(folders) == 3, \
        f"expected 3 case folders, found {len(folders)}: " \
        f"{[f.name for f in folders]}"


def test_every_case_holds_all_seven_files():
    """One test for all cases, so a new folder is checked the same way."""
    missing_report = []
    for folder in case_folders():
        missing = [name for name in REQUIRED_FILES if not (folder / name).is_file()]
        if missing:
            missing_report.append(f"{folder.name} is missing {', '.join(missing)}")

    assert not missing_report, \
        "every case folder needs all seven files. " + "; ".join(missing_report)


def test_no_case_folder_holds_anything_else():
    """Stated so a stray file is noticed rather than tolerated.

    A leftover .bak or a scratch clone inside a case folder would be committed by
    accident, and a cloned project is exactly what must not be committed.
    """
    # __pycache__ is allowed through, because importing a case file creates one
    # and .gitignore already excludes it. Anything else is a stray.
    allowed = set(REQUIRED_FILES) | {"__pycache__"}

    for folder in case_folders():
        extra = sorted(path.name for path in folder.iterdir()
                       if path.name not in allowed)
        assert not extra, \
            f"{folder.name} holds files that are not part of a case: " \
            f"{', '.join(extra)}"


def test_no_case_holds_a_copy_of_its_own_project():
    """The projects were cloned into scratch space, not into the case folders.

    Checked by name, because a full youtube-dl or PySnooper checkout in here
    would be tens of megabytes and must never be committed.
    """
    for folder in case_folders():
        names = {path.name.lower() for path in folder.iterdir()}
        for project in ("youtube_dl", "pysnooper", ".git", "compat.py",
                        "pycompat.py"):
            assert project.lower() not in names, \
                f"{folder.name} contains {project}, which is a copy of the " \
                f"project rather than part of the case"


# ---------------------------------------------------------------------------
# The two halves of a case must agree with each other
# ---------------------------------------------------------------------------

CHANGED_MARKER = "# --- CHANGED FUNCTION"


def copied_region(text):
    """The copied project code: first import line down to the marker.

    The docstring above is ours and names its own file, so it is skipped. Working
    line by line rather than by character offset, because "import " also appears
    inside those docstrings and a character search would find the wrong one.
    """
    lines = text.splitlines(keepends=True)
    start = next(index for index, line in enumerate(lines)
                 if line.startswith("import "))
    end = next(index for index, line in enumerate(lines)
               if line.startswith(CHANGED_MARKER))
    return "".join(lines[start:end])


def test_every_case_marks_where_the_change_is():
    """The changed function is marked, so the identical part can be compared."""
    for folder in case_folders():
        for version in ("before.py", "after.py"):
            text = (folder / version).read_text(encoding="utf-8")
            assert CHANGED_MARKER in text, \
                f"{folder.name}/{version} has no {CHANGED_MARKER!r} marker"


def test_the_two_halves_of_a_case_are_the_same_except_the_change():
    """Everything above the marker must be byte-identical.

    Both files start with our own docstring, which names its own file and so
    differs on purpose. Everything from the first import down to the marker is
    copied project code, and that has to match exactly or the case is measuring
    two different things.
    """
    for folder in case_folders():
        before = (folder / "before.py").read_text(encoding="utf-8")
        after = (folder / "after.py").read_text(encoding="utf-8")

        assert copied_region(before) == copied_region(after), \
            f"{folder.name}: the copied code above {CHANGED_MARKER!r} differs " \
            f"between before.py and after.py. It must be identical."


def test_the_changed_part_really_is_a_different_function():
    """Below the marker the two must differ, or there is no bug to find."""
    for folder in case_folders():
        before = (folder / "before.py").read_text(encoding="utf-8")
        after = (folder / "after.py").read_text(encoding="utf-8")

        marker = CHANGED_MARKER
        changed_before = before[before.index(marker):]
        changed_after = after[after.index(marker):]

        assert changed_before != changed_after, \
            f"{folder.name}: the code below {marker!r} is identical in before.py " \
            f"and after.py, so there is no change here to test"


def test_each_case_documents_where_it_came_from():
    """source.md must name the project, both commits and the test file.

    A case with no provenance cannot be checked against the project it claims to
    come from, which is the only thing that makes it real rather than plausible.
    """
    for folder in case_folders():
        text = (folder / "source.md").read_text(encoding="utf-8").lower()

        assert "licence" in text or "license" in text, \
            f"{folder.name}/source.md does not record the project's licence"
        assert "buggy commit" in text, \
            f"{folder.name}/source.md does not give the buggy commit"
        assert "fixed commit" in text, \
            f"{folder.name}/source.md does not give the fixed commit"
        assert "python" in text, \
            f"{folder.name}/source.md does not say which Python the bug targets"


def test_each_case_records_its_helper_count():
    """The limit was 3 per case. The number must be written down, not implied."""
    for folder in case_folders():
        text = (folder / "source.md").read_text(encoding="utf-8").lower()

        assert "helper" in text, \
            f"{folder.name}/source.md does not discuss helpers"
        assert "under the limit of 3" in text, \
            f"{folder.name}/source.md does not state the helper count against " \
            f"the limit of 3"


def test_no_case_goes_over_the_helper_limit():
    """Read from the table, not from the sentence, so the wording cannot drift.

    source.md marks each copied thing as counting or not counting as a helper,
    with "yes" in the last column. Counting the "yes" rows gives the number that
    has to be 3 or fewer.
    """
    for folder in case_folders():
        counted = 0
        for line in (folder / "source.md").read_text(
                encoding="utf-8").splitlines():
            if not line.startswith("|") or line.startswith("|---"):
                continue
            cells = [cell.strip().lower() for cell in line.strip("|").split("|")]
            if len(cells) >= 5 and cells[4].startswith("yes"):
                counted += 1

        assert counted <= 3, \
            f"{folder.name} copies in {counted} helpers, over the limit of 3. " \
            f"It should have been skipped and reported instead."


def test_each_case_documents_what_changed_in_its_test():
    """existing_test.py is adapted, so the adaptation must be listed."""
    for folder in case_folders():
        text = (folder / "source.md").read_text(encoding="utf-8").lower()

        assert "existing_test.py" in text, \
            f"{folder.name}/source.md does not discuss existing_test.py"
        assert "existing_test_original.py" in text, \
            f"{folder.name}/source.md does not point at the byte-for-byte copy"


def test_every_witness_has_one_runnable_block():
    """The check script pulls the witness out of witness.md, so there has to be
    exactly one block for it to find."""
    for folder in case_folders():
        text = (folder / "witness.md").read_text(encoding="utf-8")
        blocks = re.findall(r"```python\n(.*?)```", text, re.DOTALL)

        assert len(blocks) == 1, \
            f"{folder.name}/witness.md has {len(blocks)} ```python blocks; the " \
            f"check script needs exactly one"


def test_every_witness_documents_both_versions():
    """Both expected outputs, or the check has nothing to compare against."""
    for folder in case_folders():
        text = (folder / "witness.md").read_text(encoding="utf-8")

        assert "before.py" in text
        assert "after.py" in text

# ---------------------------------------------------------------------------
# Step 10B: the evaluation script
# ---------------------------------------------------------------------------
# scripts/eval_real_cases.py runs the pipeline over the three cases and prints
# what it found. It is allowed to name the folder, because ALLOWED_ELSEWHERE at
# the top of this file says so.
#
# What it is not allowed to do is let the three files that give the game away
# reach the generator. existing_test.py is the project's own test for this bug.
# witness.md is an input that is known to separate the two versions. source.md
# says in plain words what the change was and which commit fixed it. If the
# model could read any of them, "did PRSentinel find the bug" would measure
# nothing at all, and the three cases would be worth less than the synthetic ones
# rather than more.
#
# None of the tests below run the pipeline, run pytest on a case, or call a
# model. They read files, parse them, and feed numbers made by hand into the
# functions that read a finished report.

EVAL_SCRIPT = PROJECT / "scripts" / "eval_real_cases.py"

# The three files the generator must never see. existing_test.py is read once
# per case by the evaluation script, but only after the generator is finished.
FORBIDDEN_FOR_THE_GENERATOR = ("existing_test.py", "witness.md", "source.md")

_LOADED_SCRIPTS = {}


def load_script(path):
    """Import a file from scripts/, which is not a package.

    Cached, so every test here gets the same module object and the script is
    only read and executed once.
    """
    if path not in _LOADED_SCRIPTS:
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LOADED_SCRIPTS[path] = module
    return _LOADED_SCRIPTS[path]


ev = load_script(EVAL_SCRIPT)


def a_finished_row(name):
    """One case that finished, built the way run_case builds it.

    Numbers are made up on purpose. Nothing here runs anything, and a test that
    needs a real pipeline result would be a test that spends model calls.
    """
    return {
        "case": name,
        "stopped": "",
        "functions": {"total": 1, "modified": 1, "added": 0, "removed": 0,
                      "other": 0},
        "numbers": {"tests": 4, "catches_change": 2, "real_bug": 1},
        "caught": "yes",
        "project_label": "CATCHES_CHANGE",
        "mutation": "80%",
        "gemini_answers": 0,
        "reports": {".md": "x.md", ".json": "x.json"},
        "has_tests": True,
    }


def a_fake_report(functions):
    """The smallest thing read_report_numbers can be handed."""
    return {"functions": functions}


def a_fake_function(counts, judgements):
    """One changed function in a finished report.

    counts is keyed by the runner's labels. judgements holds one entry per test
    the plain classifier was asked about.
    """
    return {"function": "some_function", "counts": counts,
            "judgements": judgements}


def capture(function, *arguments):
    """Run something that prints and hand back what it printed."""
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        function(*arguments)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# The yes/no answer
# ---------------------------------------------------------------------------

def test_one_catching_test_is_enough_to_say_yes():
    """The bar is one, not a majority and not a count of files."""
    report = a_fake_report([
        a_fake_function({test_runner.OK: 3, test_runner.CATCHES_CHANGE: 1}, []),
    ])

    numbers = ev.read_report_numbers(report)

    assert numbers["tests"] == 4
    assert numbers["catches_change"] == 1
    assert ev.caught_the_bug(numbers) == "yes"


def test_a_case_where_nothing_catches_the_change_says_no():
    report = a_fake_report([
        a_fake_function({test_runner.OK: 5, test_runner.ODD: 1}, []),
    ])

    numbers = ev.read_report_numbers(report)

    assert numbers["tests"] == 6
    assert numbers["catches_change"] == 0
    assert ev.caught_the_bug(numbers) == "no"


def test_an_empty_report_says_no_rather_than_raising():
    """No changed function at all is a case that found nothing, not a crash."""
    numbers = ev.read_report_numbers(a_fake_report([]))

    assert numbers == {"tests": 0, "catches_change": 0, "real_bug": 0}
    assert ev.caught_the_bug(numbers) == "no"


def test_tests_the_runner_never_judged_still_count_as_tests():
    """A test that passes on both versions is still a test that was generated.

    It just is not evidence of anything, so it counts in "tests" and not in
    "CATCHES_CHANGE". Getting this backwards would quietly inflate both numbers.
    """
    report = a_fake_report([
        a_fake_function({test_runner.OK: 2, test_runner.TEST_WRONG_ON_BEFORE: 1},
                        [{"label": test_runner.TEST_WRONG_ON_BEFORE,
                          "verdict": classifier.BAD_TEST}]),
    ])

    numbers = ev.read_report_numbers(report)

    assert numbers["tests"] == 3
    assert numbers["catches_change"] == 0
    assert numbers["real_bug"] == 0


def test_real_bug_is_counted_out_of_the_tests_that_catch_the_change():
    """Never out of all tests, and never out of the judge alone.

    A test that was judged a real bug but does not actually fail on after.py is
    not evidence of a bug, it is a mistake in the classifier. Counting it would
    let the headline number rise without a single test catching anything.
    """
    report = a_fake_report([
        a_fake_function(
            {test_runner.CATCHES_CHANGE: 4, test_runner.OK: 2},
            [{"label": test_runner.CATCHES_CHANGE,
              "verdict": classifier.REAL_BUG},
             {"label": test_runner.CATCHES_CHANGE,
              "verdict": classifier.BAD_TEST},
             {"label": test_runner.CATCHES_CHANGE,
              "verdict": classifier.FLAKY},
             {"label": test_runner.CATCHES_CHANGE,
              "verdict": "UNKNOWN"},
             # Judged a real bug, but the runner says it passes on both sides.
             {"label": test_runner.OK, "verdict": classifier.REAL_BUG}]),
    ])

    numbers = ev.read_report_numbers(report)

    assert numbers["catches_change"] == 4
    assert numbers["real_bug"] == 1
    assert numbers["real_bug"] <= numbers["catches_change"]


def test_the_yes_or_no_is_printed_with_the_project_result_next_to_it():
    line = ev.case_line(a_finished_row("real_youtube-dl_bug3"))

    assert "real_youtube-dl_bug3" in line
    assert "catches: yes" in line
    assert "CATCHES_CHANGE 2" in line
    assert "REAL_BUG 1" in line
    assert "project test: CATCHES_CHANGE" in line


def test_the_case_line_says_how_the_functions_were_changed():
    """Modified, added and removed are reported separately.

    A removed function is never given tests, so folding it into "functions
    found" would make the denominator bigger than the thing being measured.
    """
    row = a_finished_row("real_youtube-dl_bug43")
    row["functions"] = {"total": 3, "modified": 1, "added": 1, "removed": 1,
                        "other": 0}

    line = ev.case_line(row)

    assert "funcs 3 (mod 1 add 1 rem 1)" in line


def test_the_counting_rule_is_stated_in_the_header():
    """Function or parametrized case is not something to leave to memory."""
    printed = capture(ev.print_header, case_folders())

    assert "parametrized case" in printed
    assert "Not files, not functions" in printed


# ---------------------------------------------------------------------------
# A stopped case reports no score
# ---------------------------------------------------------------------------

def test_a_stopped_case_line_prints_no_numbers():
    """No score, not a zero.

    A zero reads as "the model looked and found nothing", which is a different
    claim from "there was nothing to look at". Printing one when the other is
    true is how a broken run turns into a result.
    """
    row = a_finished_row("real_youtube-dl_bug3")
    row["stopped"] = ("the run finished but no tests were produced, so there "
                      "is nothing to score")
    row["caught"] = "-"
    row["mutation"] = "no tests"

    line = ev.case_line(row)

    assert "STOPPED" in line
    assert "no score from this case" in line
    for number in ("funcs 1", "tests 4", "CATCHES_CHANGE 2", "REAL_BUG 1",
                   "catches:", "project test:"):
        assert number not in line, \
            f"a stopped case must not print {number!r}, because it has no " \
            f"measurement. Got: {line}"


def test_a_finished_run_with_no_tests_counts_as_stopped():
    """Two shapes of the same thing: no test file, or a file with no tests."""
    nothing_written = a_fake_report([])
    empty_report_numbers = ev.read_report_numbers(nothing_written)
    assert ev.no_tests_produced(nothing_written, empty_report_numbers)

    one_empty_file = a_fake_report([
        a_fake_function({test_runner.OK: 0}, []),
    ])
    assert ev.no_tests_produced(one_empty_file, ev.read_report_numbers(one_empty_file))


def test_a_run_that_produced_tests_is_not_stopped():
    row = a_finished_row("real_youtube-dl_bug3")
    report = a_fake_report([
        a_fake_function({test_runner.OK: 1}, []),
    ])

    assert not ev.no_tests_produced(report, ev.read_report_numbers(report))
    assert "STOPPED" not in ev.case_line(row)


def test_the_daily_limit_uses_the_pipelines_own_exit_code():
    """6, so one number means the same thing everywhere in the project."""
    assert ev.pl.EXIT_DAILY_LIMIT == 6


def test_a_daily_limit_stops_the_whole_run_and_prints_no_table(monkeypatch, capsys):
    """The first thing that runs out of calls ends everything.

    --no-fallback is given, so every remaining case would fail the same way. A
    table with two rows of dashes in it looks like a result; there is no result.
    """
    attempted = []

    def fake_run_case(folder):
        attempted.append(folder.name)
        if len(attempted) == 2:
            raise ev.pl.DailyLimitStop("Groq is out of calls for the day.")
        return a_finished_row(folder.name)

    monkeypatch.setattr(ev, "run_case", fake_run_case)
    monkeypatch.setattr(ev.llm_client, "ALLOW_FALLBACK", True)

    code = ev.main()
    printed = capsys.readouterr().out

    assert code == 6
    assert len(attempted) == 2, \
        f"the run went past the case that hit the limit: {attempted}"
    assert "SUMMARY" not in printed
    assert "at least one generated test caught the bug" not in printed
    # The case that did finish is still reported, so the work is not thrown away.
    assert attempted[0] in printed


def test_main_turns_the_fallback_off(monkeypatch, capsys):
    """--no-fallback means the flag, set exactly the way pipeline.main() sets it."""
    monkeypatch.setattr(ev, "run_case", lambda folder: a_finished_row(folder.name))
    monkeypatch.setattr(ev.llm_client, "ALLOW_FALLBACK", True)

    ev.main()
    capsys.readouterr()

    assert ev.llm_client.ALLOW_FALLBACK is False


def test_a_clean_run_prints_the_table_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(ev, "run_case", lambda folder: a_finished_row(folder.name))

    code = ev.main()
    printed = capsys.readouterr().out

    assert code == 0
    assert "SUMMARY" in printed
    assert "at least one generated test caught the bug in 3 of 3 cases" in printed


def test_a_table_that_used_gemini_says_so_on_the_console(monkeypatch, capsys):
    """The Groq-only promise is checked by the run itself, not only by eye.

    A non-zero total is worth shouting about in the one place a reader is
    certain to look, because the table above it is then a mixture of two models
    and stops being a result.
    """
    def one_answer_from_gemini(folder):
        row = a_finished_row(folder.name)
        row["gemini_answers"] = 1
        return row

    monkeypatch.setattr(ev, "run_case", one_answer_from_gemini)

    ev.main()
    printed = capsys.readouterr().out

    assert "answers from Gemini across every case: 3" in printed
    assert "must be 0" in printed


def test_a_table_that_stayed_on_groq_does_not_carry_a_warning(monkeypatch, capsys):
    monkeypatch.setattr(ev, "run_case", lambda folder: a_finished_row(folder.name))

    ev.main()
    printed = capsys.readouterr().out

    assert "answers from Gemini across every case: 0" in printed
    assert "must be 0" not in printed


def test_a_refused_run_ends_the_evaluation_with_its_own_code(monkeypatch, capsys):
    """A report already being there stops everything, before any table.

    The refusal comes from run_case, which is the only place that knows what the
    pipeline actually saved, so it is faked here at the same level.
    """
    def refuse(folder):
        raise ev.RefusedRun(f"{folder.name}.md is already there")

    monkeypatch.setattr(ev, "run_case", refuse)
    monkeypatch.setattr(ev, "print_table", lambda rows: pytest.fail(
        "a refused run must not print a table"))

    code = ev.main()
    printed = capsys.readouterr().out

    assert code == 2
    assert "NOTHING WAS OVERWRITTEN" in printed
    assert "already there" in printed
    assert "SUMMARY" not in printed


def test_a_run_that_broke_is_not_reported_as_a_result(monkeypatch, capsys):
    """A crash inside a case is a failure of this script, not a score."""
    def explode(folder):
        raise RuntimeError("something went wrong inside a case")

    monkeypatch.setattr(ev, "run_case", explode)
    monkeypatch.setattr(ev, "print_table", lambda rows: pytest.fail(
        "a broken run must not print a table"))

    code = ev.main()
    printed = capsys.readouterr().out

    assert code == 1
    assert "SUMMARY" not in printed


# ---------------------------------------------------------------------------
# The reports are moved, never overwritten
# ---------------------------------------------------------------------------

def a_reports_folder(monkeypatch, tmp_path):
    """Point the move at a scratch folder and hand back both folders."""
    saved = tmp_path / "reports"
    destination = tmp_path / "real_cases"
    saved.mkdir()
    destination.mkdir()
    monkeypatch.setattr(ev.pl, "REPORTS_DIR", str(saved))
    monkeypatch.setattr(ev, "REPORTS_SUBDIR", destination)
    return saved, destination


def test_the_move_puts_both_files_in_the_real_cases_folder(monkeypatch, tmp_path):
    saved, destination = a_reports_folder(monkeypatch, tmp_path)
    for suffix in (".md", ".json"):
        (saved / f"case_a_bug1{suffix}").write_text("body", encoding="utf-8")

    ev.move_report("case_a_bug1")

    for suffix in (".md", ".json"):
        assert (destination / f"case_a_bug1{suffix}").is_file()
        assert not (saved / f"case_a_bug1{suffix}").exists()


def test_the_move_refuses_rather_than_overwriting(monkeypatch, tmp_path):
    """An earlier run's report is the only record that run happened."""
    saved, destination = a_reports_folder(monkeypatch, tmp_path)
    for suffix in (".md", ".json"):
        (saved / f"case_a_bug1{suffix}").write_text("second run", encoding="utf-8")
        (destination / f"case_a_bug1{suffix}").write_text("first run",
                                                         encoding="utf-8")

    with pytest.raises(ev.RefusedRun):
        ev.move_report("case_a_bug1")

    for suffix in (".md", ".json"):
        assert (destination / f"case_a_bug1{suffix}").read_text(
            encoding="utf-8") == "first run"


def test_a_refused_move_touches_neither_file(monkeypatch, tmp_path):
    """Checked before either file moves, so a refusal cannot leave half a report.

    Here only the .json is in the way. If the .md were moved first and the
    refusal came second, the folder would hold a new .md beside an old .json and
    the two would not be a report of anything.
    """
    saved, destination = a_reports_folder(monkeypatch, tmp_path)
    for suffix in (".md", ".json"):
        (saved / f"case_a_bug1{suffix}").write_text("second run", encoding="utf-8")
    (destination / "case_a_bug1.json").write_text("first run", encoding="utf-8")

    with pytest.raises(ev.RefusedRun):
        ev.move_report("case_a_bug1")

    assert (saved / "case_a_bug1.md").is_file(), \
        "the .md should not have moved; the refusal is meant to come first"
    assert not (destination / "case_a_bug1.md").exists()


def test_the_refusal_uses_the_projects_run_refused_code():
    """2, the same number pipeline.main() uses for a run it would not do."""
    assert ev.EXIT_REFUSED == 2


# ---------------------------------------------------------------------------
# The generator never sees the three give-away files
# ---------------------------------------------------------------------------

def test_the_eval_script_is_where_it_says_it_is():
    """So the guards below are guarding something that exists."""
    assert EVAL_SCRIPT.is_file()


def test_the_eval_script_names_no_api_key():
    """Same guard as the check script has, extended to this one.

    This is the script that will be run with both keys loaded in the session, so
    it must not even name the variables. It reads them through the llm_client and
    has nothing to do with them itself.
    """
    text = EVAL_SCRIPT.read_text(encoding="utf-8")

    assert "GROQ_API_KEY" not in text
    assert "GEMINI_API_KEY" not in text


def eval_script_tree():
    return ast.parse(EVAL_SCRIPT.read_text(encoding="utf-8"))


def calls_named(tree, name):
    """Every call to that name, found by walking the parsed script."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        label = (function.attr if isinstance(function, ast.Attribute)
                 else getattr(function, "id", ""))
        if label == name:
            found.append(node)
    return found


def strings_in(node):
    """Every string literal anywhere inside this bit of the tree."""
    return [item.value for item in ast.walk(node)
            if isinstance(item, ast.Constant) and isinstance(item.value, str)]


def enclosing_function(tree, node):
    """The function whose body contains this node."""
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        for statement in function.body:
            if any(item is node for item in ast.walk(statement)):
                return function
    return None


def assignment_sources(function):
    """name -> what it was assigned, for the simple assignments only.

    Unparsed back to text, because the point is to check the file name, not the
    shape of the expression that built it.
    """
    sources = {}
    for statement in ast.walk(function):
        if not isinstance(statement, ast.Assign):
            continue
        if len(statement.targets) != 1:
            continue
        if not isinstance(statement.targets[0], ast.Name):
            continue
        sources[statement.targets[0].id] = ast.unparse(statement.value)
    return sources


def test_the_pipeline_is_handed_before_and_after_and_nothing_else():
    """The strongest form of the guard, and the shortest.

    It reads the call itself rather than trusting a comment. One call, two
    positional arguments coming from the before file and the after file, and not
    one of the three give-away files anywhere in it.
    """
    tree = eval_script_tree()
    calls = calls_named(tree, "run_pipeline")

    assert len(calls) == 1, \
        f"expected exactly one run_pipeline call, found {len(calls)}. Every " \
        f"case must go through the one the CLI uses."
    call = calls[0]
    function = enclosing_function(tree, call)

    assert function is not None, "the call is not inside a function"
    assert len(call.args) >= 2, "run_pipeline is called without a before and after"
    assert all(isinstance(argument, ast.Name) for argument in call.args[:2]), \
        "the two file arguments should be plain names, so they can be traced"

    sources = assignment_sources(function)
    first, second = (argument.id for argument in call.args[:2])

    assert "before.py" in sources.get(first, ""), \
        f"{first!r} is not built from before.py. It is: " \
        f"{sources.get(first)!r}"
    assert "after.py" in sources.get(second, ""), \
        f"{second!r} is not built from after.py. It is: " \
        f"{sources.get(second)!r}"
    assert first != second, "both files cannot come from the same name"

    named = " ".join(strings_in(call)) + " " + \
        " ".join(keyword.arg or "" for keyword in call.keywords)
    for forbidden in FORBIDDEN_FOR_THE_GENERATOR:
        assert forbidden not in named, \
            f"the pipeline is handed {forbidden}. The generator must never see " \
            f"the project's own test, the witness, or the note about the change."


def test_no_line_of_code_names_the_witness_or_the_source_note():
    """Checked in the parsed code, so comments and docstrings cannot pass it.

    Naming those two files is not itself wrong: the module docstring explains
    that the generator never sees them, and that explanation is wanted. But no
    line of code may build a path to either of them, so every string outside
    every docstring is looked at.
    """
    tree = eval_script_tree()

    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            docstrings.add(id(first.value))

    offenders = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        if not isinstance(node.value, str) or id(node) in docstrings:
            continue
        for forbidden in ("witness.md", "source.md"):
            if forbidden in node.value:
                offenders.add(forbidden)

    assert not offenders, \
        f"eval_real_cases.py builds or opens these in its code: " \
        f"{', '.join(sorted(offenders))}. The evaluation script has no reason to " \
        f"know either file exists."


def test_the_projects_own_test_is_read_only_after_the_generator_is_finished():
    """existing_test.py may be read for reporting, but never before or during.

    The order inside run_case is what makes that true. The generator has written
    its tests and run_pipeline has returned before the file is opened, so there
    is no path from one to the other even in principle.
    """
    tree = eval_script_tree()
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "run_case")

    order = []
    for statement in function.body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                label = getattr(node.func, "attr", None) or getattr(
                    node.func, "id", "")
                if label in ("run_pipeline", "project_test_result"):
                    order.append(label)
                    break

    assert order == ["run_pipeline", "project_test_result"], \
        f"run_case does {order}. The project's own test has to be read after " \
        f"run_pipeline has returned, and nothing else may reach the generator."


def distinctive_lines(folder, name):
    """Lines of prose from a file the generator must never see.

    Taken from the file itself rather than written here, so the guard keeps
    working if a case is ever rebuilt. Lines that also appear in before.py or
    after.py are skipped: those are allowed in the prompt.
    """
    before = (folder / "before.py").read_text(encoding="utf-8")
    after = (folder / "after.py").read_text(encoding="utf-8")

    found = set()
    for line in (folder / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if len(line) < 40 or line[0] in "#|`=-*[]":
            continue
        if line in before or line in after:
            continue
        found.add(line)
    return sorted(found)


def test_the_generator_never_sees_a_line_from_the_three_give_away_files():
    """Built for real, for every case, and checked line by line.

    The prompts are made the way the pipeline makes them, from the same
    extractor and the same builder, so this is the text the model would actually
    be given. If any line that appears only in existing_test.py, witness.md or
    source.md turns up in one, the case has been given away.
    """
    checked = 0

    for folder in case_folders():
        forbidden_lines = []
        for name in FORBIDDEN_FOR_THE_GENERATOR:
            forbidden_lines.extend(distinctive_lines(folder, name))

        assert forbidden_lines, \
            f"{folder.name}: no lines could be taken from the give-away files, " \
            f"so this test would pass for the wrong reason"

        changes = ev.extract_changes_from_files(str(folder / "before.py"),
                                                str(folder / "after.py"))
        assert changes, f"{folder.name}: no changed function was found"

        for change in changes:
            prompt = test_generator.build_prompt(change)
            checked += 1

            for line in forbidden_lines:
                assert line not in prompt, \
                    f"{folder.name}: the prompt for {change['name']} contains a " \
                    f"line from a file the generator must not see: {line!r}"

    assert checked >= 3, f"only {checked} prompts were checked"


def test_the_prompt_holds_nothing_but_code_taken_from_before_and_after():
    """The positive version of the same guard.

    The prompt has two code blocks: the old function and the new one. Each has
    to be a copy of what is actually in the corresponding file. A prompt is then
    made of those two blocks plus wording that the frozen prompt supplies, so
    there is nowhere left for anything from another file to hide.
    """
    for folder in case_folders():
        before = (folder / "before.py").read_text(encoding="utf-8")
        after = (folder / "after.py").read_text(encoding="utf-8")

        changes = ev.extract_changes_from_files(str(folder / "before.py"),
                                                str(folder / "after.py"))
        for change in changes:
            prompt = test_generator.build_prompt(change)
            blocks = re.findall(r"```python\n(.*?)```", prompt, re.DOTALL)

            assert len(blocks) == 2, \
                f"{folder.name}: the prompt for {change['name']} has " \
                f"{len(blocks)} code blocks, expected the old and the new"
            assert blocks[0] in before, \
                f"{folder.name}: the OLD CODE block is not copied from before.py"
            assert blocks[1] in after, \
                f"{folder.name}: the NEW CODE block is not copied from after.py"
            assert change["old_code"] in before
            assert change["new_code"] in after


def test_the_prompt_never_names_the_case_folder():
    """Not the project, not the bug number, not the folder.

    Even the folder name is a label, and a label is a hint about which of a
    project's real bugs this is.
    """
    for folder in case_folders():
        changes = ev.extract_changes_from_files(str(folder / "before.py"),
                                                str(folder / "after.py"))
        for change in changes:
            prompt = test_generator.build_prompt(change)

            for clue in (folder.name, folder.name.replace("real_", ""),
                         "BugsInPy", "bug"):
                assert clue not in prompt, \
                    f"{folder.name}: the prompt names {clue!r}"


# ---------------------------------------------------------------------------
# Step 11: the single-prompt baseline
# ---------------------------------------------------------------------------
# scripts/baseline_single_prompt.py is the cheapest honest comparison against
# PRSentinel: one plain call to the same model, the same before file, the same
# after file, the same one changed function's old and new source, and nothing
# else. No pipeline, no mutation, no rerun loop, no judge.
#
# It is allowed to name the folder, because ALLOWED_ELSEWHERE at the top of this
# file says so. Two things it must not do:
#
# 1. Let the prompt be improved after the numbers are in. The prompt is a frozen
#    constant, and the first test below holds it character for character. A
#    baseline that can be rewritten once the result is known is not a baseline.
#
# 2. Let the two arms be scored by different code. read_report_numbers is
#    imported from eval_real_cases.py rather than copied, and the runner's own
#    evaluate_tests labels the reply, so "caught the bug" means one thing on both
#    sides of the table.
#
# None of the tests below call a model. Where a number is needed it is made up by
# hand, or a fake ask_llm is put in place of the real one.

BASELINE_SCRIPT = PROJECT / "scripts" / "baseline_single_prompt.py"

bsp = load_script(BASELINE_SCRIPT)

# The prompt exactly as it was frozen on 2026-10-02, before any run. If this ever
# has to change, the change is a decision about the comparison and belongs in the
# commit message, not in a quiet edit.
FROZEN_PROMPT = """\
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

Please write pytest tests that check the new code still behaves like the old code.

Rules for your answer:
- Import the function from a module named `target`, for example: `from target import <<NAME>>`
- Reply with pytest code only.
- Put all of it in one single code block.
- Do not explain anything.
"""

FROZEN_ON = "2026-10-02"


def baseline_script_tree():
    return ast.parse(BASELINE_SCRIPT.read_text(encoding="utf-8"))


def a_saved_report(**overrides):
    """One finished PRSentinel report, built by hand.

    Shaped like the five real ones that are committed, so the tests exercise the
    reading code against the same keys those files carry.
    """
    report = {
        "name": "some_case",
        "before": "before.py",
        "after": "after.py",
        "fallback": False,
        "gemini_answers": 0,
        "tests_source": "generated",
        "repair": False,
        "functions": [{
            "function": "some_function",
            "change_type": "modified",
            "counts": {test_runner.CATCHES_CHANGE: 2,
                       test_runner.TEST_WRONG_ON_BEFORE: 1,
                       test_runner.NO_SIGNAL: 3,
                       test_runner.ODD: 0},
            "judgements": [],
            "test_file": "test_some_function.py",
        }],
    }
    report.update(overrides)
    return report


def a_baseline_row(name="some_case", group="real", stopped="", tests=6,
                   catches=0, wrong=0, caught="no", older=False):
    """One finished baseline row, the way run_case builds it.

    Numbers are made up. Nothing here runs anything and nothing spends a token.
    """
    return {
        "case": name,
        "group": group,
        "stopped": stopped,
        "base": {"stopped": stopped, "tests": tests, "catches_change": catches,
                 "wrong_on_before": wrong, "caught": caught},
        "prs": {"tests": 24, "catches_change": 5, "caught": "yes",
                "tests_from": "generated", "fallback": "off", "gemini": "0",
                "older": ["fallback"] if older else []},
        "project_test": "CATCHES_CHANGE",
        "saved": "",
    }


def the_five_rows():
    """One row per case, in the order the script runs them."""
    return [
        a_baseline_row("real_PySnooper_bug3", "real", tests=4, catches=0),
        a_baseline_row("real_youtube-dl_bug3", "real", tests=19, wrong=3),
        a_baseline_row("real_youtube-dl_bug43", "real", tests=6, catches=2,
                       caught="yes"),
        a_baseline_row("round1_off_by_one", "synthetic", tests=11, catches=1,
                       caught="yes", ),
        a_baseline_row("round2_mutable_default", "synthetic", tests=9,
                       catches=4, caught="yes"),
    ]


# --- the prompt is frozen --------------------------------------------------

def test_the_baseline_script_is_where_it_says_it_is():
    """So the guards below are guarding something that exists."""
    assert BASELINE_SCRIPT.is_file()


def test_the_baseline_prompt_is_frozen_character_for_character():
    """The one that matters most.

    The prompt was written before any run and is not to be touched afterwards. An
    evaluation whose baseline can be improved once the result is known measures
    the improvement rather than the machinery.
    """
    assert bsp.PROMPT_TEMPLATE == FROZEN_PROMPT


def test_the_baseline_prompt_says_when_it_was_frozen():
    """So somebody reading the script knows which run the text belongs to."""
    assert bsp.FROZEN_ON == FROZEN_ON


def test_the_baseline_prompt_is_the_only_thing_that_varies_by_case():
    """Checked over every case, for real.

    The only things that change between two prompts are the function's name and
    the two blocks of code. If anything else moved, two cases would have been
    asked different questions and one table row would not be comparable with
    another.

    The two code blocks are taken out first. Both of them begin with the
    function's own name, so replacing the name first would leave the def line
    behind and the prompts would never match.
    """
    prompts = []
    for case in bsp.the_cases():
        change = bsp.the_modified_change(case)
        prompts.append(bsp.build_prompt(change)
                       .replace(change["old_code"] or "", "OLD")
                       .replace(change["new_code"] or "", "NEW")
                       .replace(change["name"], "NAME"))

    assert prompts, "no prompts were built, so this would pass for the wrong reason"
    assert len(set(prompts)) == 1, \
        "two cases were asked different questions once the function and its two " \
        "code blocks are taken out"


def test_the_baseline_prompt_carries_no_edge_case_advice():
    """Plain task only, and the test says so out loud.

    The pipeline prompt tells the model to look for anything the change could
    have made worse and lists the edge cases to cover. None of that is here, and
    that difference is part of what is being compared, so it is pinned by a test
    rather than left to memory.
    """
    for advice in ("Look for anything the change could have made worse",
                   "edge cases",
                   "empty input",
                   "size of zero",
                   "CHANGED LINE NUMBERS"):
        assert advice not in bsp.PROMPT_TEMPLATE, \
            f"the baseline prompt carries pipeline advice: {advice!r}"


def test_the_baseline_prompt_does_say_what_the_task_is():
    """The positive half of the test above, so it cannot be satisfied by deleting
    the whole prompt and leaving three words behind."""
    assert "check the new code still behaves like the old code" \
        in bsp.PROMPT_TEMPLATE
    assert "OLD CODE" in bsp.PROMPT_TEMPLATE
    assert "NEW CODE" in bsp.PROMPT_TEMPLATE


def test_the_baseline_prompt_names_the_module_the_runner_creates():
    """The tests have to import the name test_runner actually copies the file in
    as, or every reply imports a module that is not there."""
    assert f"`{test_generator.TARGET_MODULE}`" in bsp.PROMPT_TEMPLATE
    assert f"from {test_generator.TARGET_MODULE} import" \
        in bsp.PROMPT_TEMPLATE


def test_the_baseline_prompt_holds_only_code_from_before_and_after():
    """Two code blocks, each a copy out of the right file.

    Built for every case, so a prompt that somehow picked up a third block, or a
    block from somewhere else, is caught on the cases rather than in theory.
    """
    checked = 0

    for case in bsp.the_cases():
        folder = case["folder"]
        before = (folder / "before.py").read_text(encoding="utf-8")
        after = (folder / "after.py").read_text(encoding="utf-8")

        prompt = bsp.build_prompt(bsp.the_modified_change(case))
        blocks = re.findall(r"```python\n(.*?)```", prompt, re.DOTALL)
        checked += 1

        assert len(blocks) == 2, \
            f"{case['name']}: the prompt has {len(blocks)} code blocks, " \
            f"expected the old function and the new one"
        assert blocks[0] in before, \
            f"{case['name']}: the OLD CODE block is not copied from before.py"
        assert blocks[1] in after, \
            f"{case['name']}: the NEW CODE block is not copied from after.py"

    assert checked == 5, f"only {checked} prompts were checked, expected 5"


def test_the_baseline_prompt_never_names_the_case_folder():
    """Not the project, not the bug number, not the folder.

    Even the folder name is a label, and a label is a hint about which of a
    project's real bugs this is.
    """
    for case in bsp.the_cases():
        prompt = bsp.build_prompt(bsp.the_modified_change(case))

        for clue in (case["name"], case["name"].replace("real_", ""),
                     "BugsInPy", "bug", "youtube", "PySnooper"):
            assert clue not in prompt, \
                f"{case['name']}: the prompt names {clue!r}"


def test_the_baseline_generator_never_sees_a_line_from_the_give_away_files():
    """Built for real, for every case, and checked line by line.

    The prompts are made the way the script makes them, from the same extractor
    and the same frozen builder, so this is the text the model would actually be
    given.
    """
    checked = 0

    for case in bsp.the_cases():
        if case["group"] != "real":
            continue

        forbidden = []
        for name in FORBIDDEN_FOR_THE_GENERATOR:
            forbidden.extend(distinctive_lines(case["folder"], name))

        assert forbidden, \
            f"{case['name']}: no lines could be taken from the give-away files, " \
            f"so this test would pass for the wrong reason"

        prompt = bsp.build_prompt(bsp.the_modified_change(case))
        checked += 1

        for line in forbidden:
            assert line not in prompt, \
                f"{case['name']}: the prompt contains a line from a file the " \
                f"generator must not see: {line!r}"

    assert checked == 3, f"only {checked} real-case prompts were checked"


# --- one call per case, fallback off, no command line ----------------------

def test_the_baseline_script_has_no_command_line():
    """No argparse, and nothing read from sys.argv.

    Same reason as the evaluation script: a run that can be reconfigured by
    accident is not an evaluation run.
    """
    text = BASELINE_SCRIPT.read_text(encoding="utf-8")

    assert "argparse" not in text, "the baseline script grew a command line"
    assert "sys.argv" not in text, "the baseline script reads sys.argv"


def test_the_baseline_switches_fallback_off():
    """llm_client.ALLOW_FALLBACK is set to False.

    Checked as text because the value is set inside main(), which cannot be called
    here without spending the model calls it is there to avoid.
    """
    assert "llm_client.ALLOW_FALLBACK = False" in \
        BASELINE_SCRIPT.read_text(encoding="utf-8")


def test_the_baseline_passes_the_generation_temperature():
    """Both arms have to ask the model the same way.

    The temperature is passed positionally, so the test reads the second
    argument rather than looking for a keyword.
    """
    tree = baseline_script_tree()
    calls = calls_named(tree, "ask_llm")

    assert len(calls) == 1, \
        f"expected exactly one ask_llm call site, found {len(calls)}"

    arguments = calls[0].args
    assert len(arguments) == 2, \
        f"ask_llm is called with {len(arguments)} positional arguments, " \
        f"expected the prompt and the temperature"

    second = arguments[1]
    assert isinstance(second, ast.Attribute), \
        f"the temperature is {ast.unparse(second)}, not a plain setting"
    assert second.attr == "GENERATION_TEMPERATURE", \
        f"the baseline is asked at {ast.unparse(second)}, which is not the " \
        f"pipeline's generation setting"


def test_the_baseline_and_the_pipeline_are_asked_at_the_same_temperature():
    """The two arms, side by side, from the two call sites themselves.

    The pipeline's is in test_generator.build_prompt's caller; this one is in the
    baseline. Both have to be config.GENERATION_TEMPERATURE, or a difference
    between the arms would be down to that rather than to the machinery.
    """
    pipeline_call = calls_named(
        ast.parse((SRC / "test_generator.py").read_text(encoding="utf-8")),
        "ask_llm")
    assert pipeline_call, "the generator no longer calls ask_llm"

    baseline_call = calls_named(baseline_script_tree(), "ask_llm")

    def temperature_of(call):
        assert len(call.args) == 2, \
            f"ask_llm is called with {len(call.args)} positional arguments"
        return ast.unparse(call.args[1])

    assert temperature_of(pipeline_call[0]) == temperature_of(baseline_call[0]) \
        == "config.GENERATION_TEMPERATURE"


def test_the_baseline_makes_exactly_one_call_per_case():
    """One prompt per case, which is the whole point of the cheapest baseline."""
    assert len(calls_named(baseline_script_tree(), "ask_llm")) == 1
    assert len(bsp.the_cases()) == 5


def test_the_baseline_script_names_no_api_key():
    """This is the script that will be run with both keys in the session.

    It reads them through llm_client and has nothing to do with them itself.
    """
    text = BASELINE_SCRIPT.read_text(encoding="utf-8")

    assert "GROQ_API_KEY" not in text
    assert "GEMINI_API_KEY" not in text


def test_the_baseline_script_never_overwrites_a_saved_reply():
    """A saved reply is the only record of one live run.

    The check happens in check_case, before the model is asked, so a second run
    costs nothing rather than one case's worth of allowance.
    """
    function = next(node for node in baseline_script_tree().body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "check_case")
    names = [call_name for statement in function.body
             for call_name in [ast.unparse(statement)]]

    assert any("saved_test_file" in text for text in names), \
        "check_case does not work out where the reply would be saved"
    assert any("exists()" in text for text in names), \
        "check_case never asks whether that file is already there"


def test_the_baseline_refuses_when_the_saved_report_is_missing(monkeypatch):
    """The other half of the comparison has to exist before this half is spent.

    Run against a fake case whose report path points at a file that is not there.
    Nothing on disk is touched, and the test proves the refusal instead of
    assuming it.
    """
    fake = {"name": "no_such_case", "group": "real",
            "folder": case_folders()[0],
            "report": PROJECT / "reports" / "real_cases" / "not_saved.json"}
    monkeypatch.setattr(bsp, "the_cases", lambda: [fake])

    with pytest.raises(bsp.RefusedRun) as caught:
        bsp.check_case(fake)

    assert "not_saved.json" in str(caught.value)
    assert "No model calls were made" in str(caught.value)


def test_the_baseline_refuses_a_case_with_more_than_one_modified_function(tmp_path,
                                                                       monkeypatch):
    """One prompt per case, so one function per case.

    A second modified function would mean guessing which one the prompt is about,
    and a guess is worse than stopping. Proven by feeding the function a folder
    whose before and after files each hold two different modified functions, so
    the real cases are never touched and nothing is guessed.
    """
    before = tmp_path / "before.py"
    after = tmp_path / "after.py"
    before.write_text("def one(x):\n    return x + 1\n\n\n"
                      "def two(x):\n    return x * 2\n", encoding="utf-8")
    after.write_text("def one(x):\n    return x + 2\n\n\n"
                     "def two(x):\n    return x * 3\n", encoding="utf-8")

    fake = {"name": "two_of_them", "group": "real", "folder": tmp_path,
            "report": PROJECT / "reports" / "round1_off_by_one.json"}

    with pytest.raises(bsp.RefusedRun) as caught:
        bsp.the_modified_change(fake)

    assert "2 modified functions" in str(caught.value)
    assert "No model calls were made" in str(caught.value)


def test_the_baseline_prompt_still_builds_when_the_old_code_is_missing():
    """Documented behaviour, pinned so it cannot change unnoticed.

    the_modified_change refuses a case whose old version cannot be read, so this
    cannot happen on a real case. build_prompt itself still substitutes whatever
    it is given rather than raising, which keeps the function total.
    """
    prompt = bsp.build_prompt({"name": "brand_new", "old_code": None,
                               "new_code": "def brand_new():\n    return 1\n"})

    assert "OLD CODE:\n```python\n\n```" in prompt
    assert "brand_new" in prompt


# --- yes and no -----------------------------------------------------------

def test_caught_is_yes_when_one_test_catches_the_change():
    """The yes side, built the way score_reply builds it."""
    results = [{"name": f"test_{n}", "label": test_runner.NO_SIGNAL}
               for n in range(4)]
    results[2]["label"] = test_runner.CATCHES_CHANGE

    scored = bsp.score_reply(results)

    assert scored["caught"] == "yes"
    assert scored["catches_change"] == 1
    assert scored["tests"] == 4


def test_caught_is_no_when_nothing_catches_the_change():
    """The no side. Everything passed both ways, which is NO_SIGNAL throughout."""
    results = [{"name": f"test_{n}", "label": test_runner.NO_SIGNAL}
               for n in range(16)]

    scored = bsp.score_reply(results)

    assert scored["caught"] == "no"
    assert scored["catches_change"] == 0
    assert scored["wrong_on_before"] == 0


def test_wrong_on_before_is_counted_separately_from_catches():
    """A test that fails on before.py cannot show the change did anything, so it
    is its own column and it is not counted as having caught anything."""
    results = [
        {"name": "test_a", "label": test_runner.CATCHES_CHANGE},
        {"name": "test_b", "label": test_runner.TEST_WRONG_ON_BEFORE},
        {"name": "test_c", "label": test_runner.TEST_WRONG_ON_BEFORE},
        {"name": "test_d", "label": test_runner.ODD},
    ]

    scored = bsp.score_reply(results)

    assert scored["catches_change"] == 1
    assert scored["wrong_on_before"] == 2
    assert scored["tests"] == 4
    assert scored["caught"] == "yes"


def test_a_reply_with_no_code_block_is_stopped_rather_than_zero():
    """No measurement is not a score of zero.

    Zero would read as "the model looked and found nothing", which is a different
    claim and a much stronger one.
    """
    scored = bsp.score_reply([])

    assert scored["stopped"]
    assert "caught" not in scored
    assert "tests" not in scored


def test_a_file_that_could_not_be_run_is_stopped_rather_than_zero():
    """One row named after the whole file means pytest could not load it."""
    scored = bsp.score_reply([{"name": test_runner.WHOLE_FILE,
                               "label": test_runner.TEST_WRONG_ON_BEFORE,
                               "detail": "ImportError: no module named target"}])

    assert scored["stopped"]
    assert "no module named target" in scored["stopped"]


def test_a_stopped_case_prints_no_numbers():
    """Checked on the real printer, because that is where a zero would leak."""
    row = a_baseline_row(stopped="the reply had no code block in it")

    line = bsp.case_line(row)

    assert "STOPPED" in line
    for leaked in ("tests ", "CATCHES_CHANGE ", "caught "):
        assert leaked not in line, f"a stopped case printed {leaked!r}"


# --- a stopped run prints no table ----------------------------------------

def test_a_daily_limit_prints_no_table(monkeypatch, capsys, tmp_path):
    """The whole run ends, and nothing is totalled.

    A table with one case filled in and four blank looks like a run that found
    nothing in those four, when in fact it never asked. So no table at all.

    Two things are kept out of the way first, or this test would start failing
    the day the baseline is actually run:

      * main() switches llm_client.ALLOW_FALLBACK off and does not put it back.
      * check_case refuses when a reply is already saved, which after a live run
        it will be. saved_test_file is pointed at a temporary folder so that
        check is satisfied without touching the real saved replies.
    """
    was_allowed = llm_client.ALLOW_FALLBACK

    monkeypatch.setattr(
        bsp, "saved_test_file",
        lambda case, change: tmp_path / case["name"] / f"test_{change['name']}.py")

    def out_of_allowance(prompt, temperature=None):
        raise llm_client.DailyLimitReached("Groq says the daily limit is reached")

    monkeypatch.setattr(llm_client, "ask_llm", out_of_allowance)

    try:
        exit_code = bsp.main()
    finally:
        llm_client.ALLOW_FALLBACK = was_allowed

    printed = capsys.readouterr().out

    assert exit_code == pipeline.EXIT_DAILY_LIMIT == 6
    assert "THE RUN STOPPED EARLY" in printed
    assert "BOTH ARMS, SIDE BY SIDE" not in printed, \
        "a table was printed after the run stopped"
    assert "caught the bug" not in printed, \
        "a subtotal was printed after the run stopped"
    assert llm_client.ALLOW_FALLBACK is was_allowed, \
        "the fallback setting was left changed"


def test_a_daily_limit_still_works_once_the_replies_are_saved(monkeypatch,
                                                             tmp_path):
    """The same run with a saved reply already in place, which is what the state
    will be after the live run.

    Without this, the test above would be the only thing standing between a
    finished run and a red suite, and it would be red for the wrong reason.
    """
    monkeypatch.setattr(
        bsp, "the_cases",
        lambda: [{"name": "one_case", "group": "real",
                  "folder": case_folders()[0],
                  "report": PROJECT / "reports" / "real_cases"
                            / "real_youtube-dl_bug43.json"}])

    def already_saved(case, change):
        target = tmp_path / case["name"] / f"test_{change['name']}.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_nothing():\n    pass\n", encoding="utf-8")
        return target

    monkeypatch.setattr(bsp, "saved_test_file", already_saved)

    def out_of_allowance(prompt, temperature=None):
        raise llm_client.DailyLimitReached("out for the day")

    monkeypatch.setattr(llm_client, "ask_llm", out_of_allowance)

    assert bsp.main() == 2, \
        "a saved reply should stop the run as a refusal, before any call"


def test_the_stopped_notice_names_only_the_cases_that_finished(capsys):
    """And says the rest were never asked, so nothing is known about them."""
    rows = [a_baseline_row("real_youtube-dl_bug43", "real", tests=6, catches=2,
                           caught="yes")]

    bsp.print_stopped_notice(rows, "out of allowance")
    printed = capsys.readouterr().out

    assert "real_youtube-dl_bug43" in printed
    for missing in ("round1_off_by_one", "round2_mutable_default"):
        assert missing not in printed


def test_the_script_uses_the_six_exit_code():
    """And the two for a refusal, which is the number pipeline.main() uses."""
    assert bsp.EXIT_REFUSED == pipeline.EXIT_DAILY_LIMIT - 4 == 2


# --- reading the saved reports --------------------------------------------

def test_a_saved_report_is_read_for_the_prsentinel_side():
    """The happy path, on a report shaped like the five committed ones."""
    read = bsp.read_prsentinel(a_saved_report())

    assert read["tests"] == 6
    assert read["catches_change"] == 2
    assert read["caught"] == "yes"
    assert read["tests_from"] == "generated"
    assert read["fallback"] == "off"
    assert read["gemini"] == "0"
    assert read["older"] == []


def test_fresh_generation_and_a_frozen_baseline_copy_read_differently():
    """The column that keeps the two synthetic rows honest.

    If both read as "generated" a reader would assume PRSentinel generated fresh
    on those two rows too, when their tests came from baselines/ instead.
    """
    generated = bsp.read_prsentinel(a_saved_report(tests_source="generated"))
    copied = bsp.read_prsentinel(
        a_saved_report(tests_source="reused from baselines"))

    assert generated["tests_from"] == "generated"
    assert copied["tests_from"] == "baseline copy"
    assert generated["tests_from"] != copied["tests_from"]


def test_a_report_without_the_provenance_keys_is_marked_an_older_report():
    """It says so rather than printing a blank that would read as a zero."""
    report = a_saved_report()
    del report["fallback"]
    del report["gemini_answers"]

    read = bsp.read_prsentinel(report)

    assert read["older"] == ["fallback", "gemini_answers"]
    assert read["fallback"] == "older report"
    assert read["gemini"] == "older report"


def test_an_older_report_is_named_on_the_output(capsys):
    """The reader is told which rows are affected, not left to spot them."""
    rows = the_five_rows()
    rows[0]["prs"]["older"] = ["fallback"]
    rows[0]["prs"]["fallback"] = "older report"
    rows[0]["prs"]["gemini"] = "older report"

    bsp.print_table(rows)
    printed = capsys.readouterr().out

    assert "Older report" in printed
    assert "real_PySnooper_bug3" in printed


def test_both_arms_are_scored_by_the_same_function():
    """The comparison rests on this, so it is checked rather than assumed.

    read_report_numbers is imported from eval_real_cases.py rather than copied, so
    the PRSentinel half of the table is counted by the very function that
    produced the 1-of-3 headline for the real cases.

    The check is on the file the function came from and on the baseline script
    not having one of its own, rather than on the two objects being identical.
    Each script loads its siblings for itself through importlib, so the two
    copies are separate objects with the same source. Same source from one file
    is the guarantee that matters: a copy is what would drift.
    """
    defined_here = [node.name for node in ast.walk(baseline_script_tree())
                    if isinstance(node, ast.FunctionDef)]

    assert "read_report_numbers" not in defined_here, \
        "the baseline script has a read_report_numbers of its own, so the two " \
        "arms can be scored by two different rules"

    from_file = Path(bsp.ev.read_report_numbers.__code__.co_filename).resolve()
    assert from_file == EVAL_SCRIPT.resolve(), \
        f"read_report_numbers came from {from_file}, not from " \
        f"{EVAL_SCRIPT.resolve()}"

    assert bsp.read_prsentinel(
        a_saved_report())["tests"] == ev.read_report_numbers(
        a_saved_report())["tests"]


# --- the table ------------------------------------------------------------

def test_the_table_puts_both_arms_on_one_row(capsys):
    """Side by side, on one row per case, not one table after the other.

    Read as the header row really comes out, rather than as the tuple, so a
    column cannot be quietly dropped without a test noticing.
    """
    bsp.print_table(the_five_rows())
    printed = capsys.readouterr().out

    header = [line for line in printed.splitlines()
              if "PRS tests" in line and "CATCHES" in line]
    assert header, f"no header row found in:\n{printed}"

    for column in ("tests", "CATCHES", "WRONG_ON_BEFORE", "caught",
                   "PRS tests", "PRS CATCHES", "PRS caught", "PRS tests from",
                   "PRS fallback", "PRS gemini", "project test"):
        assert column in header[0], f"the header has no {column!r} column"


def test_the_table_has_one_row_per_case(capsys):
    """Five cases, five rows, each naming its case exactly once."""
    bsp.print_table(the_five_rows())
    printed = capsys.readouterr().out

    for row in the_five_rows():
        named = [line for line in printed.splitlines()
                 if line.startswith(row["case"])]
        assert len(named) == 1, \
            f"{row['case']} appears on {len(named)} lines of the table"


def test_the_table_covers_all_five_cases_in_one_row_each():
    """Checked on the cells as well, so a short row cannot slip past the text."""
    cells = [bsp.table_cells(row) for row in the_five_rows()]

    assert len(cells) == 5
    assert len({row["case"] for row in the_five_rows()}) == 5
    for line in cells:
        assert len(line) == len(bsp.TABLE_HEADERS)


def test_the_table_shows_which_tests_prsentinel_used():
    """The tests from column, which is what the footnote is about."""
    rows = the_five_rows()
    rows[3]["prs"]["tests_from"] = "baseline copy"

    header = bsp.TABLE_HEADERS.index("PRS tests from")
    assert bsp.table_cells(rows[3])[header] == "baseline copy"
    assert bsp.table_cells(rows[0])[header] == "generated"


def test_the_table_shows_fallback_and_gemini_for_every_row():
    """Read out of the saved reports, so the two runs' provenance is visible."""
    header_fallback = bsp.TABLE_HEADERS.index("PRS fallback")
    header_gemini = bsp.TABLE_HEADERS.index("PRS gemini")

    for row in the_five_rows():
        assert bsp.table_cells(row)[header_fallback] == "off"
        assert bsp.table_cells(row)[header_gemini] == "0"


def test_a_stopped_row_prints_a_dash_and_not_a_zero():
    """A dash says "not measured". A 0 would say "looked and found nothing"."""
    rows = the_five_rows()
    rows[0] = a_baseline_row("real_PySnooper_bug3", "real",
                             stopped="the reply had no code block in it")

    cells = bsp.table_cells(rows[0])
    for position in (1, 2, 3, 4):
        assert cells[position] == bsp.BLANK == "-"


# --- the subtotals and the footnote ---------------------------------------

def test_the_subtotals_are_labelled_and_never_merged():
    """Real cases on one line, synthetic on another, and no grand total.

    A single number across two different kinds of case invites reading it as a
    rate, which five observations cannot be.
    """
    real_line = bsp.subtotal("real cases", the_five_rows(), "real")
    synthetic_line = bsp.subtotal("synthetic cases", the_five_rows(), "synthetic")

    assert real_line == "  real cases: 1 of 3 caught the bug"
    assert synthetic_line == "  synthetic cases: 2 of 2 caught the bug"
    assert real_line != synthetic_line


def test_a_subtotal_does_not_count_an_unmeasured_case_as_a_miss():
    """A stopped case is named, not folded into the denominator.

    Counting it as not caught would be the exact misreading the stopped case
    convention exists to prevent.
    """
    rows = the_five_rows()
    rows[0] = a_baseline_row("real_PySnooper_bug3", "real",
                             stopped="the reply had no code block in it")

    line = bsp.subtotal("real cases", rows, "real")

    assert "1 of 3" in line
    assert "not measured at all" in line
    assert "this is not a rate" in line


def test_the_footnote_says_why_the_two_synthetic_rows_are_not_like_for_like(capsys):
    """Without it, a reader sees two rows where PRSentinel did well and has no way
    to know its side of them was frozen while the baseline's side is fresh."""
    bsp.print_table(the_five_rows())
    printed = capsys.readouterr().out

    assert "Footnote on the two synthetic rows" in printed
    assert "frozen hand-checked baseline tests" in printed
    assert "a fresh call on all five" in printed


def test_the_footnote_is_left_off_when_there_are_no_synthetic_rows(capsys):
    """So the note cannot end up claiming something about rows that are not there."""
    bsp.print_table(the_five_rows()[:3])
    printed = capsys.readouterr().out

    assert "Footnote on the two synthetic rows" not in printed


# --- the five cases --------------------------------------------------------

def test_the_baseline_runs_on_five_cases_in_two_groups():
    """Three real bugs and two synthetic rounds, and the split is explicit."""
    cases = bsp.the_cases()

    assert len(cases) == 5
    assert [case["group"] for case in cases].count("real") == 3
    assert [case["group"] for case in cases].count("synthetic") == 2


def test_every_case_has_exactly_one_modified_function():
    """The precondition that lets one prompt per case be honest."""
    for case in bsp.the_cases():
        change = bsp.the_modified_change(case)

        assert change["change_type"] == "modified"
        assert change["old_code"], \
            f"{case['name']}: the prompt would be missing the old version"
        assert change["new_code"], \
            f"{case['name']}: the prompt would be missing the new version"


def test_every_case_saved_report_is_there():
    """So the other half of every row can be printed."""
    for case in bsp.the_cases():
        assert case["report"].is_file(), f"{case['report']} is missing"


def test_the_project_test_is_only_asked_where_there_is_one():
    """The two synthetic folders hold no existing_test.py, so they report n/a
    rather than a label that was never measured."""
    for case in bsp.the_cases():
        if case["group"] == "real":
            assert (case["folder"] / "existing_test.py").is_file()
        else:
            assert not (case["folder"] / "existing_test.py").exists()


def test_the_projects_own_test_is_read_after_the_generator_is_finished():
    """The order inside run_case is what makes that true.

    The model is asked first, its reply is scored second, and the project's own
    test is read last. By then the generator has written its file, so there is no
    path from existing_test.py back to the prompt even in principle.
    """
    function = next(node for node in baseline_script_tree().body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "run_case")

    order = []
    for statement in function.body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                label = getattr(node.func, "attr", None) or getattr(
                    node.func, "id", "")
                if label in ("ask_llm", "evaluate_tests", "project_test_result"):
                    order.append(label)
                    break

    assert order == ["ask_llm", "evaluate_tests", "project_test_result"], \
        f"run_case does {order}. The project's own test has to be read after " \
        f"the model has been asked and its reply scored."
