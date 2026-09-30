"""Tests for the one-command pipeline.

Nothing here calls a real AI or touches the internet. The AI is replaced by a
fake, and so are the test runs, so these tests are quick and always give the
same answer.
"""

import json
from pathlib import Path

import pytest

from prsentinel import classifier as cl
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
    """Fixed test results, read fresh each time so a test can change them."""

    def __init__(self, wanted):
        self.wanted = wanted

    def before_run(self):
        """One run against the old code."""
        return fake_run(self.wanted["before"])

    def after_run(self):
        """One run against the new code, with a message for each failure."""
        messages = {name: f"assert failed in {name}"
                    for name in self.wanted["after"]}
        return fake_run(self.wanted["after"], messages)

    def rerun_run(self):
        """The reruns against the new code."""
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
    assert list(folder.glob("*.bak")) == []


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
