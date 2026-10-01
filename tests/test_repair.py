"""Tests for the repair loop.

A repair is the riskiest thing this tool does, because it rewrites a test that
was working badly and could quietly make the whole suite weaker. So these tests
are mostly about what is NOT allowed to happen:

- a real bug is never repaired away, and neither is a flaky test;
- the real file is never touched until a repair is accepted;
- a repair that damages another test is thrown away and tried again;
- a repair that crashes, or that comes back with no code, leaves the file alone;
- the number of AI calls is capped for the whole run.

Nothing here calls a real AI or runs real pytest. The AI is a fake that hands
back fixed test code, and the runs are fixed results keyed on that code.
"""

import re
from pathlib import Path

import pytest

from prsentinel import classifier as cl
from prsentinel import config as cfg
from prsentinel import pipeline as pl
from prsentinel import repair as rp
from prsentinel import test_runner as tr

from test_pipeline import (fake_change, fake_run, one_change,  # noqa: F401
                           workspace, write_modules)


# ---------------------------------------------------------------------------
# Small pieces of the world
# ---------------------------------------------------------------------------

def a_change(old_code="def get_recent_scores(scores, window):\n"
                      "    return scores[-window:]\n",
             new_code="def get_recent_scores(scores, window):\n"
                      "    return scores[-window - 1:]\n"):
    """One change, in the shape diff_extractor hands back."""
    change = fake_change("get_recent_scores")
    change["old_code"] = old_code
    change["new_code"] = new_code
    return change


def row(name, before, after, label, detail=None):
    """One row, as evaluate_tests hands it back."""
    detail = detail if detail is not None else f"assert failed in {name}"
    return {"name": name, "display": name.split("::")[-1], "before": before,
            "after": after, "label": label, "detail": detail,
            "detail_full": detail}


def judgement(test, verdict=cl.BAD_TEST, label=tr.TEST_WRONG_ON_BEFORE,
              reason="the test is asking for something odd"):
    """One judgement, as judge_one_test hands it back."""
    return {"test": test, "label": label, "verdict": verdict, "reason": reason,
            "before": tr.FAILED, "after": tr.FAILED, "rerun": {},
            "ai_verdict": "", "ai_confidence": "", "ai_reason": "",
            "ai_agrees": None}


def outcome(path, function="get_recent_scores"):
    """One outcome, as generate_test_files hands it back."""
    return {"function": function, "change_type": "modified", "path": str(path),
            "error": "", "skipped": False, "backed_up": False,
            "backup": ""}


def result(judgements):
    """One file's worth of checked results."""
    return {"test_file": "test_x.py",
            "counts": {}, "judgements": list(judgements), "needs_a_look": []}


def write_test_file(workspace, body="# the original, wrong test file\n"):
    """Put a test file on disk where the pipeline expects it."""
    folder = workspace / "generated_tests" / "my_example"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "test_get_recent_scores.py"
    path.write_text(body, encoding="utf-8")
    return path


def candidate_source(marker):
    """Test code whose first line is a marker the fake runner can read.

    The marker is what lets one fake runner answer differently for each
    attempt, without any test having to reach inside the real code.
    """
    return (f"# {marker}\n"
            f"from target import get_recent_scores\n\n\n"
            f"def test_bad():\n    assert True\n")


class Runs:
    """Fixed runs, chosen by the marker on the first line of the test file."""

    def __init__(self, candidates):
        # marker -> {"before": {...}, "after": {...}, "rerun": {...}}
        self.candidates = candidates
        self.counts = {"run_tests": 0, "rerun_failures": 0}

    def marker(self, test_file):
        first = Path(test_file).read_text(encoding="utf-8").splitlines()[0]
        return first.lstrip("#").strip()

    def run_tests(self, module, test, **kwargs):
        spec = self.candidates[self.marker(test)]
        if "after" in Path(module).name:
            self.counts["run_tests"] += 1
            return fake_run(spec["after"], spec.get("messages"))
        self.counts["run_tests"] += 1
        return fake_run(spec["before"])

    def rerun_failures(self, module, test, **kwargs):
        spec = self.candidates[self.marker(test)]
        self.counts["rerun_failures"] += 1
        return {"status": tr.OK, "times": 5, "tests": spec["rerun"],
                "error": ""}


class RepairAI:
    """A fake AI. pick(attempt, call_number) picks the reply for each call."""

    def __init__(self, pick=None):
        self.pick = pick or (lambda attempt, call: candidate_source(
            f"attempt-{attempt}"))
        self.prompts = []
        self.calls = 0

    def __call__(self, prompt, temperature):
        self.calls += 1
        self.prompts.append(prompt)
        attempt = int(re.search(r"attempt (\d+) of", prompt).group(1))
        reply = self.pick(attempt, self.calls)
        return f"Here is the corrected file.\n```python\n{reply}\n```\n"


class RepairWorld:
    """The two fakes the loop needs: baseline rows and candidate runs."""

    def __init__(self):
        self.baseline = []

    def install(self, monkeypatch, candidates):
        runs = Runs(candidates)
        monkeypatch.setattr(pl.tr, "run_tests", runs.run_tests)
        monkeypatch.setattr(pl.tr, "rerun_failures", runs.rerun_failures)
        monkeypatch.setattr(pl.tr, "evaluate_tests",
                            lambda before, after, test: list(self.baseline))
        return runs


@pytest.fixture
def rep():
    """A repair world, before its fakes have been installed."""
    return RepairWorld()


def always_fails():
    return {"passes": 0, "fails": 5, "verdict": tr.ALWAYS_FAILS}


def catching_candidate(marker, test="t::test_bad"):
    """A candidate where the repaired test passes before and fails after.

    That is what a useful repair looks like: it now states what the old code
    did, and it still notices when the change breaks it.
    """
    return {
        "before": {test: tr.PASSED, "t::test_good": tr.PASSED,
                   "t::test_catches": tr.PASSED},
        "after": {test: tr.FAILED, "t::test_good": tr.PASSED,
                  "t::test_catches": tr.FAILED},
        "rerun": {test: always_fails(),
                  "t::test_catches": always_fails()},
    }


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------

def test_the_prompt_shows_the_old_code():
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 1)

    assert "return scores[-window:]" in prompt


def test_the_prompt_shows_the_new_code():
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 1)

    assert "return scores[-window - 1:]" in prompt


def test_the_prompt_shows_the_whole_test_file():
    prompt = rp.build_repair_prompt(a_change(), "def test_bad():\n    pass\n",
                                    "t::test_bad", "m", 1)

    assert "def test_bad():" in prompt


def test_the_prompt_names_the_test_and_shows_its_message():
    prompt = rp.build_repair_prompt(a_change(), "x", "test_get.py::test_bad",
                                    "E   assert [] == [3]", 1)

    assert "test_get.py::test_bad" in prompt
    assert "assert [] == [3]" in prompt


def test_the_prompt_asks_for_the_old_behaviour():
    """The old code is the specification, and the prompt has to say so."""
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 1)

    assert "BEFORE the change" in prompt


def test_the_prompt_never_says_the_code_is_the_problem():
    """A writer told the code is wrong would weaken the test to match it."""
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 1)

    for banned in ("REAL_BUG", "BAD_TEST", "the code is wrong",
                   "the code has a bug"):
        assert banned not in prompt


def test_the_prompt_never_says_make_it_pass():
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 1)

    lowered = prompt.lower()
    assert "make it pass" not in lowered
    assert "make the test pass" not in lowered


def test_the_prompt_says_which_module_to_import_from():
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 1)

    assert "from target import get_recent_scores" in prompt


def test_the_prompt_says_to_leave_the_other_tests_alone():
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 1)

    assert "Keep every other test in the file as it is." in prompt


def test_the_prompt_numbers_the_attempt():
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 2)

    assert f"attempt 2 of {cfg.MAX_REPAIR_ATTEMPTS}" in prompt


def test_the_prompt_has_no_weakening_note_by_default():
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 1)

    assert "previous attempt" not in prompt


def test_the_prompt_warns_when_the_last_try_weakened_the_file():
    prompt = rp.build_repair_prompt(a_change(), "x", "t::test_bad", "m", 2,
                                    weakened_before=True)

    assert "previous attempt" in prompt
    assert "other tests" in prompt


def test_a_new_function_still_gets_a_prompt():
    """There is no old behaviour to match, and that must be said."""
    change = a_change(old_code="")

    prompt = rp.build_repair_prompt(change, "x", "t::test_bad", "m", 1)

    assert "no earlier version" in prompt


def test_repair_test_asks_the_ai_and_returns_its_code():
    seen = []

    def ask(prompt, temperature):
        seen.append((prompt, temperature))
        return "sure\n```python\nprint('good')\n```\nthere"

    code = rp.repair_test(a_change(), "x", "t::test_bad", "m", 1, ask=ask)

    assert code == "print('good')\n"
    assert seen[0][1] == cfg.GENERATION_TEMPERATURE


def test_repair_test_refuses_a_reply_with_no_code():
    with pytest.raises(ValueError):
        rp.repair_test(a_change(), "x", "t::test_bad", "m", 1,
                       ask=lambda prompt, temperature: "I cannot help.")


def test_repair_file_name_keeps_the_original_name():
    assert rp.repair_file_name("/some/temp/place/test_x.py") == "test_x.py"


# ---------------------------------------------------------------------------
# A repair that works
# ---------------------------------------------------------------------------

def test_a_repair_that_works_on_the_first_try_is_kept(rep, monkeypatch,
                                                      workspace):
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE),
                    row("t::test_good", tr.PASSED, tr.PASSED, tr.NO_SIGNAL)]
    rep.install(monkeypatch, {"attempt-1": catching_candidate("attempt-1")})
    ai = RepairAI()

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=ai)

    assert len(records) == 1
    assert records[0]["outcome"] == "repaired"
    assert records[0]["attempts"] == 1
    assert records[0]["final_verdict"] == cl.REAL_BUG
    assert ai.calls == 1
    # The candidate was copied over the real file, and the old copy kept.
    assert "# attempt-1" in test_file.read_text(encoding="utf-8")
    assert list(test_file.parent.glob("test_get_recent_scores.py.bak*"))


def test_a_repair_can_take_two_tries(rep, monkeypatch, workspace):
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE)]
    bad = {"before": {"t::test_bad": tr.FAILED},
           "after": {"t::test_bad": tr.FAILED}, "rerun": {}}
    good = {"before": {"t::test_bad": tr.PASSED},
            "after": {"t::test_bad": tr.FAILED},
            "rerun": {"t::test_bad": always_fails()}}
    rep.install(monkeypatch, {"attempt-1": bad, "attempt-2": good})
    ai = RepairAI()

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=ai)

    assert records[0]["attempts"] == 2
    assert records[0]["outcome"] == "repaired"
    assert ai.calls == 2


def test_a_repaired_test_is_relabelled_in_the_judgement(rep, monkeypatch,
                                                        workspace):
    """The report must say what the test says now, not what the old file said."""
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE)]
    rep.install(monkeypatch, {"attempt-1": catching_candidate("attempt-1")})
    mark = judgement("t::test_bad")
    results = [result([mark])]

    pl.repair_bad_tests(before, after, [outcome(test_file)], results,
                        ask=RepairAI())

    assert mark["verdict"] == cl.REAL_BUG
    assert mark["label"] == tr.CATCHES_CHANGE
    assert mark["repair"]["outcome"] == "repaired"
    assert mark["repair"]["attempts"] == 1


def test_a_candidate_that_passes_on_both_versions_is_kept(rep, monkeypatch,
                                                          workspace):
    """A harmless change plus a wrong test: fixing the test is enough.

    The classifier has no answer for "this test is fine now", so without the
    label rule this repair would be thrown away and described as BAD_TEST.
    """
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE),
                    row("t::test_good", tr.PASSED, tr.PASSED, tr.NO_SIGNAL)]
    fixed = {
        "before": {"t::test_bad": tr.PASSED, "t::test_good": tr.PASSED},
        "after": {"t::test_bad": tr.PASSED, "t::test_good": tr.PASSED},
        "rerun": {"t::test_bad": {"passes": 5, "fails": 0,
                                  "verdict": tr.ALWAYS_PASSES}},
    }
    rep.install(monkeypatch, {"attempt-1": fixed})

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=RepairAI())

    assert records[0]["outcome"] == "repaired"
    assert records[0]["final_label"] == tr.NO_SIGNAL
    assert records[0]["final_verdict"] == tr.NO_SIGNAL


def test_a_candidate_that_turned_the_test_flaky_is_thrown_away(
        rep, monkeypatch, workspace):
    """Passing on both single runs is not enough if reruns disagree."""
    before, after = write_modules(workspace)
    original = "# the original, wrong test file\n"
    test_file = write_test_file(workspace, original)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE)]
    flaky = {
        "before": {"t::test_bad": tr.PASSED},
        "after": {"t::test_bad": tr.PASSED},
        "rerun": {"t::test_bad": {"passes": 3, "fails": 2, "verdict": tr.FLAKY}},
    }
    rep.install(monkeypatch, {"attempt-1": flaky, "attempt-2": flaky})

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=RepairAI())

    assert records[0]["outcome"] == "unrepaired BAD_TEST"
    assert test_file.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# A repair that leaves the suite weaker is thrown away
# ---------------------------------------------------------------------------

def test_a_repair_that_stops_a_test_catching_is_thrown_away(rep, monkeypatch,
                                                            workspace):
    before, after = write_modules(workspace)
    original = "# the original, wrong test file\n"
    test_file = write_test_file(workspace, original)
    one_change(monkeypatch, a_change())

    # t::test_catches used to catch the change. The candidate makes it pass on
    # both versions, so a real bug would now slip past it.
    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE),
                    row("t::test_catches", tr.PASSED, tr.FAILED,
                        tr.CATCHES_CHANGE)]
    weakened = {
        "before": {"t::test_bad": tr.PASSED, "t::test_catches": tr.PASSED},
        "after": {"t::test_bad": tr.FAILED, "t::test_catches": tr.PASSED},
        "rerun": {"t::test_bad": always_fails(),
                  "t::test_catches": {"passes": 5, "fails": 0,
                                      "verdict": tr.ALWAYS_PASSES}},
    }
    rep.install(monkeypatch, {"attempt-1": weakened, "attempt-2": weakened})

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=RepairAI())

    assert records[0]["outcome"] == "weakened"
    assert test_file.read_text(encoding="utf-8") == original


def test_a_repair_that_breaks_a_passing_test_on_the_old_code_is_thrown_away(
        rep, monkeypatch, workspace):
    before, after = write_modules(workspace)
    original = "# the original, wrong test file\n"
    test_file = write_test_file(workspace, original)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE),
                    row("t::test_good", tr.PASSED, tr.PASSED, tr.NO_SIGNAL)]
    broken = {
        "before": {"t::test_bad": tr.PASSED, "t::test_good": tr.FAILED},
        "after": {"t::test_bad": tr.FAILED, "t::test_good": tr.FAILED},
        "rerun": {"t::test_bad": always_fails()},
    }
    rep.install(monkeypatch, {"attempt-1": broken, "attempt-2": broken})

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=RepairAI())

    assert records[0]["outcome"] == "weakened"
    assert test_file.read_text(encoding="utf-8") == original


def test_a_weakening_repair_is_retried_with_a_note(rep, monkeypatch,
                                                   workspace):
    """A rejection is a used attempt, and the next prompt says what went wrong."""
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE),
                    row("t::test_catches", tr.PASSED, tr.FAILED,
                        tr.CATCHES_CHANGE)]
    weakened = {
        "before": {"t::test_bad": tr.PASSED, "t::test_catches": tr.PASSED},
        "after": {"t::test_bad": tr.FAILED, "t::test_catches": tr.PASSED},
        "rerun": {"t::test_bad": always_fails()},
    }
    rep.install(monkeypatch, {"attempt-1": weakened,
                              "attempt-2": catching_candidate("attempt-2")})
    ai = RepairAI()

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=ai)

    assert records[0]["outcome"] == "repaired"
    assert records[0]["attempts"] == 2
    assert "previous attempt" not in ai.prompts[0]
    assert "previous attempt" in ai.prompts[1]


# ---------------------------------------------------------------------------
# What is never repaired
# ---------------------------------------------------------------------------

def test_a_real_bug_is_never_sent_for_repair(rep, monkeypatch, workspace):
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())
    rep.install(monkeypatch, {})
    ai = RepairAI()

    records = pl.repair_bad_tests(
        before, after, [outcome(test_file)],
        [result([judgement("t::test_bad", verdict=cl.REAL_BUG,
                           label=tr.CATCHES_CHANGE)])],
        ask=ai)

    assert records == []
    assert ai.calls == 0


def test_a_flaky_test_is_never_sent_for_repair(rep, monkeypatch, workspace):
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())
    rep.install(monkeypatch, {})
    ai = RepairAI()

    records = pl.repair_bad_tests(
        before, after, [outcome(test_file)],
        [result([judgement("t::test_bad", verdict=cl.FLAKY,
                           label=tr.CATCHES_CHANGE)])],
        ask=ai)

    assert records == []
    assert ai.calls == 0


def test_a_file_with_nothing_wrong_makes_no_calls(rep, monkeypatch, workspace):
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())
    rep.install(monkeypatch, {})
    ai = RepairAI()

    records = pl.repair_bad_tests(
        before, after, [outcome(test_file)],
        [result([judgement("t::test_good", verdict=cl.REAL_BUG,
                           label=tr.CATCHES_CHANGE)])],
        ask=ai)

    assert records == []
    assert ai.calls == 0


# ---------------------------------------------------------------------------
# Failures inside the loop
# ---------------------------------------------------------------------------

def test_a_repair_that_never_works_leaves_the_file_alone(rep, monkeypatch,
                                                         workspace):
    before, after = write_modules(workspace)
    original = "# the original, wrong test file\n"
    test_file = write_test_file(workspace, original)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE)]
    still_wrong = {"before": {"t::test_bad": tr.FAILED},
                   "after": {"t::test_bad": tr.FAILED}, "rerun": {}}
    rep.install(monkeypatch, {"attempt-1": still_wrong,
                              "attempt-2": still_wrong})

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=RepairAI())

    assert records[0]["outcome"] == "unrepaired BAD_TEST"
    assert records[0]["attempts"] == cfg.MAX_REPAIR_ATTEMPTS
    assert test_file.read_text(encoding="utf-8") == original
    assert not list(test_file.parent.glob("test_get_recent_scores.py.bak*"))


def test_an_empty_reply_costs_an_attempt_but_not_the_run(rep, monkeypatch,
                                                         workspace):
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE)]
    rep.install(monkeypatch, {"attempt-2": catching_candidate("attempt-2")})

    calls = {"n": 0}

    def ask(prompt, temperature):
        calls["n"] += 1
        if calls["n"] == 1:
            return "I am not sure how to correct this one."
        return "here\n```python\n" + candidate_source("attempt-2") + "\n```"

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=ask)

    assert records[0]["attempts"] == 2
    assert records[0]["outcome"] == "repaired"


def test_a_candidate_that_cannot_be_run_is_thrown_away(rep, monkeypatch,
                                                       workspace):
    """A crash in the runner must not escape the loop or touch the file."""
    before, after = write_modules(workspace)
    original = "# the original, wrong test file\n"
    test_file = write_test_file(workspace, original)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE)]

    def explode(module, test, **kwargs):
        raise RuntimeError("pytest could not even start")

    monkeypatch.setattr(pl.tr, "run_tests", explode)
    monkeypatch.setattr(pl.tr, "rerun_failures", explode)
    monkeypatch.setattr(pl.tr, "evaluate_tests",
                        lambda before, after, test: list(rep.baseline))

    records = pl.repair_bad_tests(before, after, [outcome(test_file)],
                                  [result([judgement("t::test_bad")])],
                                  ask=RepairAI())

    assert records[0]["outcome"] == "unrepaired BAD_TEST"
    assert test_file.read_text(encoding="utf-8") == original


def test_a_candidate_is_never_run_in_the_real_folder(rep, monkeypatch,
                                                     workspace):
    """The candidate goes somewhere temporary, so nothing is left behind."""
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())

    rep.baseline = [row("t::test_bad", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE)]
    wrong = {"before": {"t::test_bad": tr.FAILED},
             "after": {"t::test_bad": tr.FAILED}, "rerun": {}}
    rep.install(monkeypatch, {"attempt-1": wrong, "attempt-2": wrong})

    pl.repair_bad_tests(before, after, [outcome(test_file)],
                        [result([judgement("t::test_bad")])],
                        ask=RepairAI())

    # Only the one original file is in the folder: no half-run candidates.
    assert sorted(p.name for p in test_file.parent.iterdir()) == [
        "test_get_recent_scores.py"]


# ---------------------------------------------------------------------------
# The call budget
# ---------------------------------------------------------------------------

def test_the_budget_stops_further_repairs(rep, monkeypatch, workspace):
    before, after = write_modules(workspace)
    test_file = write_test_file(workspace)
    one_change(monkeypatch, a_change())
    monkeypatch.setattr(cfg, "MAX_REPAIR_CALLS_PER_RUN", 1)

    rep.baseline = [row("t::test_a", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE),
                    row("t::test_b", tr.FAILED, tr.FAILED,
                        tr.TEST_WRONG_ON_BEFORE)]
    good = {"before": {"t::test_a": tr.PASSED, "t::test_b": tr.PASSED},
            "after": {"t::test_a": tr.FAILED, "t::test_b": tr.FAILED},
            "rerun": {"t::test_a": always_fails()}}
    rep.install(monkeypatch, {"attempt-1": good})
    ai = RepairAI()

    records = pl.repair_bad_tests(
        before, after, [outcome(test_file)],
        [result([judgement("t::test_a"), judgement("t::test_b")])],
        ask=ai)

    assert records[0]["outcome"] == "repaired"
    assert records[1]["outcome"] == "not attempted, repair budget reached"
    assert records[1]["attempts"] == 0
    assert ai.calls == 1


def test_the_repair_settings_have_sensible_defaults():
    assert cfg.MAX_REPAIR_ATTEMPTS == 2
    assert cfg.MAX_REPAIR_CALLS_PER_RUN == 10


def test_repair_is_off_by_default():
    import inspect

    default = inspect.signature(pl.run_pipeline).parameters["repair_tests"]
    assert default.default is False


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def repair_record(outcome="repaired", attempts=1,
                  final_verdict=cl.REAL_BUG, final_label=tr.CATCHES_CHANGE):
    return {"function": "get_recent_scores", "test_file": "test_x.py",
            "test": "t::test_bad", "attempts": attempts, "outcome": outcome,
            "final_verdict": final_verdict, "final_reason": "because",
            "final_label": final_label, "backup": ""}


def sample_report(repairs, repair=False):
    function = {"function": "get_recent_scores", "change_type": "modified",
                "test_file": "test_x.py", "from_folder": "", "counts": {},
                "judgements": [], "needs_a_look": []}
    return {"name": "my_example", "before": "before.py", "after": "after.py",
            "tests_source": "generated", "functions": [function],
            "generation_failed": [], "skipped": [], "repairs": repairs,
            "repair": repair, "summary": "one bug found"}


def test_the_json_report_carries_a_repairs_key():
    report = pl.make_report("b.py", "a.py", "n", [], [], repairs=[])

    assert report["repairs"] == []


def test_make_report_keeps_the_repairs_it_is_given():
    records = [repair_record()]

    report = pl.make_report("b.py", "a.py", "n", [], [], repairs=records)

    assert report["repairs"] == records


def test_the_report_shows_each_repair_with_its_attempts():
    text = pl.format_report(sample_report([repair_record(attempts=2)]))

    assert "--- Repairs ---" in text
    assert "get_recent_scores / t::test_bad" in text
    assert "attempts    : 2" in text
    assert cl.REAL_BUG in text


def test_the_report_counts_repaired_unrepaired_and_weakened():
    text = pl.format_report(sample_report([
        repair_record(), repair_record(outcome="repaired"),
        repair_record(outcome="unrepaired BAD_TEST"),
        repair_record(outcome="weakened"),
    ]))

    assert "repaired: 2" in text
    assert "unrepaired: 1" in text
    assert "weakened: 1" in text


def test_a_report_with_no_repairs_has_no_repairs_section():
    text = pl.format_report(sample_report([]))

    assert "--- Repairs ---" not in text


def test_a_run_without_repair_still_has_an_empty_repairs_key():
    """The saved JSON always says whether any repair happened."""
    report = pl.make_report("b.py", "a.py", "n", [], [])

    assert report["repairs"] == []


def test_the_json_report_says_whether_repair_was_on():
    off = pl.make_report("b.py", "a.py", "n", [], [])
    on = pl.make_report("b.py", "a.py", "n", [], [], repair_tests=True)

    assert off["repair"] is False
    assert on["repair"] is True


def test_the_report_header_says_repair_off_by_default():
    text = pl.format_report(sample_report([]))

    assert "repair: off" in text


def test_the_report_header_says_repair_on_when_it_was_asked_for():
    text = pl.format_report(sample_report([], repair=True))

    assert "repair: on" in text


def test_a_repair_run_with_nothing_to_repair_still_shows_the_section():
    """Repair on plus no bad tests must not look the same as repair off."""
    text = pl.format_report(sample_report([], repair=True))

    assert "--- Repairs ---" in text
    assert "nothing to repair" in text
    assert "repaired: 0" in text


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def test_repair_and_reuse_tests_cannot_be_combined(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv",
                        ["pipeline", "b.py", "a.py", "--repair",
                         "--reuse-tests"])

    assert pl.main() == 2
    printed = capsys.readouterr().out
    assert "cannot be used together" in printed


def test_the_refusal_names_both_flags(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv",
                        ["pipeline", "b.py", "a.py", "--repair",
                         "--reuse-tests"])

    pl.main()
    printed = capsys.readouterr().out

    assert "--repair" in printed
    assert "--reuse-tests" in printed


def test_the_refusal_happens_before_any_file_is_read(monkeypatch, capsys):
    """Both paths are missing, and the refusal still wins, so it costs nothing."""
    monkeypatch.setattr("sys.argv",
                        ["pipeline", "no_such_before.py", "no_such_after.py",
                         "--repair", "--reuse-tests"])

    assert pl.main() == 2
    assert "Cannot read that file" not in capsys.readouterr().out
