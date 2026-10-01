"""Tests for the one-command pipeline.

Nothing here calls a real AI or touches the internet. The AI is replaced by a
fake, and so are the test runs, so these tests are quick and always give the
same answer.
"""

import json
from pathlib import Path

import pytest

from prsentinel import classifier as cl
from prsentinel import llm_client
from prsentinel import pipeline as pl
from prsentinel import test_runner as tr

# Some fake code for the module and the test file.
MODULE_CODE = "def get_recent_scores(scores, window):\n    return scores[-window:]\n"
GENERATED_TEST = """
    from target import get_recent_scores

    def test_one():
        assert get_recent_scores([1, 2, 3], 2) == [2, 3]
"""


def fake_change(name, change_type="modified"):
    """One change, in the shape diff_extractor hands back."""
    return {"name": name, "change_type": change_type, "old_code": "",
            "new_code": "", "old_lines": [], "new_lines": [],
            "summary": f"{change_type} {name}"}


def fake_run(tests, failures=None):
    """A run, in the shape run_tests hands back."""
    return {
        "status": tr.OK,
        "tests": dict(tests),
        "failures": dict(failures or {}),
        "failures_full": dict(failures or {}),
        "error": "",
    }


class FakeAI:
    """Remembers what it was asked to generate, and what it was asked twice."""

    def __init__(self):
        self.generated = []
        self.calls = []


class FakeRuns:
    """Fixed test results, read fresh each time so a test can change them.

    Also counts how many times the pipeline asked for a run, so a test can
    check we are not running pytest once per test.
    """

    def __init__(self, wanted):
        self.wanted = wanted
        self.counts = {"run_tests": 0, "rerun_failures": 0}

    def before_run(self):
        """One run against the old code."""
        self.counts["run_tests"] += 1
        return fake_run(self.wanted["before"])

    def after_run(self):
        """One run against the new code, with a message for each failure."""
        self.counts["run_tests"] += 1
        messages = {name: f"assert failed in {name}"
                    for name in self.wanted["after"]}
        return fake_run(self.wanted["after"], messages)

    def rerun_run(self):
        """The reruns against the new code."""
        self.counts["rerun_failures"] += 1
        return {"status": tr.OK, "times": 5,
                "tests": self.wanted["rerun"], "error": ""}

    def rows(self):
        """The labelled rows, as evaluate_tests would hand them back."""
        rows = []
        for name, after_result in self.wanted["after"].items():
            before_result = self.wanted["before"].get(name, tr.TEST_ERROR)
            rows.append({
                "name": name,
                "display": name.split("::")[-1],
                "before": before_result,
                "after": after_result,
                "label": tr.label_for(before_result, after_result),
                "detail": f"assert failed in {name}",
                "detail_full": f"assert failed in {name}",
            })
        return rows


# One test passes everywhere, and three fail in three different ways, so all
# three verdicts get used.
DEFAULT_WANTED = {
    "before": {
        "t::test_clean": tr.PASSED,
        "t::test_a": tr.PASSED,     # becomes a real bug
        "t::test_b": tr.FAILED,     # fails on the correct code too
        "t::test_c": tr.PASSED,     # becomes flaky
    },
    "after": {
        "t::test_clean": tr.PASSED,
        "t::test_a": tr.FAILED,
        "t::test_b": tr.FAILED,
        "t::test_c": tr.FAILED,
    },
    "rerun": {
        "t::test_a": {"passes": 0, "fails": 5, "verdict": tr.ALWAYS_FAILS},
        "t::test_b": {"passes": 0, "fails": 5, "verdict": tr.ALWAYS_FAILS},
        "t::test_c": {"passes": 3, "fails": 2, "verdict": tr.FLAKY},
    },
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """An empty folder we can work in, so nothing lands in the project."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def fake_ai(monkeypatch):
    """Replace test generation and the second-opinion call with fakes."""
    recorder = FakeAI()

    def fake_generate_tests(change):
        """Hand back a fixed test file, and remember what we were asked for."""
        recorder.generated.append(change["name"])
        return GENERATED_TEST

    def fake_llm_classify(evidence, mode):
        """Count the calls and give a fixed answer."""
        recorder.calls.append((evidence["test_name"], mode))
        return {"label": cl.BAD_TEST, "confidence": "medium",
                "reason": "The test asks for something odd."}

    monkeypatch.setattr(pl.tg, "generate_tests", fake_generate_tests)
    monkeypatch.setattr(cl, "llm_classify", fake_llm_classify)

    return recorder


@pytest.fixture
def fake_runs(monkeypatch):
    """Replace the test runs with fixed results.

    A test can set `fake_runs.wanted` to something else at any time before it
    runs the pipeline, and the fakes will use the new values.
    """
    runs = FakeRuns(dict(DEFAULT_WANTED))

    def fake_run_tests(module, test, **kwargs):
        """We are asked for the old version first, then the new one."""
        return runs.after_run() if "after" in Path(module).name \
            else runs.before_run()

    monkeypatch.setattr(pl.tr, "run_tests", fake_run_tests)
    monkeypatch.setattr(pl.tr, "rerun_failures",
                        lambda module, test, **kw: runs.rerun_run())
    monkeypatch.setattr(pl.tr, "evaluate_tests",
                        lambda before, after, test: runs.rows())

    return runs


def write_modules(workspace, name="my_example"):
    """Write a before.py and after.py and give the two paths back."""
    folder = workspace / "src_examples" / name
    folder.mkdir(parents=True, exist_ok=True)
    before = folder / "before.py"
    after = folder / "after.py"
    before.write_text(MODULE_CODE, encoding="utf-8")
    after.write_text(MODULE_CODE.replace("[-window:]", "[-window - 1:]"),
                     encoding="utf-8")
    return str(before), str(after)


def one_change(monkeypatch, *changes):
    """Make diff_extractor return exactly these changes."""
    monkeypatch.setattr(pl, "extract_changes_from_files",
                        lambda before, after: list(changes))


# ---------------------------------------------------------------------------
# The report text
# ---------------------------------------------------------------------------

def test_the_report_shows_every_verdict(workspace, fake_ai, fake_runs,
                                        monkeypatch):
    """A real bug, a bad test and a flaky one must all appear in the report."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)
    text = pl.format_report(report)

    assert cl.REAL_BUG in text
    assert cl.BAD_TEST in text
    assert cl.FLAKY in text

    # One line per verdict, saying which test it belongs to.
    assert "test_a" in text
    assert "test_b" in text
    assert "test_c" in text
    assert "points to a real bug" in text


def test_the_report_shows_the_counts_per_function(workspace, fake_ai,
                                                  fake_runs, monkeypatch):
    """Each of the four labels gets a line, even when it is zero."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    text = pl.format_report(pl.run_pipeline(before, after))

    for label in pl.COUNT_LABELS:
        assert label in text, f"{label} is missing from the report"

    # One test caught the change, one was wrong on the correct code.
    counts = text
    assert f"{tr.CATCHES_CHANGE:<24} 2" in counts
    assert f"{tr.NO_SIGNAL:<24} 1" in counts


def test_the_summary_counts_only_real_bugs(workspace, fake_ai, fake_runs,
                                           monkeypatch):
    """A bad test is not evidence of a bug, so it is left out."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)

    # Only test_a is judged a real bug, even though two tests caught the change.
    assert report["summary"] == \
        "1 test points to a real bug in get_recent_scores."


def test_the_summary_says_so_when_there_is_nothing_to_find(workspace, fake_ai,
                                                            fake_runs, monkeypatch):
    """With no failing test we say nothing was found, in plain words."""
    fake_runs.wanted = {
        "before": {"t::test_clean": tr.PASSED},
        "after": {"t::test_clean": tr.PASSED},
        "rerun": {},
    }
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)

    assert report["summary"] == "No test points to a real bug in the code."
    assert "nothing to judge" in pl.format_report(report)


def test_several_functions_are_reported_separately(workspace, fake_ai,
                                                   fake_runs, monkeypatch):
    """Each changed function gets its own block in the report."""
    one_change(monkeypatch,
               fake_change("first_function"),
               fake_change("second_function"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)
    text = pl.format_report(report)

    assert len(report["functions"]) == 2
    assert "first_function" in text
    assert "second_function" in text
    # Each function gets its own clause, so both are named in the summary.
    assert "real bug in first_function" in report["summary"]
    assert "real bug in second_function" in report["summary"]


# ---------------------------------------------------------------------------
# The second opinion is opt-in
# ---------------------------------------------------------------------------

def test_without_the_flag_the_ai_is_never_asked(workspace, fake_ai, fake_runs,
                                                monkeypatch):
    """No flag means no extra AI call at all."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after, ai_second_opinion=False)

    assert fake_ai.calls == [], "the AI was asked even without the flag"
    for function in report["functions"]:
        for judgement in function["judgements"]:
            assert judgement["ai_verdict"] == ""
            assert judgement["ai_agrees"] is None


def test_with_the_flag_the_ai_is_asked_once_per_failing_test(workspace, fake_ai,
                                                             fake_runs,
                                                             monkeypatch):
    """Three failing tests means three AI calls, and not one more."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after, ai_second_opinion=True)

    assert len(fake_ai.calls) == 3, "we should ask once per failing test"
    assert all(mode == cl.MODE_FULL for _, mode in fake_ai.calls)


# ---------------------------------------------------------------------------
# Step 6: tests that are wrong even on the correct code
# ---------------------------------------------------------------------------

def test_a_test_wrong_on_the_correct_code_is_judged(workspace, fake_ai,
                                                    fake_runs, monkeypatch):
    """A test that fails on the OLD code gets a verdict too.

    The rule already knows what to do with one of these: a test that fails on
    code that used to work is a bad test.
    """
    fake_runs.wanted = {
        "before": {"t::test_bad": tr.FAILED},
        "after": {"t::test_bad": tr.FAILED},
        "rerun": {"t::test_bad": {"passes": 0, "fails": 5,
                                  "verdict": tr.ALWAYS_FAILS}},
    }
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)
    function = report["functions"][0]

    assert function["counts"][tr.TEST_WRONG_ON_BEFORE] == 1
    assert len(function["judgements"]) == 1

    judgement = function["judgements"][0]
    assert judgement["test"] == "t::test_bad"
    assert judgement["label"] == tr.TEST_WRONG_ON_BEFORE
    assert judgement["verdict"] == cl.BAD_TEST
    assert cl.BAD_TEST in pl.format_report(report)


def test_a_bad_test_is_never_counted_as_a_real_bug(workspace, fake_ai,
                                                   fake_runs, monkeypatch):
    """A wrong test is not evidence of a bug, so it stays out of the summary."""
    fake_runs.wanted = {
        "before": {"t::test_bad": tr.FAILED, "t::test_real": tr.PASSED},
        "after": {"t::test_bad": tr.FAILED, "t::test_real": tr.FAILED},
        "rerun": {
            "t::test_bad": {"passes": 0, "fails": 5,
                            "verdict": tr.ALWAYS_FAILS},
            "t::test_real": {"passes": 0, "fails": 5,
                             "verdict": tr.ALWAYS_FAILS},
        },
    }
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)

    # Two tests failed on the new code, but only one of them counts.
    assert len(report["functions"][0]["judgements"]) == 2
    assert report["summary"] == \
        "1 test points to a real bug in get_recent_scores."


def test_an_odd_test_is_listed_but_not_judged(workspace, fake_ai, fake_runs,
                                              monkeypatch):
    """A test that only the new code satisfies is a question for a person.

    A rule cannot tell whether that test is wrong or the change simply added
    behaviour, so we point at it and stop there.
    """
    fake_runs.wanted = {
        "before": {"t::test_odd": tr.FAILED},
        "after": {"t::test_odd": tr.PASSED},
        "rerun": {},
    }
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)
    function = report["functions"][0]
    text = pl.format_report(report)

    assert function["counts"][tr.ODD] == 1
    assert function["needs_a_look"] == ["t::test_odd"]
    assert function["judgements"] == [], "an odd test must not be judged"
    assert "needs a human look" in text
    assert "t::test_odd" in text


def test_an_odd_test_does_not_ask_the_ai_either(workspace, fake_ai, fake_runs,
                                                monkeypatch):
    """Listing an odd test is not judging it, so no AI call is made."""
    fake_runs.wanted = {
        "before": {"t::test_odd": tr.FAILED},
        "after": {"t::test_odd": tr.PASSED},
        "rerun": {},
    }
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    pl.run_pipeline(before, after, ai_second_opinion=True)

    assert fake_ai.calls == []


def test_a_wrong_test_and_an_odd_test_are_both_reported(workspace, fake_ai,
                                                        fake_runs, monkeypatch):
    """The two awkward cases sit side by side without being confused."""
    fake_runs.wanted = {
        "before": {"t::test_bad": tr.FAILED, "t::test_odd": tr.FAILED,
                   "t::test_real": tr.PASSED},
        "after": {"t::test_bad": tr.FAILED, "t::test_odd": tr.PASSED,
                  "t::test_real": tr.FAILED},
        "rerun": {
            "t::test_bad": {"passes": 0, "fails": 5,
                            "verdict": tr.ALWAYS_FAILS},
            "t::test_real": {"passes": 0, "fails": 5,
                             "verdict": tr.ALWAYS_FAILS},
        },
    }
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)
    function = report["functions"][0]

    judged = sorted(j["test"] for j in function["judgements"])
    assert judged == ["t::test_bad", "t::test_real"]
    assert function["needs_a_look"] == ["t::test_odd"]
    assert report["summary"] == \
        "1 test points to a real bug in get_recent_scores."


# ---------------------------------------------------------------------------
# The tests are run once per file, not once per test
# ---------------------------------------------------------------------------

def test_pytest_runs_once_per_file_not_once_per_test(workspace, fake_ai,
                                                     fake_runs, monkeypatch):
    """Three failing tests must not mean three sets of pytest runs.

    Every test in a file shares one run on the old code, one on the new code,
    and one set of reruns. Running them again per test would be wasted work.
    """
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)

    assert len(report["functions"][0]["judgements"]) == 3
    assert fake_runs.counts["run_tests"] == 2, "one run per version of the module"
    assert fake_runs.counts["rerun_failures"] == 1, "one set of reruns"


def test_no_runs_at_all_when_nothing_needs_judging(workspace, fake_ai,
                                                   fake_runs, monkeypatch):
    """If every test passes on the new code we do not bother running anything."""
    fake_runs.wanted = {
        "before": {"t::test_clean": tr.PASSED},
        "after": {"t::test_clean": tr.PASSED},
        "rerun": {},
    }
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)

    assert report["functions"][0]["judgements"] == []
    assert fake_runs.counts["run_tests"] == 0
    assert fake_runs.counts["rerun_failures"] == 0


def test_a_disagreement_is_flagged(workspace, fake_ai, fake_runs, monkeypatch):
    """When the AI says something else, we say so in the report."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after, ai_second_opinion=True)
    text = pl.format_report(report)

    # The fake AI always says BAD_TEST, so the real bug is a disagreement.
    judged = report["functions"][0]["judgements"][0]
    assert judged["verdict"] == cl.REAL_BUG
    assert judged["ai_verdict"] == cl.BAD_TEST
    assert judged["ai_agrees"] is False
    assert "DISAGREES" in text


# ---------------------------------------------------------------------------
# One function failing does not stop the rest
# ---------------------------------------------------------------------------

def test_a_function_that_will_not_generate_does_not_stop_the_others(
        workspace, fake_ai, fake_runs, monkeypatch):
    """A generation failure is reported, and the next function still runs."""
    one_change(monkeypatch,
               fake_change("broken_function"),
               fake_change("working_function"))

    real_generate = pl.tg.generate_tests
    attempted = []

    def sometimes_fails(change):
        """Fail for one name only, and remember that we were asked."""
        attempted.append(change["name"])
        if change["name"] == "broken_function":
            raise RuntimeError("the model gave us nothing usable")
        return real_generate(change)

    monkeypatch.setattr(pl.tg, "generate_tests", sometimes_fails)
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)
    text = pl.format_report(report)

    # Both were tried, and the failure of the first did not stop the second.
    assert attempted == ["broken_function", "working_function"]
    assert fake_ai.generated == ["working_function"]
    assert [f["function"] for f in report["functions"]] == ["working_function"]

    # And the failure is written down at the end, not hidden.
    assert len(report["generation_failed"]) == 1
    assert report["generation_failed"][0]["function"] == "broken_function"
    assert "the model gave us nothing usable" in text
    assert "could not write tests for" in text


def test_a_removed_function_is_skipped(workspace, fake_ai, fake_runs,
                                       monkeypatch):
    """There is nothing left to test in a function that was deleted."""
    one_change(monkeypatch,
               fake_change("gone_function", change_type="removed"),
               fake_change("still_here_function"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)

    assert "gone_function" not in fake_ai.generated
    assert "still_here_function" in fake_ai.generated
    assert len(report["skipped"]) == 1
    assert report["skipped"][0]["function"] == "gone_function"


def test_a_judgement_that_breaks_is_reported_not_fatal(workspace, fake_ai,
                                                      fake_runs, monkeypatch):
    """If we cannot judge a test we say so and carry on."""
    def broken_evidence(*args, **kwargs):
        raise RuntimeError("could not work out what happened")

    monkeypatch.setattr(pl.cl, "build_evidence", broken_evidence)
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)

    judgements = report["functions"][0]["judgements"]
    assert len(judgements) == 3
    assert all(j["verdict"] == "UNKNOWN" for j in judgements)
    assert "UNKNOWN" in pl.format_report(report)


# ---------------------------------------------------------------------------
# The files we save
# ---------------------------------------------------------------------------

def test_the_report_is_saved(workspace, fake_ai, fake_runs, monkeypatch):
    """Both files are written, into reports/."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after, name="saved_run")

    markdown = workspace / "reports" / "saved_run.md"
    data = workspace / "reports" / "saved_run.json"

    assert markdown.is_file()
    assert data.is_file()
    assert report["summary"] in markdown.read_text(encoding="utf-8")

    saved = json.loads(data.read_text(encoding="utf-8"))
    assert saved["name"] == "saved_run"
    assert saved["summary"] == report["summary"]
    assert len(saved["functions"]) == 1


def test_the_saved_files_hold_nothing_from_the_answer_key(workspace, fake_ai,
                                                          fake_runs, monkeypatch):
    """No case folder names and no answer key wording in what we save."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    pl.run_pipeline(before, after, name="clean_run")

    saved_files = [workspace / "reports" / "clean_run.md",
                   workspace / "reports" / "clean_run.json"]
    for path in saved_files:
        text = path.read_text(encoding="utf-8")

        assert "classifier_cases" not in text, f"{path.name} names the cases folder"
        for leaked in ("real_bug_", "bad_test_", "flaky_random",
                       "flaky_set_order", "flaky_current_time",
                       "expected.json"):
            assert leaked not in text, f"{path.name} leaks {leaked}"

        assert "expected" not in text.lower(), \
            f"{path.name} says 'expected', which belongs to the answer key"
        assert "gsk_" not in text
        assert "AIza" not in text


def test_the_name_defaults_to_the_folder(workspace, fake_ai, fake_runs,
                                         monkeypatch):
    """Without --name we use the folder the old file sits in."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")

    report = pl.run_pipeline(before, after)

    assert report["name"] == "round7_thing"
    assert (workspace / "generated_tests" / "round7_thing").is_dir()
    assert (workspace / "reports" / "round7_thing.md").is_file()
    assert (workspace / "reports" / "round7_thing.json").is_file()


def test_an_old_test_file_is_kept_as_a_backup(workspace, fake_ai, fake_runs,
                                              monkeypatch):
    """Writing over an old file keeps a copy, so nothing is lost."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")

    folder = workspace / "generated_tests" / "round7_thing"
    folder.mkdir(parents=True, exist_ok=True)
    old_path = folder / "test_get_recent_scores.py"
    old_path.write_text("# the version we looked at last time\n",
                        encoding="utf-8")

    pl.run_pipeline(before, after)

    backup = folder / ("test_get_recent_scores.py" + pl.BACKUP_SUFFIX)
    assert backup.is_file()
    assert "last time" in backup.read_text(encoding="utf-8")
    assert "last time" not in old_path.read_text(encoding="utf-8")


def test_no_backup_is_made_when_there_is_nothing_to_replace(workspace, fake_ai,
                                                            fake_runs,
                                                            monkeypatch):
    """A first run leaves no stray .bak files behind."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")

    pl.run_pipeline(before, after)

    folder = workspace / "generated_tests" / "round7_thing"
    assert list(folder.glob("*.bak*")) == []


# ---------------------------------------------------------------------------
# An existing backup is never overwritten
# ---------------------------------------------------------------------------

def test_a_second_run_keeps_both_older_copies(workspace, fake_ai, fake_runs,
                                              monkeypatch):
    """The second backup must not land on top of the first one.

    This is the exact mistake that lost the original 108-line round 2 file: an
    earlier run put it in .bak, and the next run wrote over the same name.
    """
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    folder = workspace / "generated_tests" / "round7_thing"
    folder.mkdir(parents=True, exist_ok=True)

    main_file = folder / "test_get_recent_scores.py"

    # Run 1: the version we were given, and then a generated one.
    main_file.write_text("# version 0\n", encoding="utf-8")
    pl.run_pipeline(before, after)

    # Run 2: a second generated version, which must be kept separately.
    main_file.write_text("# version 1\n", encoding="utf-8")
    pl.run_pipeline(before, after)

    first = folder / ("test_get_recent_scores.py" + pl.BACKUP_SUFFIX)
    second = folder / ("test_get_recent_scores.py" + pl.BACKUP_SUFFIX + ".2")

    assert first.read_text(encoding="utf-8") == "# version 0\n"
    assert second.read_text(encoding="utf-8") == "# version 1\n"


def test_backups_keep_numbering_up_forever(workspace, fake_ai, fake_runs,
                                           monkeypatch):
    """Every run adds a new backup and none of the old ones change."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    folder = workspace / "generated_tests" / "round7_thing"
    folder.mkdir(parents=True, exist_ok=True)
    main_file = folder / "test_get_recent_scores.py"

    for run in range(4):
        main_file.write_text(f"# version {run}\n", encoding="utf-8")
        pl.run_pipeline(before, after)

    names = sorted(p.name for p in folder.glob("*.bak*"))
    assert names == ["test_get_recent_scores.py.bak",
                     "test_get_recent_scores.py.bak.2",
                     "test_get_recent_scores.py.bak.3",
                     "test_get_recent_scores.py.bak.4"]

    # The oldest one is still exactly what it was.
    oldest = folder / names[0]
    assert oldest.read_text(encoding="utf-8") == "# version 0\n"


def test_free_backup_path_never_returns_a_taken_name(tmp_path):
    """The helper itself always points at a name that is free."""
    path = tmp_path / "test_x.py"

    first = pl.free_backup_path(path)
    assert first.name == "test_x.py.bak"

    first.write_text("something", encoding="utf-8")
    second = pl.free_backup_path(path)
    assert second.name == "test_x.py.bak.2"

    second.write_text("something", encoding="utf-8")
    third = pl.free_backup_path(path)
    assert third.name == "test_x.py.bak.3"
    assert not third.exists()


# ---------------------------------------------------------------------------
# --reuse-tests: no AI at all
# ---------------------------------------------------------------------------

def saved_test_file(workspace, name, function="get_recent_scores",
                    folder="generated_tests"):
    """Put a test file in place, as an earlier run would have left it.

    folder is which folder to put it in: generated_tests for a live file, or
    baselines for a frozen copy.
    """
    place = workspace / folder / name
    place.mkdir(parents=True, exist_ok=True)
    path = place / f"test_{function}.py"
    path.write_text(GENERATED_TEST, encoding="utf-8")
    return path


def test_reuse_tests_makes_no_ai_calls(workspace, fake_ai, fake_runs,
                                       monkeypatch):
    """With --reuse-tests the AI is never asked for anything."""
    def forbidden(*args, **kwargs):
        raise AssertionError("the AI was asked, but --reuse-tests forbids it")

    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing")

    monkeypatch.setattr(pl.tg, "generate_tests", forbidden)
    monkeypatch.setattr(cl, "llm_classify", forbidden)

    pl.run_pipeline(before, after, reuse_tests=True)

    assert fake_ai.calls == []


def test_reuse_tests_does_not_write_a_new_test_file(workspace, fake_ai,
                                                    fake_runs, monkeypatch):
    """The saved test must come out the other side untouched."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    path = saved_test_file(workspace, "round7_thing")
    original = path.read_text(encoding="utf-8")

    pl.run_pipeline(before, after, reuse_tests=True)

    assert path.read_text(encoding="utf-8") == original
    assert list(path.parent.glob("*.bak*")) == [], \
        "reusing a test must not make a backup, because nothing was replaced"


def test_the_report_says_where_the_tests_came_from(workspace, fake_ai,
                                                   fake_runs, monkeypatch):
    """A saved report must always say whether the tests were new or reused."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing")

    fresh = pl.format_report(pl.run_pipeline(before, after,
                                             name="round7_thing"))
    reused = pl.format_report(pl.run_pipeline(before, after,
                                              name="round7_thing",
                                              reuse_tests=True))

    assert "Tests: generated" in fresh
    assert "Tests: reused from generated_tests" in reused


def test_reuse_tests_reports_a_function_it_has_no_test_for(workspace, fake_ai,
                                                           fake_runs,
                                                           monkeypatch):
    """A missing saved test is a failure in the report, not a crash."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    # Deliberately do not save a test file.

    report = pl.run_pipeline(before, after, reuse_tests=True)

    assert report["functions"] == []
    assert len(report["generation_failed"]) == 1
    assert "no saved test file" in report["generation_failed"][0]["error"]
    assert report["summary"] == "No test points to a real bug in the code."


def test_reuse_tests_skips_a_removed_function(workspace, fake_ai, fake_runs,
                                              monkeypatch):
    """A deleted function has no test to reuse and no test to want."""
    one_change(monkeypatch,
               fake_change("gone_function", change_type="removed"),
               fake_change("still_here_function"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing", function="still_here_function")

    report = pl.run_pipeline(before, after, reuse_tests=True)

    assert [f["function"] for f in report["functions"]] == ["still_here_function"]
    assert [s["function"] for s in report["skipped"]] == ["gone_function"]


def test_reuse_tests_still_runs_and_judges(workspace, fake_ai, fake_runs,
                                           monkeypatch):
    """Reusing tests must not mean skipping the work."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing")

    report = pl.run_pipeline(before, after, reuse_tests=True)

    assert len(report["functions"][0]["judgements"]) == 3
    assert "points to a real bug" in report["summary"]


def test_reuse_tests_is_off_by_default(workspace, fake_ai, fake_runs,
                                       monkeypatch):
    """Without the flag we ask the AI, as before."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")

    report = pl.run_pipeline(before, after)

    assert fake_ai.generated == ["get_recent_scores"]
    assert report["tests_source"] == "generated"


def test_the_reuse_flag_reaches_the_command_line(workspace, fake_ai, fake_runs,
                                                 monkeypatch, capsys):
    """The flag is wired up on the command line, not just in the function."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing")

    def forbidden(*args, **kwargs):
        raise AssertionError("the AI was asked, but --reuse-tests forbids it")

    monkeypatch.setattr(pl.tg, "generate_tests", forbidden)
    monkeypatch.setattr("sys.argv",
                        ["pipeline", before, after, "--reuse-tests"])

    assert pl.main() == 0
    assert "Tests: reused from generated_tests" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --reuse-tests falls back to the frozen baselines
# ---------------------------------------------------------------------------

def test_reuse_falls_back_to_the_baseline_when_there_is_no_live_file(
        workspace, fake_ai, fake_runs, monkeypatch):
    """No file in generated_tests, but one in baselines, so we use the baseline.

    This is what makes --reuse-tests work on a fresh clone, where the
    generated_tests folder does not exist at all.
    """
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    saved = saved_test_file(workspace, "round7_thing", folder="baselines")

    def forbidden(*args, **kwargs):
        raise AssertionError("the AI was asked, but --reuse-tests forbids it")

    monkeypatch.setattr(pl.tg, "generate_tests", forbidden)

    report = pl.run_pipeline(before, after, name="round7_thing",
                             reuse_tests=True)

    assert [f["function"] for f in report["functions"]] == ["get_recent_scores"]
    assert report["functions"][0]["from_folder"] == "baselines"
    assert report["tests_source"] == "reused from baselines"
    assert report["generation_failed"] == []
    assert saved.name == report["functions"][0]["test_file"]
    # It still runs and judges, it just read a frozen file instead of a live one.
    assert len(report["functions"][0]["judgements"]) == 3


def test_a_live_file_is_always_preferred_over_the_baseline(
        workspace, fake_ai, fake_runs, monkeypatch):
    """When both folders have the file, the live one wins."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    live = saved_test_file(workspace, "round7_thing",
                           folder="generated_tests")
    saved_test_file(workspace, "round7_thing", folder="baselines")

    report = pl.run_pipeline(before, after, name="round7_thing",
                             reuse_tests=True)

    assert report["functions"][0]["from_folder"] == "generated_tests"
    assert report["tests_source"] == "reused from generated_tests"
    assert live.name == report["functions"][0]["test_file"]


def test_the_fallback_is_per_function_not_all_or_nothing(
        workspace, fake_ai, fake_runs, monkeypatch):
    """One live file and one frozen file in the same run is allowed."""
    one_change(monkeypatch,
               fake_change("get_recent_scores"),
               fake_change("add_item_to_cart"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing", function="get_recent_scores",
                    folder="generated_tests")
    saved_test_file(workspace, "round7_thing", function="add_item_to_cart",
                    folder="baselines")

    report = pl.run_pipeline(before, after, name="round7_thing",
                             reuse_tests=True)

    got = {f["function"]: f["from_folder"] for f in report["functions"]}
    assert got == {"get_recent_scores": "generated_tests",
                   "add_item_to_cart": "baselines"}
    assert report["tests_source"] == "reused from generated_tests and baselines"


def test_the_report_names_the_folder_next_to_each_function(
        workspace, fake_ai, fake_runs, monkeypatch):
    """The per-function lines must say which folder that file came from."""
    one_change(monkeypatch,
               fake_change("get_recent_scores"),
               fake_change("add_item_to_cart"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing", function="get_recent_scores",
                    folder="generated_tests")
    saved_test_file(workspace, "round7_thing", function="add_item_to_cart",
                    folder="baselines")

    report = pl.run_pipeline(before, after, name="round7_thing",
                             reuse_tests=True)
    printed = pl.format_report(report)

    assert "came from: generated_tests" in printed
    assert "came from: baselines" in printed


def test_the_fallback_still_makes_no_ai_calls(workspace, fake_ai, fake_runs,
                                              monkeypatch):
    """Falling back must not turn into asking the AI for a new file."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing", folder="baselines")

    def forbidden(*args, **kwargs):
        raise AssertionError("the AI was asked, but --reuse-tests forbids it")

    monkeypatch.setattr(pl.tg, "generate_tests", forbidden)
    monkeypatch.setattr(pl.cl, "llm_classify", forbidden)

    report = pl.run_pipeline(before, after, name="round7_thing",
                             reuse_tests=True, ai_second_opinion=False)

    assert len(report["functions"]) == 1


def test_no_file_anywhere_is_still_reported_as_a_failure(
        workspace, fake_ai, fake_runs, monkeypatch):
    """If neither folder has it, we say so instead of guessing."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing", function="some_other_function",
                    folder="baselines")

    report = pl.run_pipeline(before, after, name="round7_thing",
                             reuse_tests=True)

    assert report["functions"] == []
    assert len(report["generation_failed"]) == 1
    assert "generated_tests" in report["generation_failed"][0]["error"]
    assert "baselines" in report["generation_failed"][0]["error"]


def test_find_saved_test_says_nothing_when_neither_folder_has_it(workspace):
    """The helper itself returns None and no folder for a missing file."""
    path, folder = pl.find_saved_test("nothing_here", "test_nothing.py")
    assert path is None
    assert folder is None


def test_a_generating_run_never_looks_at_the_baselines(
        workspace, fake_ai, fake_runs, monkeypatch):
    """The fallback is for --reuse-tests only. A normal run asks the AI."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace, name="round7_thing")
    saved_test_file(workspace, "round7_thing", folder="baselines")

    report = pl.run_pipeline(before, after, name="round7_thing")

    assert fake_ai.generated == ["get_recent_scores"]
    assert report["tests_source"] == "generated"
    # The new file went to generated_tests, not on top of the baseline.
    assert (workspace / "generated_tests" / "round7_thing" /
            "test_get_recent_scores.py").is_file()


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def test_a_missing_file_is_reported(monkeypatch, capsys):
    """A file we cannot read stops us, with a non-zero exit."""
    monkeypatch.setattr("sys.argv",
                        ["pipeline", "no_such_before.py", "no_such_after.py"])

    assert pl.main() == 1
    assert "Cannot read that file" in capsys.readouterr().out


def test_a_pipeline_that_breaks_is_reported(workspace, monkeypatch, capsys):
    """If the pipeline itself falls over we say so and return non-zero."""
    before, after = write_modules(workspace)

    def broken(*args, **kwargs):
        raise RuntimeError("something went badly wrong")

    monkeypatch.setattr("sys.argv", ["pipeline", before, after])
    monkeypatch.setattr(pl, "run_pipeline", broken)

    assert pl.main() == 1
    assert "the pipeline broke" in capsys.readouterr().out


def test_finding_a_bug_is_still_a_good_run(monkeypatch, workspace, fake_ai,
                                           fake_runs):
    """Bugs are the point of the tool, so they must not look like a failure."""
    monkeypatch.setattr("sys.argv", ["pipeline", "b.py", "a.py"])
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)
    monkeypatch.setattr("sys.argv", ["pipeline", before, after])

    assert pl.main() == 0


# ---------------------------------------------------------------------------
# Where an answer came from, and which setting the run used
# ---------------------------------------------------------------------------

def test_the_gemini_warning_fires_after_the_second_opinion_call(
        workspace, fake_ai, fake_runs, monkeypatch, capsys):
    """The warning must appear at the point a fallback second opinion arrives."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    def gemini_classify(evidence, mode):
        llm_client.LAST_PROVIDER = "Gemini"
        return {"label": cl.REAL_BUG, "confidence": "high", "reason": "because"}

    # Overrides the fake_ai fixture, so the second opinion comes from Gemini.
    monkeypatch.setattr(cl, "llm_classify", gemini_classify)

    pl.run_pipeline(before, after, ai_second_opinion=True)

    assert "AN ANSWER CAME FROM GEMINI" in capsys.readouterr().out


def test_the_json_says_the_fallback_setting():
    on = pl.make_report("b.py", "a.py", "n", [], [])
    off = pl.make_report("b.py", "a.py", "n", [], [], fallback_allowed=False)

    assert on["fallback"] is True
    assert off["fallback"] is False


def test_the_json_says_how_many_answers_came_from_gemini():
    report = pl.make_report("b.py", "a.py", "n", [], [], gemini_answers=3)

    assert report["gemini_answers"] == 3


def test_the_header_says_the_fallback_setting():
    on = pl.format_report(pl.make_report("b.py", "a.py", "n", [], []))
    off = pl.format_report(pl.make_report("b.py", "a.py", "n", [], [],
                                          fallback_allowed=False))

    assert "fallback: on" in on
    assert "fallback: off" in off


def test_the_header_says_how_many_answers_came_from_gemini():
    text = pl.format_report(
        pl.make_report("b.py", "a.py", "n", [], [], gemini_answers=3))

    assert "answers from Gemini: 3" in text


def test_a_default_run_names_the_setting_and_a_zero_count(workspace, fake_ai,
                                                          fake_runs,
                                                          monkeypatch):
    """A run that asks no Gemini still says so, so the report is complete."""
    one_change(monkeypatch, fake_change("get_recent_scores"))
    before, after = write_modules(workspace)

    report = pl.run_pipeline(before, after)
    text = pl.format_report(report)

    assert report["fallback"] is True
    assert report["gemini_answers"] == 0
    assert "fallback: on" in text
    assert "answers from Gemini: 0" in text


def test_a_run_counts_every_answer_that_came_from_gemini(workspace, fake_runs,
                                                         monkeypatch):
    """Both functions got their test from Gemini, so the count is two."""
    one_change(monkeypatch, fake_change("first"), fake_change("second"))
    before, after = write_modules(workspace)

    def gemini_generate_tests(change):
        llm_client.LAST_PROVIDER = "Gemini"
        return GENERATED_TEST

    monkeypatch.setattr(pl.tg, "generate_tests", gemini_generate_tests)

    report = pl.run_pipeline(before, after)

    assert report["gemini_answers"] == 2
    assert "answers from Gemini: 2" in pl.format_report(report)
