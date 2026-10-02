"""Tests for the real bug cases in examples/real_cases.

Two things are guarded here, and both guard against the same failure: the cases
quietly ceasing to be real evidence.

1. Nothing in src/prsentinel may reach into examples/real_cases. These three
   cases are for evaluation only. If the pipeline could read them, then a run
   could be pointed at them, and every number from that run would stop being an
   evaluation and start being a tuning result. The only things allowed to name
   the folder are the check script and, later, evaluation code written for the
   purpose. There is none yet, and these tests say so.

2. Each case folder must hold all seven files. A case missing its witness or its
   provenance cannot be checked, and a case that cannot be checked is not
   evidence of anything.

Neither test runs a case, runs pytest, or calls a model. They read files.
"""

import ast
from pathlib import Path

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

# The only place outside src/ that is allowed to name the real cases.
ALLOWED_ELSEWHERE = ("scripts/check_real_cases.py",)


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


def test_the_pipeline_does_not_import_the_check_script():
    """The check script is a tool, not part of the package.

    If the pipeline could import it, the guard above would be the only thing
    stopping the two from becoming entangled.
    """
    offenders = []
    for path in source_files():
        text = path.read_text(encoding="utf-8")
        if "check_real_cases" in text:
            offenders.append(path.name)

    assert not offenders, (
        f"these files name the check script: {', '.join(offenders)}. The check "
        f"script stands outside the package on purpose.")


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
    import re

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