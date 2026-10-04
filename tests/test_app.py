"""Tests for the demo web app (src/prsentinel/app.py).

Nothing here reaches a network, and one test makes that harder than a promise:
it blocks the socket itself while a saved-tests run goes through for real, so
anything that tried to open a connection would fail loudly instead of quietly
spending an allowance.

The end-to-end test really does run the pipeline, in a child process, on a
one-line function with mutation switched off. It is the only slow test in the
file and it is the one that proves the wiring.
"""

import io
import json
import subprocess
import sys
import threading
import time
from importlib.resources import files
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prsentinel import app as A
from prsentinel import config

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client():
    with TestClient(A.app) as made:
        yield made


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point the app's folders at a temporary place.

    Used by the tests that start a run but do not let it finish. The child
    process is faked there, so the real project folders are not needed and the
    real ones stay clean.
    """
    monkeypatch.setattr(A, "GENERATED", tmp_path / "generated")
    monkeypatch.setattr(A, "SCRATCH", tmp_path / "scratch")
    return tmp_path


# ---------------------------------------------------------------------------
# A fake child process
#
# The app starts a real process per run. Most tests do not need a real one, and
# a real one cannot be told to hang on cue, so these stand in for it.
# ---------------------------------------------------------------------------

# Every fake ever made, so no test can leave one running for the next test. The
# app allows a single run at a time, so a leaked child would answer 409 for
# every later test for entirely the wrong reason.
_EVERY_CHILD = []


@pytest.fixture(autouse=True)
def the_runner_is_left_free():
    yield
    for child in _EVERY_CHILD:
        child.release()
    wait_until_free()
    _EVERY_CHILD.clear()

class _SilentPipe:
    """Stands in for a child's output: no lines at all, ever.

    It waits to be let go before it ends, which is what a real pipe does while
    the child is still working, so the reader thread stays where a real one
    would be rather than finishing early.
    """

    def __init__(self, done):
        self._done = done

    def __iter__(self):
        self._done.wait()
        return iter(())


class FakeChild:
    """Looks enough like subprocess.Popen for Runner to work with."""

    def __init__(self, block=0.4):
        self.killed = False
        self._done = threading.Event()
        self._block = block
        _EVERY_CHILD.append(self)

    @property
    def stdout(self):
        return _SilentPipe(self._done)

    def wait(self, timeout=None):
        seconds = self._block if timeout is None else min(self._block, timeout)
        if not self._done.wait(seconds):
            raise subprocess.TimeoutExpired("fake", timeout)
        return 0

    def kill(self):
        self.killed = True
        self._done.set()

    def release(self):
        self._done.set()


@pytest.fixture
def fake_children(monkeypatch):
    """Replace the real Popen with FakeChild objects and hand back the list."""
    made = []

    def spawn(*args, **kwargs):
        child = FakeChild()
        made.append(child)
        return child

    monkeypatch.setattr(A.subprocess, "Popen", spawn)
    return made


def test_the_fake_child_is_well_behaved():
    """The fake has to behave like the real thing, or it hides bugs.

    It once looked right and was not: the stand-in for a child's output had no
    yield in it, so asking for it blocked for ever and the reader thread died
    with a message nobody read. The app was fine. The fake was not, and it had
    been quietly failing a dozen tests that still went green.
    """
    child = FakeChild()
    got = []

    def read():
        got.extend(child.stdout)

    reader = threading.Thread(target=read)
    reader.start()
    time.sleep(0.1)
    assert reader.is_alive(), "the fake pipe finished too early"
    assert got == []

    child.release()
    reader.join(timeout=5)
    assert not reader.is_alive()
    assert got == []

    with pytest.raises(subprocess.TimeoutExpired):
        FakeChild(block=0).wait(timeout=5)


def wait_until_free(seconds=5.0):
    """Wait for the one-run-at-a-time slot to clear."""
    limit = time.time() + seconds
    while time.time() < limit:
        if not A.RUNNER.busy():
            return True
        time.sleep(0.02)
    return False


def read_stream(client, run_id):
    """Read a run's events to the end, which is also what lets it clean up."""
    events = []
    with client.stream("GET", f"/api/stream?run_id={run_id}") as stream:
        content_type = stream.headers["content-type"]
        for line in stream.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return content_type, events


# ---------------------------------------------------------------------------
# The page is found through the installed package
# ---------------------------------------------------------------------------

def test_the_page_is_found_through_the_installed_package():
    """The page must come from the package, not from the current folder.

    A path built relative to wherever the app was started works on the machine
    of whoever wrote it and nowhere else, which is the failure this test exists
    to catch.
    """
    page = files("prsentinel") / "static" / "index.html"
    assert page.is_file()

    package_folder = Path(str(files("prsentinel"))).resolve()
    assert package_folder in page.resolve().parents


def test_the_page_is_read_the_same_way_from_any_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert "<!DOCTYPE html>" in A.page_text()


def test_the_page_has_the_controls_somebody_needs_to_press():
    page = A.page_text()
    for needed in ('id="run"', 'name="mode"', 'value="saved"', 'value="fresh"',
                   "EventSource", "/api/stream"):
        assert needed in page, needed


def test_the_page_shows_the_mutation_score_as_a_percentage():
    """It used to print the raw fraction, which read 0.6666666666666666.

    Checked against the source because there is no JavaScript here to run. It is
    a weak check, but it is enough to stop somebody tidying the rounding away
    without noticing what it puts on screen.
    """
    page = A.page_text()
    assert "Math.round(score.score * 100)" in page
    assert "score.score === null ? " not in page
    assert "not defined" in page


def test_the_page_never_asks_for_a_key():
    """A page that asked for a key would put one in the browser's memory."""
    page = A.page_text().lower()
    for forbidden in ("aiza", "api key", "password", "token"):
        assert forbidden not in page, forbidden


def test_the_package_ships_the_page_as_package_data():
    """A real install has to contain the page, not only a checkout."""
    text = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    assert '[tool.setuptools.package-data]' in text
    assert 'prsentinel = ["static/*.html"]' in text


def test_all_three_dependencies_are_pinned_and_named_in_both_places():
    requirements = (PROJECT / "requirements.txt").read_text(encoding="utf-8")
    pyproject = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    for package in ("fastapi==0.142.2", "uvicorn==0.54.0", "httpx==0.28.1"):
        assert package in requirements, package
        assert package in pyproject, package
    assert "These three are pinned exactly" in requirements
    assert "StarletteDeprecationWarning" in requirements


# ---------------------------------------------------------------------------
# The demo cases on disk
# ---------------------------------------------------------------------------

def test_every_demo_case_has_the_three_files_it_needs():
    cases = A.demo_cases()
    assert len(cases) == 3, [case["name"] for case in cases]
    for case in cases:
        folder = A.DEMOS / case["name"]
        assert (folder / "before.py").is_file()
        assert (folder / "after.py").is_file()
        assert (folder / case["test_file"]).is_file()


def test_each_demo_case_has_a_one_line_note_to_show_next_to_it():
    for case in A.demo_cases():
        assert case["note"], case["name"]


def test_a_demo_name_cannot_climb_out_of_the_demo_folder():
    for sneaky in ("../../etc", "..\\windows", "/etc", "a/b", ".", "..", ""):
        assert A.pick_demo(sneaky) is None, sneaky


def test_an_unknown_demo_name_is_refused(client):
    answer = client.post("/api/run", json={"demo": "no_such_case"})
    assert answer.status_code == 400
    assert "not one of the demo cases" in answer.json()["detail"]


def test_a_half_finished_demo_folder_is_not_offered(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "DEMOS", tmp_path)
    (tmp_path / "lonely").mkdir()
    (tmp_path / "lonely" / "before.py").write_text("x = 1\n", encoding="utf-8")
    assert A.demo_cases() == []


def test_the_two_reused_demo_cases_are_copies_and_the_originals_remain():
    """Copy, never move. The old answers still have to be answerable."""
    pairs = [
        ("examples/demo/round1_off_by_one/before.py",
         "examples/round1_off_by_one/before.py"),
        ("examples/demo/round1_off_by_one/test_get_recent_scores.py",
         "baselines/round1_off_by_one/test_get_recent_scores.py"),
        ("examples/demo/round2_mutable_default/before.py",
         "examples/round2_mutable_default/before.py"),
        ("examples/demo/round2_mutable_default/test_add_item_to_cart.py",
         "baselines/round2_mutable_default/test_add_item_to_cart.py"),
    ]
    for copied, original in pairs:
        assert (PROJECT / copied).read_bytes() == \
            (PROJECT / original).read_bytes(), copied


def test_the_three_verdict_case_produces_all_three_from_one_test_file():
    folder = A.DEMOS / "three_verdicts"
    tests = list(folder.glob("test_*.py"))
    assert len(tests) == 1, "the case must work as one saved test file"
    said = tests[0].read_text(encoding="utf-8")
    assert said.count("def test_") == 3, said


def test_the_flaky_test_is_flaky_because_of_a_set_and_not_a_counter():
    """The wobble has to come from real nondeterminism.

    A counter, a clock or a seeded random would be a trick, and a mentor who
    asks how the flake is faked would be right to. The check is on the code
    that actually runs, so the prose in the docstrings is free to explain
    itself without tripping it.
    """
    import ast

    folder = A.DEMOS / "three_verdicts"
    files_to_check = [folder / "before.py", folder / "after.py",
                      next(folder.glob("test_*.py"))]

    for path in files_to_check:
        said = path.read_text(encoding="utf-8")
        tree = ast.parse(said)

        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)
            elif isinstance(node, ast.Attribute):
                called.add(node.attr)

        for trick in ("random", "randint", "shuffle", "sample", "seed",
                      "getenv", "environ", "uuid", "time", "monotonic",
                      "perf_counter", "counter", "PYTHONHASHSEED"):
            assert trick not in called, f"{path.name} uses {trick}"

    before = (folder / "before.py").read_text(encoding="utf-8")
    assert "REWARD_WORDS = {" in before
    assert "next(iter(REWARD_WORDS))" in before


def test_only_best_offer_changed_between_the_two_halves():
    """reward_word is scenery. It must be identical on both sides."""
    before = (A.DEMOS / "three_verdicts" / "before.py").read_text(
        encoding="utf-8")
    after = (A.DEMOS / "three_verdicts" / "after.py").read_text(
        encoding="utf-8")

    def reward(text):
        start = text.index("def reward_word")
        return text[start:]

    assert reward(before) == reward(after)
    assert before.count("def ") == after.count("def ") == 2


# ---------------------------------------------------------------------------
# Saved tests make no network call
# ---------------------------------------------------------------------------

def run_child_here(job):
    """Call the child half in this process, with its output captured.

    run_once prints its progress with markers meant for a parent process, and
    while it does that sys.stdout is a stand-in. Putting the old one back
    afterwards matters, or pytest's own capture is left pointing at a string.
    """
    saved_out = sys.stdout
    try:
        code = A.run_once(job)
        return code, sys.__stdout__.getvalue()
    finally:
        sys.stdout = saved_out


def test_saved_tests_make_no_network_call(monkeypatch):
    """Block the socket, then run a saved-tests job for real.

    A saved run reuses a test file that is already on disk. If anything in it
    tried to open a connection, this fails loudly.
    """
    import socket

    def refused(*args, **kwargs):
        raise AssertionError("the app tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket.socket, "connect_ex", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(sys, "__stdout__", io.StringIO())

    case = A.DEMOS / "three_verdicts"
    name = "demo_network_probe"

    # The saved test has to be in place, or the run would find nothing at all
    # and a test that found nothing would pass for the wrong reason.
    folder = A.GENERATED / name
    assert A.claim_folder(folder) == ""
    try:
        test_file = next(case.glob("test_*.py"))
        (folder / test_file.name).write_bytes((case / test_file.name).read_bytes())

        code, said = run_child_here({"before": str(case / "before.py"),
                                     "after": str(case / "after.py"),
                                     "name": name,
                                     "mode": "saved",
                                     "mutation": False})
    finally:
        A.clean_up(name, folder, None)

    assert code == 0
    marked = [line for line in said.splitlines() if line.startswith("R ")]
    assert len(marked) == 1, said[-400:]

    report = json.loads(marked[0][2:])
    assert report["app_mode"] == "saved"
    assert report["gemini_answers"] == 0
    assert report["fallback"] is False
    assert report["tests_source"] == "reused from generated_tests"
    assert report["functions"], "the saved test was not used at all"


def test_the_saved_run_really_reused_a_saved_test(monkeypatch):
    """The saved test has to be the one on disk, not a fresh one."""
    monkeypatch.setattr(sys, "__stdout__", io.StringIO())
    case = A.DEMOS / "three_verdicts"
    name = "demo_source_probe"

    folder = A.GENERATED / name
    assert A.claim_folder(folder) == ""
    try:
        test_file = next(case.glob("test_*.py"))
        shutil_bytes = (folder / test_file.name).write_bytes(
            (case / test_file.name).read_bytes())
        assert shutil_bytes > 0

        code, said = run_child_here({"before": str(case / "before.py"),
                                     "after": str(case / "after.py"),
                                     "name": name,
                                     "mode": "saved",
                                     "mutation": False})
    finally:
        A.clean_up(name, folder, None)

    assert code == 0
    report = json.loads([line for line in said.splitlines()
                         if line.startswith("R ")][0][2:])
    assert report["tests_source"] == "reused from generated_tests"
    assert report["functions"][0]["from_folder"] == "generated_tests"


def test_a_saved_run_is_never_refused_for_a_missing_key(client, sandbox,
                                                          fake_children,
                                                          monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    answer = client.post("/api/run", json={"demo": "round1_off_by_one",
                                           "mode": "saved"})
    assert answer.status_code == 200, answer.text
    assert fake_children, "no run was started"


def test_fresh_tests_are_refused_when_the_key_is_not_set(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    answer = client.post("/api/run", json={"demo": "round1_off_by_one",
                                           "mode": "fresh"})
    assert answer.status_code == 400
    said = answer.json()["detail"]
    assert "No Groq key is set" in said
    assert "Saved tests" in said, "the answer should point at the way out"


# ---------------------------------------------------------------------------
# A key never reaches the browser
# ---------------------------------------------------------------------------

def test_no_answer_the_app_can_give_contains_a_key(client, monkeypatch):
    sentinel = "PRIVATEKEYMATERIAL0001doNotPrint"
    monkeypatch.setenv("GROQ_API_KEY", sentinel)

    answers = [
        client.get("/").text,
        client.get("/api/demos").text,
        client.get("/api/state").text,
        client.post("/api/run", json={"demo": "no_such_case"}).text,
        client.post("/api/run", json={"before": "", "after": ""}).text,
        client.get("/api/stream?run_id=nothing-here").text,
    ]
    for text in answers:
        assert sentinel not in text


def test_the_source_never_copies_a_key_anywhere():
    """os.environ may only be asked a question, never taken apart.

    Reading the whole environment, or one variable by name, is how a key ends
    up in a response. The two shapes that are allowed are a yes/no check and a
    copy of the environment to hand to the child process.
    """
    import re

    source = (PROJECT / "src" / "prsentinel" / "app.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in source.splitlines()
                     if not line.strip().startswith("#"))

    for after in re.findall(r"os\.environ(.{0,4})", code):
        assert after.startswith(".get") or after.startswith(")"), repr(after)

    assert "logging" not in code, "the app should print, not log"
    assert "GROQ_API_KEY" in code, "the app should still know the name"


def test_the_child_is_given_an_empty_backup_key(monkeypatch):
    """The second provider is off in the child as well as in the flags."""
    captured = {}
    child = FakeChild()

    def spawn(args, **kwargs):
        captured.update(kwargs.get("env") or {})
        return child

    monkeypatch.setenv("GEMINI_API_KEY", "second-provider-key")
    monkeypatch.setenv("GROQ_API_KEY", "main-provider-key")
    monkeypatch.setattr(A.subprocess, "Popen", spawn)

    try:
        A.RUNNER.start("demo_env_probe", "saved", None, None,
                       PROJECT / "job.json")
    finally:
        child.release()

    assert captured["GEMINI_API_KEY"] == ""
    assert captured["GROQ_API_KEY"] == "main-provider-key"
    assert captured["PYTHONIOENCODING"] == "utf-8"
    assert wait_until_free()


# ---------------------------------------------------------------------------
# One run at a time
# ---------------------------------------------------------------------------

def test_a_second_click_while_a_run_is_going_is_refused(client, sandbox,
                                                        fake_children):
    first = client.post("/api/run", json={"demo": "round1_off_by_one"})
    assert first.status_code == 200, first.text
    run_id = first.json()["run_id"]

    second = client.post("/api/run", json={"demo": "round1_off_by_one"})
    assert second.status_code == 409
    assert "already going" in second.json()["detail"]
    assert len(fake_children) == 1, "a second child was started anyway"

    # The refused click must not have taken away the running job's files.
    assert A.RUNNER.find(run_id) is not None
    assert (A.GENERATED / "demo_round1_off_by_one").is_dir()

    for child in fake_children:
        child.release()
    assert wait_until_free()


def test_two_clicks_at_the_same_moment_cannot_collide(client, sandbox,
                                                      fake_children):
    """Both requests must not get as far as writing files.

    The saved-test folder is named after the case, because that is the name the
    pipeline looks the test up by, so it cannot be made unique per run. Two
    clicks landing together would both pass the busy check, both write into that
    one folder, and the loser would delete the winner's files while tidying up
    after itself. START_LOCK is what stops it.
    """
    answers = []
    lock = threading.Lock()

    def press():
        answer = client.post("/api/run", json={"demo": "round1_off_by_one"})
        with lock:
            answers.append(answer.status_code)

    pressers = [threading.Thread(target=press) for _ in range(4)]
    for one in pressers:
        one.start()
    for one in pressers:
        one.join(timeout=30)

    assert len(answers) == 4
    assert sorted(answers) == [200, 409, 409, 409], answers
    assert len(fake_children) == 1, "more than one run was started"
    assert (A.GENERATED / "demo_round1_off_by_one").is_dir(), \
        "the refused clicks deleted the running job's files"


def test_the_app_is_not_busy_again_once_a_run_is_over(client, sandbox,
                                                      fake_children):
    client.post("/api/run", json={"demo": "round1_off_by_one"})
    assert client.get("/api/state").json()["busy"] is True

    for child in fake_children:
        child.release()
    assert wait_until_free()
    assert client.get("/api/state").json()["busy"] is False


def test_a_run_that_outstays_the_timeout_is_stopped_and_reported(monkeypatch):
    monkeypatch.setattr(A.config, "APP_RUN_TIMEOUT_SECONDS", 0)
    child = FakeChild(block=99)
    monkeypatch.setattr(A.subprocess, "Popen", lambda *a, **k: child)

    try:
        job = A.RUNNER.start("demo_slow", "saved", None, None,
                             PROJECT / "job.json")
        limit = time.time() + 5
        seen = None
        while time.time() < limit and seen is None:
            try:
                event = job.events.get(timeout=0.1)
            except Exception:
                continue
            if event is None:
                break
            if event.get("type") == "stopped":
                seen = event
    finally:
        child.release()

    assert seen is not None, "no stopped event arrived"
    assert "longer than 5 minutes" in seen["message"]
    assert "says nothing about the code" in seen["message"]
    assert wait_until_free()


# ---------------------------------------------------------------------------
# Cleaning up after itself
# ---------------------------------------------------------------------------

def test_clean_up_takes_away_this_runs_files_and_nothing_else(tmp_path,
                                                              monkeypatch):
    monkeypatch.setattr(A, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(A, "SCRATCH", tmp_path / "scratch")
    reports = tmp_path / "reports"
    reports.mkdir()

    mine = reports / "demo_this_run.json"
    mine.write_text("{}", encoding="utf-8")
    mine_md = reports / "demo_this_run.md"
    mine_md.write_text("#", encoding="utf-8")
    theirs = reports / "round1_off_by_one.json"
    theirs.write_text("{}", encoding="utf-8")
    other_demo = reports / "demo_somebody_elses.json"
    other_demo.write_text("{}", encoding="utf-8")

    scratch = tmp_path / "scratch" / "demo_run_abc"
    scratch.mkdir(parents=True)
    (scratch / "before.py").write_text("x = 1\n", encoding="utf-8")
    kept = tmp_path / "scratch" / "not_ours"
    kept.mkdir(parents=True)

    A.clean_up("demo_this_run", None, scratch)

    assert not mine.exists()
    assert not mine_md.exists()
    assert not scratch.exists()
    # not_ours is still sitting in there, so the parent has to stay. Only an
    # empty one is taken away.
    assert scratch.parent.is_dir()
    assert theirs.is_file()
    assert other_demo.is_file(), "another run's report was deleted"
    assert kept.is_dir(), "a folder the app did not make was deleted"


def test_the_scratch_parent_goes_when_this_run_emptied_it(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(A, "SCRATCH", tmp_path / "scratch")
    scratch = tmp_path / "scratch" / "demo_run_abc"
    scratch.mkdir(parents=True)
    (scratch / "before.py").write_text("x = 1\n", encoding="utf-8")

    A.clean_up("demo_abc", None, scratch)

    assert not scratch.exists()
    assert not (tmp_path / "scratch").exists(), "an empty folder was left behind"


def test_clean_up_will_not_delete_a_report_without_the_demo_prefix(tmp_path,
                                                                  monkeypatch):
    monkeypatch.setattr(A, "REPORTS", tmp_path)
    keep = tmp_path / "round1_off_by_one.json"
    keep.write_text("{}", encoding="utf-8")

    A.clean_up("round1_off_by_one", None, None)

    assert keep.is_file(), "a report without the demo prefix was deleted"


def test_clean_up_will_not_delete_a_folder_the_app_did_not_make(tmp_path):
    folder = tmp_path / "demo_someone_elses"
    folder.mkdir()
    keep = folder / "test_precious.py"
    keep.write_text("# mine\n", encoding="utf-8")

    A.clean_up("demo_someone_elses", folder, None)

    assert keep.is_file(), "a saved test file the app did not make was deleted"


def test_the_app_refuses_to_overwrite_a_folder_it_did_not_make(client,
                                                                tmp_path,
                                                                monkeypatch):
    monkeypatch.setattr(A, "GENERATED", tmp_path / "generated")
    squatters = tmp_path / "generated" / "demo_round1_off_by_one"
    squatters.mkdir(parents=True)
    precious = squatters / "test_get_recent_scores.py"
    precious.write_text("# written by hand, not by the app\n", encoding="utf-8")

    answer = client.post("/api/run", json={"demo": "round1_off_by_one"})

    assert answer.status_code == 409
    assert "not made by this app" in answer.json()["detail"]
    assert precious.read_text(encoding="utf-8") == \
        "# written by hand, not by the app\n"


def test_the_app_may_replace_its_own_leftovers(client, sandbox, monkeypatch):
    child = FakeChild()
    monkeypatch.setattr(A.subprocess, "Popen", lambda *a, **k: child)

    leftovers = sandbox / "generated" / "demo_round1_off_by_one"
    leftovers.mkdir(parents=True)
    (leftovers / A.MARKER).write_text("Made by the PRSentinel demo app.\n",
                                      encoding="utf-8")
    (leftovers / "test_get_recent_scores.py").write_text("# last time\n",
                                                         encoding="utf-8")

    try:
        answer = client.post("/api/run", json={"demo": "round1_off_by_one"})
        assert answer.status_code == 200, answer.text
        copied = leftovers / "test_get_recent_scores.py"
        assert "last time" not in copied.read_text(encoding="utf-8")
    finally:
        child.release()
        assert wait_until_free()


# ---------------------------------------------------------------------------
# Pasted code
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body, expected", [
    ({"before": "", "after": "x = 1"}, "There is no before code"),
    ({"before": "x = 1", "after": "   "}, "There is no after code"),
    ({"before": "def (", "after": "x = 1"}, "not valid Python"),
    ({"before": "x = 1", "after": "x = 1"}, "the same"),
])
def test_pasted_code_needs_two_halves_that_are_python(body, expected):
    assert expected in A.read_pasted(body)[2]


def test_pasted_code_too_big_is_refused_in_plain_words(monkeypatch):
    monkeypatch.setattr(A.config, "APP_MAX_PASTED_BYTES", 20)
    said = A.read_pasted({"before": "x = 1\n" * 50, "after": "y = 2\n" * 50})[2]
    assert "more than this app will hold" in said
    assert "KB" in said


def test_pasted_code_has_no_saved_tests_and_the_app_says_so(client):
    answer = client.post("/api/run", json={"before": "def f():\n    return 1\n",
                                           "after": "def f():\n    return 2\n"})
    assert answer.status_code == 400
    said = answer.json()["detail"]
    assert "none for pasted code" in said
    assert "Generate fresh tests" in said


# ---------------------------------------------------------------------------
# The settings the demo depends on
# ---------------------------------------------------------------------------

def test_the_run_timeout_is_five_minutes():
    assert config.APP_RUN_TIMEOUT_SECONDS == 300


def test_the_pasted_size_cap_is_a_plain_number():
    assert config.APP_MAX_PASTED_BYTES == 60000


def test_the_two_new_settings_can_be_changed_without_editing_code(tmp_path):
    """Run in a child so the change cannot leak into the rest of the suite."""
    script = tmp_path / "ask.py"
    script.write_text(
        "import sys\n"
        "sys.path.insert(0, r'" + str(PROJECT / "src") + "')\n"
        "from prsentinel import config\n"
        "print(config.APP_RUN_TIMEOUT_SECONDS, config.APP_MAX_PASTED_BYTES)\n",
        encoding="utf-8")

    import os

    env = dict(os.environ)
    env["PRSENTINEL_APP_RUN_TIMEOUT_SECONDS"] = "42"
    env["PRSENTINEL_APP_MAX_PASTED_BYTES"] = "1234"

    import subprocess
    said = subprocess.run([sys.executable, str(script)], env=env, cwd=tmp_path,
                          capture_output=True, text=True, timeout=120)
    assert said.stdout.split() == ["42", "1234"], said.stderr


def test_the_two_new_settings_are_documented_where_they_live():
    text = (PROJECT / "src" / "prsentinel" / "config.py").read_text(
        encoding="utf-8")
    assert "# The demo web app" in text
    assert "APP_RUN_TIMEOUT_SECONDS = _int_from_env" in text
    assert "APP_MAX_PASTED_BYTES = _int_from_env" in text
    assert "a thread cannot be killed" in text


# ---------------------------------------------------------------------------
# The app calls the pipeline, it does not reimplement it
# ---------------------------------------------------------------------------

def test_the_app_calls_the_pipeline_instead_of_reimplementing_it():
    source = (PROJECT / "src" / "prsentinel" / "app.py").read_text(
        encoding="utf-8")
    assert "pl.run_pipeline(" in source
    for banned in ("def rule_classify", "def judge_one_test",
                   "def run_all_three", "def evaluate_tests",
                   "PROMPT_TEMPLATE", "RERUN_SECTION", "def rule_"):
        assert banned not in source, banned


def test_the_safety_sentence_is_the_one_the_comment_uses():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "make_pr_comment_under_test", PROJECT / "scripts" / "make_pr_comment.py")
    other = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(other)
    assert other.FIXED_SENTENCE == A.SAFETY_SENTENCE
    # The page does not carry the sentence as its own text. It is served, so
    # there is one place to change it and the comment cannot drift away from it.
    assert 'id="safety"' in A.page_text()
    assert client_says_the_sentence()


def client_says_the_sentence():
    with TestClient(A.app) as made:
        said = made.get("/api/demos").json()["safety_sentence"]
    return said == A.SAFETY_SENTENCE


def test_the_app_binds_to_the_loopback_address_only():
    source = (PROJECT / "src" / "prsentinel" / "app.py").read_text(
        encoding="utf-8")
    assert 'host="127.0.0.1"' in source
    assert "0.0.0.0" not in source
    assert "python -m prsentinel.app" in source
    assert 'raise SystemExit(main())' in source


def test_the_child_flag_does_not_swallow_the_job_file():
    """argparse once ate the job file, and the child started with nothing.

    An option that takes an optional value of its own swallows the word after
    it, so the child ran, found no job file and exited without saying why on
    the stream the page was watching. It only showed up as a run that produced
    no result, which is the least helpful symptom there is.
    """
    args = A.parse_args(["--run-once", r"C:\somewhere\job.json"])
    assert args.run_once is True
    assert args.job_file == r"C:\somewhere\job.json"

    plain = A.parse_args([])
    assert plain.run_once is False
    assert plain.job_file is None
    assert plain.port == 8000

    assert A.parse_args(["--port", "9001"]).port == 9001


def test_a_child_with_no_job_file_says_so_and_stops(capsys):
    assert A.main(["--run-once"]) == 2
    assert "needs a job file" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# End to end: a real saved run through a real child process
# ---------------------------------------------------------------------------

@pytest.fixture
def tiny_demo(tmp_path, monkeypatch):
    """A one-line change, so the end-to-end test is not slow."""
    demos = tmp_path / "demos"
    folder = demos / "tiny"
    folder.mkdir(parents=True)
    (folder / "before.py").write_text(
        'def add(a, b):\n    """Add two numbers."""\n    return a + b\n',
        encoding="utf-8")
    (folder / "after.py").write_text(
        'def add(a, b):\n    """Add two numbers."""\n    return a - b\n',
        encoding="utf-8")
    (folder / "test_add.py").write_text(
        "from target import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        encoding="utf-8")
    (demos / "README.md").write_text(
        "| case | note |\n| --- | --- |\n| `tiny` | One line, for the tests. |\n",
        encoding="utf-8")

    monkeypatch.setattr(A, "DEMOS", demos)
    monkeypatch.setattr(A, "SCRATCH", tmp_path / "scratch")
    monkeypatch.setattr(A.config, "APP_RUN_TIMEOUT_SECONDS", 120)
    return folder


def test_a_saved_run_works_end_to_end(client, tiny_demo):
    """Press the button for real: a child process, a stream, a report."""
    started = client.post("/api/run", json={"demo": "tiny",
                                            "mode": "saved",
                                            "mutation": False})
    assert started.status_code == 200, started.text

    content_type, events = read_stream(client, started.json()["run_id"])

    assert content_type.startswith("text/event-stream")
    kinds = [event["type"] for event in events]
    assert kinds[-1] == "done", events[-3:]
    assert "progress" in kinds, "no progress arrived"

    results = [event for event in events if event["type"] == "result"]
    assert len(results) == 1, [event["type"] for event in events]

    report = results[0]["report"]
    assert report["app_mode"] == "saved"
    assert report["tests_source"] == "reused from generated_tests"
    assert report["name"] == "demo_tiny"
    assert report["functions"][0]["function"] == "add"
    assert report["functions"][0]["judgements"][0]["verdict"] == "REAL_BUG"
    assert report["gemini_answers"] == 0

    # The page is told file names, never the scratch path they came from.
    assert report["before"] == "before.py"
    assert "demo_scratch" not in json.dumps(report)


def test_the_end_to_end_run_leaves_nothing_behind(client, tiny_demo):
    """The moment the page is told the run is done, the files must already be
    gone.

    Tidying up used to happen in the thread watching the clock, while a
    different thread announced the end as soon as the child's output ran out.
    Those two are not ordered against each other, so the page could be told done
    and then look for files that had not been deleted yet. This assertion is
    where that showed up, and it is the reason the tidying happens where it
    does now.
    """
    started = client.post("/api/run", json={"demo": "tiny",
                                            "mutation": False})
    content_type, events = read_stream(client, started.json()["run_id"])

    assert [event["type"] for event in events][-1] == "done"
    assert content_type.startswith("text/event-stream")

    assert not A.SCRATCH.exists()
    assert not (A.GENERATED / "demo_tiny").exists()
    assert not (A.REPORTS / "demo_tiny.json").exists()
    assert not (A.REPORTS / "demo_tiny.md").exists()


def test_the_end_to_end_run_leaves_the_real_reports_alone(client, tiny_demo):
    kept = A.REPORTS / "round1_off_by_one.json"
    assert kept.is_file(), "the committed report should be there to begin with"
    before = kept.stat().st_size

    started = client.post("/api/run", json={"demo": "tiny",
                                            "mutation": False})
    read_stream(client, started.json()["run_id"])

    assert kept.is_file()
    assert kept.stat().st_size == before


def test_the_run_is_cleaned_up_even_if_nobody_is_listening(client, tiny_demo):
    """Closing the tab mid-run must not leave files behind.

    Tidying up used to hang off the event stream, so closing the browser
    halfway through a run left the copied test and both report files on disk
    for good. Nothing reads those files, so there was never a reason to wait.
    """
    started = client.post("/api/run", json={"demo": "tiny",
                                            "mutation": False})
    assert started.status_code == 200

    assert wait_until_free(180), "the run never finished"
    assert not A.SCRATCH.exists()
    assert not (A.GENERATED / "demo_tiny").exists()
    assert not (A.REPORTS / "demo_tiny.json").exists()
    assert not (A.REPORTS / "demo_tiny.md").exists()


def test_a_stream_for_a_run_that_is_gone_says_so(client):
    answer = client.get("/api/stream?run_id=nothing-here")
    assert answer.status_code == 404
    assert "already finished" in answer.json()["detail"]


def test_the_demo_list_tells_the_page_what_it_needs(client):
    said = client.get("/api/demos").json()
    assert said["timeout_seconds"] == 300
    assert said["max_pasted_bytes"] == 60000
    assert said["safety_sentence"] == A.SAFETY_SENTENCE
    assert len(said["demos"]) == 3
    assert said["model"] == config.GROQ_MODEL