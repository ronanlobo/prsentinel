"""End-to-end tests for the repair loop.

test_repair.py uses fake runs so it can check the decisions quickly. These
tests are the opposite: the only fake is the writer. Everything else is the
real code doing real work:

- the real diff extractor finds the changed function;
- the real test_runner starts pytest in its own temporary folders and runs the
  fixture tests against the real before and after files;
- the real classifier decides whether the wrong test is still wrong.

The files live in tests/fixtures/repair_e2e/. Each test copies them into a
scratch folder inside the project and removes the folder again afterwards.

The suite in the fixture has one wrong test (it expects a product from code
that has always added up, so it fails on both versions) and two good tests.
That is exactly the shape the repair loop is meant to handle.
"""

import re
import shutil
import tempfile
from pathlib import Path

import pytest

from prsentinel import config as cfg
from prsentinel import pipeline as pl
from prsentinel import test_runner as tr

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repair_e2e"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_FILE_NAME = "wrong_and_good.py"
WRONG_LINE = "assert total_price([2, 3]) == 6"
FIXED_LINE = "assert total_price([2, 3]) == 5"
GOOD_LINE = "assert total_price([]) == 0"


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def code_block(text: str) -> str:
    """Wrap a test file the way a chatty writer's reply would wrap it."""
    return "Here is the corrected file:\n\n```python\n" + text + "\n```\n"


def writer_returning(text: str):
    """A fake writer that always hands back the same test file."""
    def ask(prompt, temperature=None):
        return code_block(text)
    return ask


def writer_that_crashes(prompt, temperature=None):
    """A fake writer that fails, as a broken network call would."""
    raise RuntimeError("the writer fell over")


@pytest.fixture(autouse=True)
def one_rerun(monkeypatch):
    """Shorten the flakiness reruns for these tests only.

    Every fixture test is deterministic, so the rerun count cannot change any
    answer here. The real runner is still the code doing the running; this just
    stops it repeating a fixed answer several times for no new information.
    """
    monkeypatch.setattr(cfg, "RERUN_TIMES", 1)


@pytest.fixture
def scratch():
    """A copy of the fixture files, made inside the project."""
    folder = Path(tempfile.mkdtemp(prefix="repair_e2e_", dir=PROJECT_ROOT))
    shutil.copyfile(FIXTURES / "before.py", folder / "before.py")
    shutil.copyfile(FIXTURES / "after.py", folder / "after.py")
    shutil.copyfile(FIXTURES / TEST_FILE_NAME, folder / TEST_FILE_NAME)
    try:
        yield folder
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def one_outcome(test_file) -> dict:
    """An outcome in the shape the repair loop reads."""
    return {"function": "total_price", "change_type": "modified",
            "path": str(test_file), "from_folder": "", "skipped": False}


def one_result(test_name, verdict, label) -> dict:
    """A result carrying a single judgement, as the pipeline builds them."""
    judgement = {"test": test_name, "verdict": verdict, "reason": "because",
                 "label": label, "before": tr.FAILED, "after": tr.FAILED}
    return {"judgements": [judgement]}


def run_the_repair(test_file, ask, verdict, label):
    """Call the real repair loop with one wrong test and a fake writer."""
    return pl.repair_bad_tests(
        str(test_file.parent / "before.py"),
        str(test_file.parent / "after.py"),
        [one_outcome(test_file)],
        [one_result(wrong_test_name(test_file), verdict, label)],
        ask=ask,
    )


def wrong_test_name(test_file) -> str:
    """The name the real runner gives the wrong test, found by running it."""
    rows = real_rows(test_file)
    return next(row for row in rows
                if row["label"] == tr.TEST_WRONG_ON_BEFORE)["name"]


def real_rows(test_file) -> list:
    """Run the real runner on both versions and label every test."""
    return tr.evaluate_tests(str(test_file.parent / "before.py"),
                             str(test_file.parent / "after.py"),
                             str(test_file))


def backups_in(folder) -> list:
    return [p.name for p in Path(folder).iterdir()
            if re.search(r"\.bak(\.\d+)?$", p.name)]


# ---------------------------------------------------------------------------
# The fixture itself is what we think it is
# ---------------------------------------------------------------------------

def test_the_fixture_has_one_wrong_test_and_two_good_ones(scratch):
    rows = real_rows(scratch / TEST_FILE_NAME)

    labels = sorted(row["label"] for row in rows)
    assert labels == [tr.NO_SIGNAL, tr.NO_SIGNAL, tr.TEST_WRONG_ON_BEFORE]


# ---------------------------------------------------------------------------
# 1. A good repair is accepted, kept, and backed up
# ---------------------------------------------------------------------------

def test_a_good_repair_fixes_the_wrong_test_and_keeps_the_others(scratch):
    test_file = scratch / TEST_FILE_NAME
    original = read(test_file)
    fixed = original.replace(WRONG_LINE, FIXED_LINE)
    assert fixed != original  # the fixture must really contain the wrong line

    records = run_the_repair(test_file, writer_returning(fixed),
                             verdict="BAD_TEST", label=tr.TEST_WRONG_ON_BEFORE)

    assert len(records) == 1
    record = records[0]
    assert record["outcome"] == "repaired"
    assert record["attempts"] == 1

    # The real file now holds the repaired version, good tests untouched.
    assert read(test_file) == fixed
    assert GOOD_LINE in read(test_file)

    # A backup of the original was kept.
    assert record["backup"]
    backup = test_file.parent / record["backup"]
    assert re.search(r"\.bak(\.\d+)?$", record["backup"])
    assert backup.exists()
    assert read(backup) == original

    # Run the repaired file for real: nothing is wrong on the old code any
    # more, and both good tests still pass on both versions.
    after_rows = real_rows(test_file)
    assert all(row["label"] != tr.TEST_WRONG_ON_BEFORE for row in after_rows)
    assert sum(1 for row in after_rows if row["label"] == tr.NO_SIGNAL) == 3


# ---------------------------------------------------------------------------
# 2. A repair that damages a good test is thrown away
# ---------------------------------------------------------------------------

def test_a_repair_that_breaks_a_good_test_is_rejected(scratch):
    test_file = scratch / TEST_FILE_NAME
    original = read(test_file)
    # Its own test is fixed, but a good test is broken.
    weakening = original.replace(WRONG_LINE, FIXED_LINE)
    weakening = weakening.replace(GOOD_LINE, "assert total_price([]) == 99")

    records = run_the_repair(test_file, writer_returning(weakening),
                             verdict="BAD_TEST", label=tr.TEST_WRONG_ON_BEFORE)

    assert records[0]["outcome"] == "weakened"
    assert records[0]["attempts"] == cfg.MAX_REPAIR_ATTEMPTS
    # The real file is byte-for-byte the one we started with, and no backup
    # was made because nothing was accepted.
    assert read(test_file) == original
    assert backups_in(scratch) == []


# ---------------------------------------------------------------------------
# 3. A writer that never improves the test gives up after the limit
# ---------------------------------------------------------------------------

def test_a_writer_that_never_improves_gives_up(scratch):
    test_file = scratch / TEST_FILE_NAME
    original = read(test_file)

    records = run_the_repair(test_file, writer_returning(original),
                             verdict="BAD_TEST", label=tr.TEST_WRONG_ON_BEFORE)

    assert records[0]["outcome"] == "unrepaired BAD_TEST"
    assert records[0]["attempts"] == cfg.MAX_REPAIR_ATTEMPTS
    assert read(test_file) == original
    assert backups_in(scratch) == []


# ---------------------------------------------------------------------------
# 4. A writer that crashes leaves the file alone
# ---------------------------------------------------------------------------

def test_a_writer_that_crashes_leaves_the_file_alone(scratch):
    test_file = scratch / TEST_FILE_NAME
    original = read(test_file)

    records = run_the_repair(test_file, writer_that_crashes,
                             verdict="BAD_TEST", label=tr.TEST_WRONG_ON_BEFORE)

    assert records[0]["outcome"] == "unrepaired BAD_TEST"
    assert records[0]["attempts"] == cfg.MAX_REPAIR_ATTEMPTS
    assert read(test_file) == original
    assert backups_in(scratch) == []
