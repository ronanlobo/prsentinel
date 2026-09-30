"""Run an AI-generated test file against a version of the module.

The idea: take one generated test file and run it twice, once against the old
module and once against the new one. Comparing the two runs tells us whether
the test actually noticed the change.

How it works:
1. Make a throwaway temporary folder.
2. Copy the module in as `target.py`, because that is the name the generated
   tests import. Copy the test file in under its own name.
3. Run pytest in a separate process inside that folder and ask for its
   built-in JUnit XML report, which tells us each test's result.
4. Read that XML back and turn it into a simple dictionary.

Nothing is ever written into `examples/` or `generated_tests/`. The
temporary folder is thrown away afterwards.

Safety: the child process never receives GROQ_API_KEY or GEMINI_API_KEY, so a
generated test cannot spend our money or read our keys.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from prsentinel import config

# ---------------------------------------------------------------------------
# The labels. They all live here so there is one place to look.
# Each test gets exactly one label, decided by its two results:
#
#   before passes, after fails -> CATCHES_CHANGE
#       The test noticed the change. This is the useful one.
#   before fails, after fails  -> TEST_WRONG_ON_BEFORE
#       The test fails even on the correct old code, so the test itself is
#       wrong or made up an expectation that never existed.
#   before fails, after passes -> ODD
#       The test failed on the correct code but passed on the changed code.
#       Usually the test expected the wrong thing and the change matched it.
#   before passes, after passes -> NO_SIGNAL
#       The test cannot tell the two versions apart, so it proves nothing.
# ---------------------------------------------------------------------------

CATCHES_CHANGE = "CATCHES_CHANGE"
TEST_WRONG_ON_BEFORE = "TEST_WRONG_ON_BEFORE"
ODD = "ODD"
NO_SIGNAL = "NO_SIGNAL"

# The labels, in the order we print them in the summary.
ALL_LABELS = (CATCHES_CHANGE, TEST_WRONG_ON_BEFORE, ODD, NO_SIGNAL)

# The overall status of one run.
OK = "ok"          # the file ran and we got results
TIMEOUT = "timeout"  # it took too long and we stopped it
ERROR = "error"      # the file could not even be loaded, e.g. a bad import

# The per-test results we report.
PASSED = "passed"
FAILED = "failed"
TEST_ERROR = "error"
SKIPPED = "skipped"

# The name the module is copied to, because that is what the tests import.
TARGET_MODULE = "target.py"

# Keys we must never pass on to the child process.
SECRET_ENV_NAMES = ("GROQ_API_KEY", "GEMINI_API_KEY")

# How many lines of the failure message we keep for the printed table, and how
# many characters that short version is limited to.
MESSAGE_LINES = 3
MESSAGE_CHARS = 200

# How much of the cleaned failure message we keep in the result data. The
# short version is only for reading; a classifier needs the longer text.
FULL_MESSAGE_CHARS = 1500

# Pytest adds this to the end of an assert message. It is only useful when you
# can actually run pytest yourself, so we take it out.
PYTEST_NOISE_PHRASES = (
    "Use -v to get more diff",
    "use -v to get more diff",
)

# The environment variable that tells a test which rerun it is on. It lets a
# test be flaky in a predictable way, and the variable dies with the process.
RUN_INDEX_ENV = "PRSENTINEL_RUN_INDEX"

# The verdicts rerun_failures can give one test.
ALWAYS_FAILS = "ALWAYS_FAILS"
ALWAYS_PASSES = "ALWAYS_PASSES"
FLAKY = "FLAKY"

# The name used in the table when the whole file failed to load, so there are
# no individual test names to show.
WHOLE_FILE = "(whole file)"


def label_for(before_result: str, after_result: str) -> str:
    """Return the label for a test that got these two results.

    An 'error' counts as a failure, because a test that cannot even run on
    the correct code is just as broken as one that fails an assertion.
    A 'skipped' test did not really run, so it is never a failure.
    """
    before_failed = before_result in (FAILED, TEST_ERROR)
    after_failed = after_result in (FAILED, TEST_ERROR)

    if before_failed and after_failed:
        return TEST_WRONG_ON_BEFORE
    if before_failed:
        return ODD
    if after_failed:
        return CATCHES_CHANGE
    return NO_SIGNAL


def clean_message(text: str) -> str:
    """Remove pytest's own wording from a failure message.

    Pytest adds 'Use -v to get more diff', which only helps if you can run
    pytest by hand. It is noise here, so we take it out and tidy the spacing.
    """
    if not text:
        return ""
    cleaned = text
    for phrase in PYTEST_NOISE_PHRASES:
        cleaned = cleaned.replace(phrase, "")
    # The removal can leave a space or a comma behind, so tidy that up.
    cleaned = cleaned.replace(" ,", ",").replace("  ", " ")
    return cleaned.strip()


def full_message(text: str) -> str:
    """Clean the message and keep up to FULL_MESSAGE_CHARS characters.

    This longer version goes into the result data, where something reading
    the results later has room to look at the whole thing.
    """
    cleaned = clean_message(text)
    if len(cleaned) > FULL_MESSAGE_CHARS:
        cleaned = cleaned[:FULL_MESSAGE_CHARS - 3] + "..."
    return cleaned


def _short_message(text: str) -> str:
    """Squeeze a failure message into one short line for the table.

    This is the version a person reads, so we clean it and then cut it down
    to a few lines and a limited number of characters.
    """
    cleaned = clean_message(text)
    if not cleaned:
        return ""
    # Keep only the first few useful lines.
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    message = " ".join(lines[:MESSAGE_LINES])
    if len(message) > MESSAGE_CHARS:
        message = message[:MESSAGE_CHARS - 3] + "..."
    return message


def split_param_id(test_name: str):
    """Split a pytest name into the function name and its parameter ID.

    pytest writes names like 'test_thing[some-id]'. A plain function has no
    brackets at all. Returns (function_name, param_id_or_None).
    """
    start = test_name.find("[")
    if start == -1 or not test_name.endswith("]"):
        return test_name, None
    return test_name[:start], test_name[start + 1:-1]


def readable_param_id(param_id):
    """Make a parameter ID clear to read, even when it is blank.

    An empty or whitespace-only ID would otherwise print as bare brackets,
    which is easy to misread. Blank IDs become '<empty>' or '<blank>'.
    Returns None when the test had no parameters at all.
    """
    if param_id is None:
        return None
    if param_id == "":
        return "<empty>"
    if param_id.strip() == "":
        return "<blank>"
    return param_id


def make_display_names(names) -> dict:
    """Build a short, readable, guaranteed-unique name for each test.

    Returns {unique_key: display_name}. The key stays the full pytest name so
    labelling still works per case, while the display name drops the file
    prefix and tidies up the parameter ID. If two cases would still end up
    with the same display name, '#1', '#2' and so on are added so every row
    can be told apart.
    """
    plain = {}

    # First pass: work out the plain name for each test.
    for name in names:
        function_part, param_part = split_param_id(name)
        # Drop the leading "test_file.py::" so the name is not needlessly long.
        if "::" in function_part:
            short_function = function_part.rsplit("::", 1)[-1]
        else:
            short_function = function_part

        readable = readable_param_id(param_part)
        if readable is None:
            plain[name] = short_function
        else:
            plain[name] = f"{short_function}[{readable}]"

    # Second pass: count how often each plain name is used.
    totals = {}
    for name in names:
        totals[plain[name]] = totals.get(plain[name], 0) + 1

    # Third pass: number the ones that were used more than once. We write to a
    # new dictionary so the plain names stay untouched for the next test.
    display = {}
    numbered = {}
    for name in names:
        base = plain[name]
        if totals[base] > 1:
            numbered[base] = numbered.get(base, 0) + 1
            display[name] = f"{base}#{numbered[base]}"
        else:
            display[name] = base

    return display


def _child_environment() -> dict:
    """Return a copy of the environment with our API keys taken out.

    The child process must never see the keys, so a generated test cannot
    read them or use them.
    """
    environment = dict(os.environ)
    for name in SECRET_ENV_NAMES:
        environment.pop(name, None)
    return environment


def _read_junit_xml(xml_path: Path, module_stem: str) -> dict:
    """Read pytest's XML report and return the result of each test.

    Returns {"tests", "failures", "failures_full", "file_error"}.
    "failures" is the short one-line version for printing. "failures_full"
    keeps much more of the message for whatever reads the results later.
    A file that could not even be imported gives no tests at all.
    """
    tests = {}
    failures = {}
    failures_full = {}

    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, OSError) as error:
        return {"tests": {}, "failures": {}, "failures_full": {},
                "file_error": f"no usable XML report ({error})"}

    for case in tree.iter("testcase"):
        name = case.get("name", "")
        classname = case.get("classname", "") or ""

        is_error = case.find("error") is not None

        # When a file cannot be imported, pytest still writes a testcase with
        # an empty classname and the module name as the name. That is not a
        # real test, it is the file failing to load, so we treat it as one.
        if is_error and not classname and name == module_stem:
            node = case.find("error")
            message = node.get("message") or (node.text or "")
            return {"tests": {}, "failures": {}, "failures_full": {},
                    "file_error": _short_message(message)}

        # pytest writes "class::name"; for plain functions classname is the file.
        full_name = f"{classname}::{name}" if classname else name

        message = ""
        if case.find("failure") is not None:
            result = FAILED
            node = case.find("failure")
            message = node.get("message") or (node.text or "")
        elif is_error:
            result = TEST_ERROR
            node = case.find("error")
            message = node.get("message") or (node.text or "")
        elif case.find("skipped") is not None:
            result = SKIPPED
        else:
            result = PASSED

        tests[full_name] = result
        if result in (FAILED, TEST_ERROR):
            failures[full_name] = _short_message(message)
            failures_full[full_name] = full_message(message)

    return {"tests": tests, "failures": failures,
            "failures_full": failures_full, "file_error": ""}


def run_tests(module_file, test_file, timeout_seconds=30, run_index=None) -> dict:
    """Run one test file against one version of the module.

    Returns a dictionary with:
      "status"        - OK, TIMEOUT or ERROR for the file as a whole
      "tests"         - {test name: passed / failed / error / skipped}
      "failures"      - {test name: short message} for the printed table
      "failures_full" - {test name: longer message} for anything reading it
      "error"         - a file-level message when status is ERROR

    run_index, when given, is passed to the child process as an environment
    variable. rerun_failures uses it so a flaky test can tell which rerun it
    is on. Nothing outside a temporary folder is ever written to.
    """
    module_path = Path(module_file)
    test_path = Path(test_file)

    for path in (module_path, test_path):
        if not path.is_file():
            return {"status": ERROR, "tests": {}, "failures": {},
                    "failures_full": {}, "error": f"cannot find that file: {path}"}

    work_dir = Path(tempfile.mkdtemp(prefix="prsentinel_run_"))
    try:
        # The module becomes target.py, which is what the tests import.
        shutil.copyfile(module_path, work_dir / TARGET_MODULE)
        shutil.copyfile(test_path, work_dir / test_path.name)

        report = work_dir / "results.xml"
        command = [
            sys.executable, "-m", "pytest", "-q",
            "-p", "no:cacheprovider",      # do not litter the folder
            "--junitxml", str(report),
            test_path.name,
        ]

        environment = _child_environment()
        if run_index is not None:
            environment[RUN_INDEX_ENV] = str(run_index)

        try:
            completed = subprocess.run(
                command,
                cwd=str(work_dir),
                env=environment,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            # We could not finish in time, so stop here and say so.
            return {"status": TIMEOUT, "tests": {}, "failures": {},
                    "failures_full": {},
                    "error": f"took longer than {timeout_seconds}s, so we stopped it"}

        if not report.is_file():
            return {"status": ERROR, "tests": {}, "failures": {},
                    "failures_full": {}, "error": "pytest produced no report file"}

        parsed = _read_junit_xml(report, test_path.stem)
        tests = parsed["tests"]
        failures = parsed["failures"]
        failures_full = parsed["failures_full"]
        file_error = parsed["file_error"]

        if not tests:
            # pytest could not load the file, so there is one file-level result.
            detail = file_error or _short_message(completed.stdout) \
                or "pytest could not collect the tests"
            return {"status": ERROR, "tests": {}, "failures": {},
                    "failures_full": {}, "error": detail}

        status = OK
        # pytest exit code 2 means it was interrupted, usually a bad import.
        if completed.returncode == 2:
            status = ERROR
            file_error = file_error or _short_message(completed.stdout)
        elif completed.returncode == 5:
            status = ERROR
            file_error = "pytest collected no tests at all"

        return {"status": status, "tests": tests, "failures": failures,
                "failures_full": failures_full, "error": file_error}

    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def rerun_failures(module_file, test_file, times=None) -> dict:
    """Run one test file again and again to see if it is flaky.

    A test is only believable if it gives the same answer every time. This
    runs the file `times` times (5 by default) against ONE version of the
    module, and counts how many times each test passed and failed.

    Returns:
      "status" - OK, TIMEOUT or ERROR for the file as a whole
      "times"  - how many reruns we actually did
      "tests"  - {test name: {"passes": n, "fails": n,
                             "verdict": ALWAYS_FAILS / ALWAYS_PASSES / FLAKY}}

    A file that could not be loaded at all gives an empty "tests" dictionary.
    A run that timed out or errored is counted as a failure, because a test
    that cannot run is not a test that passed. Each rerun uses a fresh
    temporary folder and the same safety rules as run_tests, so nothing is
    written outside it and our API keys are never passed on.
    """
    if times is None:
        times = config.RERUN_TIMES

    passes_so_far = {}
    fails_so_far = {}
    status = OK
    error = ""

    for index in range(1, times + 1):
        one_run = run_tests(module_file, test_file, run_index=index)

        if one_run["status"] != OK:
            status = one_run["status"]
            error = one_run.get("error", "")

        for name, result in one_run["tests"].items():
            if result in (PASSED, SKIPPED):
                passes_so_far[name] = passes_so_far.get(name, 0) + 1
            else:
                fails_so_far[name] = fails_so_far.get(name, 0) + 1

    tests = {}
    for name in list(passes_so_far) + [n for n in fails_so_far
                                        if n not in passes_so_far]:
        got_passes = passes_so_far.get(name, 0)
        got_fails = fails_so_far.get(name, 0)

        if got_fails and not got_passes:
            verdict = ALWAYS_FAILS
        elif got_passes and not got_fails:
            verdict = ALWAYS_PASSES
        else:
            # It passed at least once and failed at least once, so we cannot
            # trust it.
            verdict = FLAKY

        tests[name] = {"passes": got_passes, "fails": got_fails,
                       "verdict": verdict}

    return {"status": status, "times": times, "tests": tests, "error": error}


def evaluate_tests(before_file, after_file, test_file) -> list:
    """Run the same test file against both versions and label every test.

    Returns a list of dictionaries, one per test, with the keys
    "name", "before", "after" and "label".
    """
    before_run = run_tests(before_file, test_file)
    after_run = run_tests(after_file, test_file)

    print(f"[prsentinel] before: status {before_run['status']}")
    print(f"[prsentinel] after : status {after_run['status']}")

    # If the file could not be loaded we have no per-test names, so we report
    # one row for the whole file rather than pretending to know the details.
    if not before_run["tests"] and not after_run["tests"]:
        broken = before_run["status"] != OK or after_run["status"] != OK
        return [{
            "name": WHOLE_FILE,
            "display": WHOLE_FILE,
            "before": before_run["status"],
            "after": after_run["status"],
            "label": TEST_WRONG_ON_BEFORE if broken else NO_SIGNAL,
            "detail": before_run.get("error") or after_run.get("error") or "",
            "detail_full": before_run.get("error") or after_run.get("error") or "",
        }]

    # One side has names and the other does not, so line them up with the
    # broken side marked as an error for every test.
    names = list(before_run["tests"].keys()) or list(after_run["tests"].keys())
    display = make_display_names(names)

    results = []
    for name in names:
        before_result = before_run["tests"].get(name, TEST_ERROR)
        after_result = after_run["tests"].get(name, TEST_ERROR)

        # The detail is the failure message from whichever run failed. The
        # short one is for the table, the long one for anything reading the
        # results later.
        detail = ""
        detail_full = ""
        if before_result in (FAILED, TEST_ERROR):
            detail = before_run["failures"].get(name, before_run.get("error", ""))
            detail_full = before_run["failures_full"].get(name, before_run.get("error", ""))
        elif after_result in (FAILED, TEST_ERROR):
            detail = after_run["failures"].get(name, after_run.get("error", ""))
            detail_full = after_run["failures_full"].get(name, after_run.get("error", ""))

        results.append({
            "name": name,                 # the unique key, used for labelling
            "display": display[name],     # the short name we print
            "before": before_result,
            "after": after_result,
            "label": label_for(before_result, after_result),
            "detail": detail,
            "detail_full": detail_full,
        })
    return results


def print_results(results: list) -> None:
    """Print a table of the test results, then a count for each label.

    A name is never cut off, even if it is long. When the line would be too
    wide the name is wrapped onto the next line, indented, so the parameter
    ID stays readable. The failure message goes on its own line underneath.
    """
    if not results:
        print("\nNo tests were run.")
        return

    # How wide the name column may be before we move it to its own line.
    name_width = 54
    result_width = 9

    print("\n=== Results ===")
    header = (f"{'test name':{name_width}} {'before':{result_width}} "
              f"{'after':{result_width}} label")
    print(header)
    print("-" * len(header))

    for row in results:
        name = row.get("display", row["name"])

        if len(name) <= name_width:
            print(f"{name:{name_width}} {row['before']:{result_width}} "
                  f"{row['after']:{result_width}} {row['label']}")
        else:
            # Too wide for one line, so the name goes above the results.
            print(name)
            print(f"{'':{name_width}} {row['before']:{result_width}} "
                  f"{row['after']:{result_width}} {row['label']}")

        # The detail line says why it failed, in plain text under the row.
        detail = row.get("detail", "")
        if detail:
            print(f"{'':{name_width}}   -> {detail}")

    counts = {label: 0 for label in ALL_LABELS}
    for row in results:
        counts[row["label"]] = counts.get(row["label"], 0) + 1

    print("\n=== Summary ===")
    for label in ALL_LABELS:
        print(f"  {label:24} {counts.get(label, 0)}")


def main() -> int:
    """Let us run this from the terminal:
    python -m prsentinel.test_runner before.py after.py generated_test.py
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a generated test file against the old and new module."
    )
    parser.add_argument("before_file", help="path to the old version of the module")
    parser.add_argument("after_file", help="path to the new version of the module")
    parser.add_argument("test_file", help="path to the generated test file")
    args = parser.parse_args()

    for path in (args.before_file, args.after_file, args.test_file):
        if not Path(path).is_file():
            print(f"Cannot read that file: {path}")
            return 1

    results = evaluate_tests(args.before_file, args.after_file, args.test_file)
    print_results(results)

    # A test that fails, or a file that errors or times out, is a finding
    # about the tests. Only a fault in this runner is a non-zero exit.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
