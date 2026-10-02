"""Tests for the real bug cases in examples/real_cases.

Two things are guarded here, and both guard against the same failure: the cases
quietly ceasing to be real evidence.

1. Nothing in src/prsentinel may reach into examples/real_cases. These three
   cases are for evaluation only. If the pipeline could read them, then a run
   could be pointed at them, and every number from that run would stop being an
   evaluation and start being a tuning result. The only things allowed to name
   the folder are the check script, and the evaluation script that runs the
   pipeline over the cases. Both are named in ALLOWED_ELSEWHERE below, so the
   exception is a deliberate line in this file rather than a gap in it.

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

from prsentinel import classifier, test_generator, test_runner

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
# Two, and both are named here on purpose. If a third ever appears it has to be
# added to this tuple in the same commit that created it, so that widening the
# exception is something somebody chose rather than something that happened.
ALLOWED_ELSEWHERE = (
    "scripts/check_real_cases.py",
    "scripts/eval_real_cases.py",
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
    """Both scripts in scripts/ are tools, not package members.

    If the pipeline could import either, the guard above would be the only thing
    stopping the two from becoming entangled.
    """
    offenders = []
    for path in source_files():
        text = path.read_text(encoding="utf-8")
        if "check_real_cases" in text or "eval_real_cases" in text:
            offenders.append(path.name)

    assert not offenders, (
        f"these files name a script from scripts/: {', '.join(offenders)}. "
        f"Those scripts stand outside the package on purpose.")


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
