r"""Check that every folder in examples/real_cases really is a real bug case.

Run it with:  .venv\Scripts\python.exe scripts\check_real_cases.py

What it does, for each case folder:

1. Runs the project's own test file through prsentinel.test_runner twice: once
   with before.py as the module, once with after.py. That is the same code path
   the pipeline uses, so a result here means what it would mean there. The two
   runs are then read as one of test_runner's own four labels.

2. Runs the witness in witness.md twice, the same way, and requires the two
   outputs to be different. A witness that agrees on both versions means the bug
   does not reproduce here, so the case is REJECTED and this script says so.
   It does not try to fix it or work around it.

3. Compares what the witness actually printed with what witness.md documents it
   printing. A witness that reproduces but prints something other than its own
   documentation is REJECTED too, because the documentation is part of the case.

There is no AI anywhere in this file. It calls no model, reads no API key and
needs no network.

A case is GOOD when the witness reproduces AND matches its documentation AND the
project's own test ran. A NO_SIGNAL label from that test is not a failure here:
some real projects ship a test that cannot see their own bug, and reporting that
plainly is the honest result.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from prsentinel import test_runner as tr  # noqa: E402

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
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

# A case's own verdict, which is separate from test_runner's test label.
GOOD = "GOOD"
REJECTED = "REJECTED"

RULE = "=" * 74

# The child process gets a stripped environment, so no key can reach a witness.
WITNESS_ENV_NAMES = ("PATH", "SYSTEMROOT", "TEMP", "TMP")


# ---------------------------------------------------------------------------
# The one judgement: what do the two runs of the project's test file mean?
# ---------------------------------------------------------------------------

def all_passed(result):
    """Did every test in this run pass? An empty run is not a pass."""
    return bool(result["tests"]) and all(
        value == tr.PASSED for value in result["tests"].values())


def test_label(before_result, after_result):
    """Name what the project's own test did, using test_runner's own labels.

    pipeline.py has a ready-made way of turning two results into a label, but
    pipeline.py is the code we must not reach into from here. These are the same
    four labels with the same meanings, written out so this script stands alone.
    """
    for result in (before_result, after_result):
        if result["status"] == tr.ERROR:
            return tr.ERROR, "the test file could not be run at all"
        if result["status"] == tr.TIMEOUT:
            return tr.TIMEOUT, "the test file took too long to run"

    before_ok = all_passed(before_result)
    after_ok = all_passed(after_result)

    if before_ok and not after_ok:
        return tr.CATCHES_CHANGE, \
            "passes on the correct code, fails on the buggy code"
    if not before_ok and not after_ok:
        return tr.TEST_WRONG_ON_BEFORE, \
            "fails on both, so it is not measuring this bug"
    if not before_ok and after_ok:
        return tr.ODD, \
            "fails on the correct code and passes on the buggy code"
    return tr.NO_SIGNAL, \
        "passes on both, so it cannot tell the two versions apart"


# ---------------------------------------------------------------------------
# Running the project's own test file.
# ---------------------------------------------------------------------------

def print_test_run(result, indent):
    """Print what one run did, one line per test."""
    if result["status"] != tr.OK:
        detail = result.get("error") or result["status"]
        print(f"{indent}the file did not run: {detail}")
        return
    for name in sorted(result["tests"]):
        state = result["tests"][name]
        line = f"{indent}{state:<8} {name}"
        if state != tr.PASSED and name in result["failures"]:
            line += f"  |  {result['failures'][name]}"
        print(line)


# ---------------------------------------------------------------------------
# The witness. It lives in witness.md as a fenced python block, so the case and
# its own documentation cannot drift apart.
# ---------------------------------------------------------------------------

WITNESS_BLOCK = re.compile(r"```python\n(.*?)```", re.DOTALL)
DOCUMENTED_OUTPUT = re.compile(r"`before\.py`[^`]*:\s*\n+```\n(.*?)\n```", re.DOTALL)
DOCUMENTED_AFTER = re.compile(r"`after\.py`[^`]*:\s*\n+```\n(.*?)\n```", re.DOTALL)


def read_witness(case):
    """Pull the runnable python block out of witness.md."""
    text = (case / "witness.md").read_text(encoding="utf-8")
    blocks = WITNESS_BLOCK.findall(text)
    if not blocks:
        raise ValueError("witness.md has no ```python block")
    if len(blocks) > 1:
        raise ValueError("witness.md has more than one ```python block")
    return blocks[0]


def read_documented_outputs(case):
    """Pull the before.py and after.py outputs witness.md claims."""
    text = (case / "witness.md").read_text(encoding="utf-8")
    before = DOCUMENTED_OUTPUT.search(text)
    after = DOCUMENTED_AFTER.search(text)
    if not before or not after:
        raise ValueError(
            "witness.md must document what before.py prints and what after.py "
            "prints, each in its own ``` block under a line naming that file")
    return before.group(1), after.group(1)


def run_witness(code, case, version):
    """Run the witness with case/<version>.py available to it as `target`.

    This makes its own temporary folder rather than going through test_runner,
    because a witness is a script that prints, not a pytest file.
    """
    work = Path(tempfile.mkdtemp(prefix="prsentinel_witness_"))
    try:
        (work / "target.py").write_bytes((case / f"{version}.py").read_bytes())
        (work / "witness.py").write_text(code, encoding="utf-8")

        environment = {}
        for name in WITNESS_ENV_NAMES:
            if name in os.environ:
                environment[name] = os.environ[name]
        environment["TEMP"] = str(work)
        environment["TMP"] = str(work)

        return subprocess.run(
            [sys.executable, "witness.py"],
            cwd=str(work),
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        # The witness may leave files open, so clearing read-only first and
        # ignoring what is still locked keeps a half-cleaned folder from being
        # left in TEMP for good.
        def unlock(func, path, _):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass

        shutil.rmtree(work, onerror=unlock)


def witness_output(completed):
    """What the witness printed, or the error it died with.

    stdout is preferred, because that is what a witness is written to print.
    Only when stdout is empty do we fall back to the error, because a crash is a
    real and important difference between two versions.
    """
    if completed.stdout.strip():
        return completed.stdout.strip()
    error = next((line.strip() for line in reversed(completed.stderr.splitlines())
                  if line.strip()), "")
    return f"raised {error}" if error else "printed nothing and said nothing"


def matches_documentation(actual, documented):
    """Did the witness print what witness.md says it prints?

    The documentation is written the way a person writes it, so a blank line or
    different spacing should not fail a case. Each side is squeezed onto single
    lines and compared line by line.
    """
    def lines_of(text):
        return [" ".join(line.split())
                for line in text.splitlines() if line.strip()]

    return lines_of(actual) == lines_of(documented)


# ---------------------------------------------------------------------------
# One case.
# ---------------------------------------------------------------------------

def check_case(folder):
    """Check one case folder. Returns a dictionary of what was found."""
    found = {"name": folder.name, "verdict": GOOD, "label": "",
             "problems": [], "notes": []}
    report = [RULE, folder.name, RULE]
    found["report"] = report

    missing = [name for name in REQUIRED_FILES if not (folder / name).is_file()]
    if missing:
        found["verdict"] = REJECTED
        found["label"] = "not run"
        found["problems"].append(f"missing {', '.join(missing)}")
        report.append(f"  {REJECTED}: missing {', '.join(missing)}")
        return found

    # 1. The project's own test, through test_runner, on both versions.
    report.append("")
    report.append("  The project's own test, through prsentinel.test_runner:")
    before_result = tr.run_tests(str(folder / "before.py"),
                                 str(folder / "existing_test.py"))
    after_result = tr.run_tests(str(folder / "after.py"),
                                str(folder / "existing_test.py"))
    report.append("    on before.py (the correct code):")
    for line in run_lines(before_result):
        report.append(f"      {line}")
    report.append("    on after.py (the buggy code):")
    for line in run_lines(after_result):
        report.append(f"      {line}")

    label, meaning = test_label(before_result, after_result)
    found["label"] = label
    report.append(f"    -> {label}: {meaning}")
    if label in (tr.ERROR, tr.TIMEOUT):
        found["problems"].append(f"the project's own test did not run ({label})")

    # 2. The witness, on both versions.
    report.append("")
    report.append("  The witness, run on both versions:")
    try:
        code = read_witness(folder)
    except ValueError as error:
        found["verdict"] = REJECTED
        found["problems"].append(str(error))
        report.append(f"    {REJECTED}: {error}")
        return found

    before_out = witness_output(run_witness(code, folder, "before"))
    after_out = witness_output(run_witness(code, folder, "after"))
    report.append(f"    on before.py: {before_out}")
    report.append(f"    on after.py:  {after_out}")

    if before_out == after_out:
        found["problems"].append(
            "the witness gives the same output on both versions, so the bug does "
            f"not reproduce on Python {sys.version.split()[0]}. Rejected rather "
            "than worked around.")

    # 3. The witness against what witness.md says it prints.
    try:
        documented_before, documented_after = read_documented_outputs(folder)
    except ValueError as error:
        found["problems"].append(str(error))
    else:
        if not matches_documentation(before_out, documented_before):
            found["problems"].append(
                f"witness.md says before.py prints {documented_before.strip()!r} "
                f"but it printed {before_out!r}")
        if not matches_documentation(after_out, documented_after):
            found["problems"].append(
                f"witness.md says after.py prints {documented_after.strip()!r} "
                f"but it printed {after_out!r}")

    # 4. A NO_SIGNAL test label is a fact about the bug, not a problem here.
    if label == tr.NO_SIGNAL and not found["problems"]:
        note = (f"{tr.NO_SIGNAL} from the project's own test. That is a true fact "
                "about this bug, not a problem with this case.")
        found["notes"].append(note)
        report.append("")
        report.append(f"  {note}")

    report.append("")
    if found["problems"]:
        found["verdict"] = REJECTED
        report.append(f"  {REJECTED}:")
        for problem in found["problems"]:
            report.append(f"    - {problem}")
    else:
        report.append(f"  {GOOD}: the witness reproduces and matches witness.md.")

    return found


def run_lines(result):
    """One line per test, as plain strings, so they can go in a report."""
    if result["status"] != tr.OK:
        return [f"the file did not run: {result.get('error') or result['status']}"]
    lines = []
    for name in sorted(result["tests"]):
        state = result["tests"][name]
        line = f"{state:<8} {name}"
        if state != tr.PASSED and name in result["failures"]:
            line += f"  |  {result['failures'][name]}"
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# All of them.
# ---------------------------------------------------------------------------

def case_folders():
    if not CASES.is_dir():
        raise SystemExit(f"there is no {CASES}")
    folders = sorted(path for path in CASES.iterdir() if path.is_dir())
    if not folders:
        raise SystemExit(f"{CASES} has no case folders in it")
    return folders


def main():
    folders = case_folders()

    print(RULE)
    print("PRSentinel real-case check. No AI is used anywhere in this script.")
    print(f"Python {sys.version.split()[0]}")
    print(RULE)
    print(f"\n{len(folders)} case folders in examples/real_cases/")

    found_all = []
    for folder in folders:
        found = check_case(folder)
        found_all.append(found)
        print()
        for line in found["report"]:
            print(line)

    print(RULE)
    print("SUMMARY")
    print(RULE)
    width = max(len(f["name"]) for f in found_all)
    print(f"  {'case':<{width}}  {'case':<8}  {'the project test'}")
    for found in found_all:
        print(f"  {found['name']:<{width}}  {found['verdict']:<8}  "
              f"{found['label'] or '-'}")

    rejected = [f["name"] for f in found_all if f["verdict"] == REJECTED]
    good = len(found_all) - len(rejected)
    print(f"\n  {good} of {len(found_all)} reproduced.")
    for name in rejected:
        print(f"  REJECTED: {name}")

    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())