"""Tests for the two GitHub Actions workflows and the comment they leave.

Two separate things are guarded here, and both guard against mistakes that are
invisible until they matter.

1. What the workflows are allowed to say and do. A workflow runs on a Linux
   machine, holding this repository's secrets, against code somebody wrote
   minutes ago. Two mistakes there are quiet. One is naming the evaluation data,
   which would let a run be pointed at the real cases and turn an evaluation
   into a tuning result. The other is putting the model key somewhere wider than
   the one step that needs it. Both are checked by reading the two workflow files
   as plain text, so a mention inside a comment counts as a mention.

2. What the comment says. scripts/make_pr_comment.py runs on every pull request
   and puts words in front of the person who opened it. The fixed sentence at
   the top is the difference between a hint and a claim, so it is held character
   for character, and every branch of the comment is checked against a report
   built by hand rather than by a model.

Nothing here calls a model, runs pytest on generated code, or reaches the
network. Every report in this file was made up.
"""

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
SRC = PROJECT / "src" / "prsentinel"
WORKFLOWS = PROJECT / ".github" / "workflows"
PR_WORKFLOW = WORKFLOWS / "prsentinel.yml"
SUITE_WORKFLOW = WORKFLOWS / "tests.yml"
COMMENT_SCRIPT = PROJECT / "scripts" / "make_pr_comment.py"

BOTH_WORKFLOWS = (PR_WORKFLOW, SUITE_WORKFLOW)

# The sentence the comment must always open with. Copied out of the script rather
# than imported, so that if the script's own constant is edited to sound more
# confident, the test still holds the older, safer wording and fails.
SAFETY_SENTENCE = ("Tests are AI-generated. "
                   "A catching test is a hint, not proof.")

# What must never appear in a workflow or in the comment script. These are the
# evaluation inputs. A workflow that can reach them can be aimed at them, and
# every number that came out of that run stops being evidence.
FORBIDDEN_IN_CI = (
    "real_cases",
    "baselines",
    "PROMPT_LOG",
    "heldback_runs",
    "expected.json",
)


# ---------------------------------------------------------------------------
# Reading things
# ---------------------------------------------------------------------------

def workflow_texts():
    """Both workflow files as plain text, so failures come out in order."""
    return sorted(WORKFLOWS.glob("*.yml"))


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def code_lines(text: str) -> list:
    """The lines of a workflow that are not YAML comments.

    Comments in these files explain why the workflow does not do something, and
    saying "no --repair here" in a comment is exactly the documentation we want.
    Dropping whole comment lines lets those words stay while still catching a
    flag that is really passed, a key that is really read, or a trigger that is
    really set. Only whole lines are dropped: a comment at the end of a line with
    a command on it is still read, so this cannot be used to smuggle a setting
    past a guard.
    """
    return [line for line in text.splitlines()
            if not line.lstrip().startswith("#")]


def code_text(text: str) -> str:
    return "\n".join(code_lines(text))


def load_comment_script():
    """Import scripts/make_pr_comment.py by path, the same way the other tests
    load the other scripts."""
    spec = importlib.util.spec_from_file_location("make_pr_comment",
                                                  COMMENT_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_function(name="do_thing", catches=2, wrong=0, no_signal=1, odd=0,
                  real_bugs=0):
    """One changed function with made-up counts."""
    return {
        "function": name,
        "change_type": "modified",
        "test_file": "test_do_thing.py",
        "from_folder": "work",
        "counts": {
            "CATCHES_CHANGE": catches,
            "TEST_WRONG_ON_BEFORE": wrong,
            "NO_SIGNAL": no_signal,
            "ODD": odd,
        },
        "judgements": [{"verdict": "REAL_BUG"} for _ in range(real_bugs)],
        "needs_a_look": [],
    }


def fake_report(name="prsentinel_1", functions=None, mutation=None,
                fallback=False, gemini_answers=0, generation_failed=False):
    """One whole report, made up. Defaults describe a run that found something."""
    if functions is None:
        functions = [fake_function()]
    if mutation is None:
        mutation = [{"function": "do_thing", "found": 3, "killed": 3,
                     "score": 1.0}]

    return {
        "name": name,
        "before": "work/1/before.py",
        "after": "work/1/after.py",
        "fallback": fallback,
        "gemini_answers": gemini_answers,
        "generation_failed": generation_failed,
        "tests_source": "generated",
        "mutation": mutation,
        "repair": False,
        "repairs": [],
        "skipped": [],
        "summary": {},
        "functions": functions,
    }


def build(**kwargs):
    """The comment a run would leave, from a made-up report."""
    module = load_comment_script()
    report = fake_report(**kwargs)
    facts = {"repo": "owner/name", "pr": "12", "base_sha": "aaa",
             "head_sha": "bbb", "skipped": "", "no_result": ""}
    return module.build_comment([("some_module.py", report)], facts)


def build_empty(facts=None):
    module = load_comment_script()
    return module.build_comment([], facts or {"repo": "owner/name", "pr": "12",
                                              "base_sha": "aaa",
                                              "head_sha": "bbb",
                                              "skipped": "", "no_result": ""})


# ---------------------------------------------------------------------------
# The workflows exist at all
# ---------------------------------------------------------------------------

def test_there_are_exactly_two_workflow_files():
    """If a third appears, this file stops being a list of what is allowed to run
    against a pull request, which is the only reason it is allowed to run at all.
    """
    names = [path.name for path in workflow_texts()]
    assert names == ["prsentinel.yml", "tests.yml"], \
        f"workflow files are {names}. A new one needs to be read and approved " \
        f"here before it runs on anybody's pull request."


@pytest.mark.parametrize("path", BOTH_WORKFLOWS)
def test_the_workflow_file_exists_and_is_not_empty(path):
    assert path.is_file(), f"{path} is missing"
    assert read(path).strip(), f"{path} is empty"


@pytest.mark.parametrize("path", BOTH_WORKFLOWS)
def test_the_workflow_file_is_plain_ascii_and_ends_with_a_newline(path):
    """YAML is easier to get wrong than it looks, and a stray non-ASCII character
    or a missing final newline is the kind of thing GitHub rejects with an error
    message nobody reads."""
    text = read(path)
    text.encode("ascii")  # raises if not
    assert text.endswith("\n"), f"{path} does not end with a newline"


@pytest.mark.parametrize("path", BOTH_WORKFLOWS)
def test_the_workflow_file_has_no_tabs(path):
    """YAML forbids tabs for indentation and the failure is a parser error on a
    file most people will not open."""
    for number, line in enumerate(read(path).splitlines(), start=1):
        assert "\t" not in line, f"{path} line {number} has a tab in it"


@pytest.mark.parametrize("path", BOTH_WORKFLOWS)
def test_indentation_in_the_workflow_is_a_whole_number_of_spaces(path):
    """Two spaces per level. Catches the half-indented step that otherwise looks
    plausible enough to be committed."""
    for number, line in enumerate(read(path).splitlines(), start=1):
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        assert indent % 2 == 0, \
            f"{path} line {number} is indented by {indent} spaces"


def test_action_versions_are_pinned():
    """An action with no version follows whatever its author pushes next, which
    means a run of this project could change without anybody changing it. A major
    version tag is the most this repository can pin to offline, because a commit
    hash cannot be looked up from here."""
    used = re.findall(r"uses:\s*([^\s]+)", read(PR_WORKFLOW) +
                      read(SUITE_WORKFLOW))

    assert used, "no actions are used, so nothing was found to check"

    for action in sorted(set(used)):
        assert "@" in action, f"{action} names no version"

        ref = action.split("@", 1)[1]
        floating = ("main", "master", "HEAD", "latest")
        assert ref not in floating, \
            f"{action} follows a branch. Whoever owns that action can change " \
            f"what runs here at any time."
        assert re.fullmatch(r"v\d+(\.\d+)*", ref) or \
            re.fullmatch(r"[0-9a-f]{40}", ref), \
            f"{action} is pinned to {ref!r}, which is neither a version nor a " \
            f"commit hash"


# ---------------------------------------------------------------------------
# The shell inside the workflows
# ---------------------------------------------------------------------------

def shell_blocks(text: str) -> list:
    """The body of every "run: |" block in a workflow file.

    A block starts at the run: line and runs until the first line that is not
    blank and is not indented further than the run: line itself. That is what
    makes it a block, so no YAML parser is needed to find one.
    """
    lines = text.splitlines()
    blocks = []

    for number, line in enumerate(lines):
        if line.strip() != "run: |":
            continue

        indent = len(line) - len(line.lstrip(" "))
        body = []
        for follower in lines[number + 1:]:
            if not follower.strip():
                body.append("")
                continue
            if len(follower) - len(follower.lstrip(" ")) <= indent:
                break
            body.append(follower)

        blocks.append((number + 1, "\n".join(body).strip()))

    return blocks


def find_bash():
    """Where bash might be, so the check below can be skipped instead of failing
    on a machine that has none."""
    import shutil

    found = shutil.which("bash")
    if found:
        return found

    for candidate in (r"C:\Program Files\Git\bin\bash.exe",
                      r"C:\Program Files\Git\usr\bin\bash.exe"):
        if Path(candidate).is_file():
            return candidate
    return None


@pytest.mark.parametrize("path", BOTH_WORKFLOWS)
def test_the_shell_in_the_workflow_is_valid(path):
    """The one thing that cannot be checked by reading.

    A shell mistake in a workflow file is invisible until the job runs on GitHub,
    which is the one machine where a broken job also costs a real model call and
    a real runner. bash -n parses without running anything. Skipped where there
    is no bash, which is every machine that has never had this problem anyway;
    the Linux runner running tests.yml always has one."""
    bash = find_bash()
    if not bash:
        pytest.skip("no bash on this machine")

    import subprocess

    blocks = shell_blocks(read(path))
    assert blocks, f"{path.name} has no run: block to check"

    for number, body in blocks:
        if not body:
            continue

        result = subprocess.run([bash, "-n"], input=body, capture_output=True,
                                text=True, timeout=60)
        assert result.returncode == 0, \
            f"{path.name} has a shell mistake in the run: block at line " \
            f"{number}:\n{result.stderr}\n---\n{body}"


def test_the_workflow_has_shell_to_check():
    """So the test above cannot pass for the wrong reason."""
    for path in BOTH_WORKFLOWS:
        assert shell_blocks(read(path)), \
            f"{path.name} has no run: block, so the shell check found nothing"


# ---------------------------------------------------------------------------
# The workflows may not reach the evaluation data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path", BOTH_WORKFLOWS)
def test_no_workflow_names_the_evaluation_data(path):
    """The important one. Read as plain text, so a mention in a comment counts.
    """
    text = read(path)
    for name in FORBIDDEN_IN_CI:
        assert name not in text, \
            f"{path} names {name}. A workflow that can reach the evaluation data " \
            f"can be aimed at it, and then every number from that run stops " \
            f"being an evaluation."


def test_the_comment_script_does_not_name_the_evaluation_data():
    """It runs on every pull request, so it gets the same rule. It is not on the
    allowed list in tests/test_real_cases.py, and it should not need to be.
    """
    text = read(COMMENT_SCRIPT)
    for name in FORBIDDEN_IN_CI:
        assert name not in text, f"make_pr_comment.py names {name}"


def test_the_comment_script_is_not_on_the_evaluation_allow_list():
    """If somebody adds it to ALLOWED_ELSEWHERE to silence the guard above, that
    is a decision to notice, not one to make quietly in another file."""
    from tests.test_real_cases import ALLOWED_ELSEWHERE  # noqa: F401
    allow = read(PROJECT / "tests" / "test_real_cases.py")
    assert "scripts/make_pr_comment.py" not in allow, \
        "make_pr_comment.py was added to ALLOWED_ELSEWHERE. It does not need to " \
        "name the evaluation data, so the exception should be removed instead."


def test_the_package_does_not_import_the_comment_script():
    """The comment is built outside the package. If src/ started importing it,
    the pipeline would be carrying report formatting into every run."""
    for path in sorted(SRC.glob("*.py")):
        text = read(path)
        assert "make_pr_comment" not in text, \
            f"{path.name} names make_pr_comment"


# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

# What a leaked key actually looks like. Checking for the shape catches a key
# pasted straight into a workflow file, which is the mistake that cannot be
# undone by editing the file afterwards.
KEY_SHAPES = (r"gsk_[A-Za-z0-9]{8,}", r"AIza[A-Za-z0-9_\-]{8,}")


@pytest.mark.parametrize("path", BOTH_WORKFLOWS)
def test_no_workflow_contains_something_shaped_like_a_key(path):
    """secrets.GROQ_API_KEY is a name, not a value, and is fine. A run of real
    key characters is not."""
    text = read(path)
    for shape in KEY_SHAPES:
        assert not re.search(shape, text), \
            f"{path} contains something that looks like an API key. Remove it " \
            f"from the history too, not just from this file."


def test_the_suite_workflow_names_no_provider_key_at_all():
    """It runs on every fork, so it must have nothing to leak."""
    text = code_text(read(SUITE_WORKFLOW))
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "ANTHROPIC_API_KEY", "secrets."):
        assert name not in text, \
            f"tests.yml uses {name}. That workflow is meant to need no secrets " \
            f"at all."


def test_the_key_is_referenced_on_exactly_one_line_of_one_workflow():
    """One line means one step. If this ever needs two, the answer is to work
    out why, not to widen the test."""
    users = [path for path in BOTH_WORKFLOWS
             if "GROQ_API_KEY" in code_text(read(path))]
    assert users == [PR_WORKFLOW], \
        f"GROQ_API_KEY appears in {[p.name for p in users]}, expected only " \
        f"in prsentinel.yml"

    lines = [line for line in code_lines(read(PR_WORKFLOW))
             if "GROQ_API_KEY" in line]
    assert len(lines) == 1, \
        f"GROQ_API_KEY is on {len(lines)} lines: {lines}"
    assert "secrets.GROQ_API_KEY" in lines[0], \
        f"the key must be read from secrets, but the line is {lines[0]!r}"


def test_the_one_step_holding_the_key_is_the_pipeline_step():
    """The key goes where the model is called and nowhere else, so that no other
    step and no code running in any other step can reach it."""
    pr_text = read(PR_WORKFLOW)
    holder = "GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}"

    lines = pr_text.splitlines()
    index = next(i for i, line in enumerate(lines) if holder in line)

    # Walk back to the step's own name, which sits a few lines above the env.
    name = next(lines[i].strip() for i in range(index, -1, -1)
                if lines[i].strip().startswith("- name:"))
    assert "prsentinel.pipeline" in pr_text, "the pipeline is not run at all"
    assert "Run PRSentinel" in name, \
        f"the key is on the step called {name!r}. It belongs on the step that " \
        f"calls the model."


def test_the_key_is_never_written_to_a_file_or_echoed():
    """A key in a build log is a key in everybody's build logs."""
    pr_text = read(PR_WORKFLOW)
    for line in pr_text.splitlines():
        if "secrets." not in line:
            continue
        stripped = line.strip()
        assert stripped.endswith("}}") or stripped.endswith("}}"), \
            f"this line does more than pass a secret on: {stripped!r}"
        for danger in ("echo ", ">>", "tee ", "cat "):
            assert danger not in stripped, \
                f"a secret is sent to {danger!r} here: {stripped!r}"


def test_the_workflow_asks_for_no_more_permission_than_it_needs():
    """contents:read to get the code, pull-requests:write to leave one comment.
    Nothing else, and no write-all."""
    text = read(PR_WORKFLOW)
    assert re.search(r"^permissions:\s*$", text, re.M), "no permissions block"
    block = text.split("permissions:", 1)[1].split("\n\n", 1)[0]
    assert "contents: read" in block, block
    assert "pull-requests: write" in block, block
    for stronger in ("write-all", "contents: write", "packages: write",
                     "id-token: write", "actions: write"):
        assert stronger not in block, f"{stronger} in the permissions block"

    suite = read(SUITE_WORKFLOW)
    suite_block = suite.split("permissions:", 1)[1].split("\n\n", 1)[0]
    assert "contents: read" in suite_block, suite_block
    assert "write" not in suite_block, \
        f"tests.yml needs no write permission at all, but has {suite_block!r}"


# ---------------------------------------------------------------------------
# What the pipeline step does
# ---------------------------------------------------------------------------

def test_fallback_is_switched_off_in_the_workflow():
    """So every number in the comment came from one model."""
    assert "--no-fallback" in code_text(read(PR_WORKFLOW))


def test_no_second_provider_is_configured():
    """--no-fallback should be enough, but if somebody ever adds the key the
    backup becomes reachable again and the comment would be a mixture."""
    text = code_text(read(PR_WORKFLOW))
    for name in ("GEMINI", "gemini", "google-genai", "GOOGLE_API_KEY"):
        assert name not in text, f"prsentinel.yml uses {name}"


def test_repair_is_off_and_nothing_is_edited():
    """This workflow reads a pull request. It does not write to it."""
    text = code_text(read(PR_WORKFLOW))
    assert "--repair" not in text, "the workflow repairs tests"
    assert "--reuse-tests" not in text, \
        "--reuse-tests would read the frozen test folders, which the guard " \
        "above stops it naming anyway"


def test_mutation_is_turned_on():
    """It is the number that says whether the new tests were any use, and it was
    in scope for this run."""
    assert "--mutation" in code_text(read(PR_WORKFLOW))


def test_before_is_the_base_commit_and_after_is_the_head_commit():
    """That is the direction a real pull request reads in, and the direction the
    whole evaluation was measured in. Getting it backwards would report every
    test as failing on the old code."""
    text = read(PR_WORKFLOW)
    assert re.search(r'git show "\$BASE_SHA:\$path"\s*>\s*"work/\$index/before\.py"',
                     text), "before.py is not taken from the base commit"
    assert re.search(r'git show "\$HEAD_SHA:\$path"\s*>\s*"work/\$index/after\.py"',
                     text), "after.py is not taken from the head commit"


def test_only_changed_python_files_outside_tests_are_scored():
    """The three rules, spelled out in the shell so the workflow needs no extra
    script to test. Deleted files are left out because there is nothing left to
    test; tests/ is left out because this workflow writes new tests and has no
    business reading someone else's."""
    text = code_text(read(PR_WORKFLOW))
    assert "'*.py'" in text, "the file list is not restricted to .py"
    assert "--diff-filter=d" in text, "deleted files are not left out"
    assert "grep -v '^tests/'" in text, "files under tests/ are not left out"


def test_two_commits_that_cannot_be_compared_fail_the_job():
    """The manual run takes two SHAs from whoever typed them. A wrong one has to
    be loud. If it were quiet it would end up as a comment saying no changed file
    was found, which is a different and completely untrue statement."""
    text = code_text(read(PR_WORKFLOW))
    assert "git_code=$?" in text, "git's exit code is thrown away"
    assert '[ "$git_code" -ne 0 ]' in text, "a failed comparison is not noticed"
    assert re.search(r"exit \"\$git_code\"", text), \
        "a failed comparison does not fail the job"


def test_the_file_limit_is_the_same_number_in_the_shell_and_in_the_note():
    """Both halves, and they have to agree. Checking for the text "head -5" would
    also pass on head -50, so the number is read out of each instead."""
    text = code_text(read(PR_WORKFLOW))

    shell = re.search(r"head -(\d+) all_files\.txt", text)
    assert shell, "the file limit is not in the shell"
    assert shell.group(1) == "5", \
        f"the shell scores at most {shell.group(1)} files per pull request"

    note = re.search(r"at most (\d+) per pull request", text)
    assert note, "the comment never says what the limit is"
    assert note.group(1) == shell.group(1), \
        "the note says one number and the shell uses another. A reader who has " \
        "to work out which one is true is right to distrust the rest."


def test_a_run_with_no_catching_test_does_not_fail_the_job():
    """Only the pipeline breaking fails it. A file nobody caught is a result, and
    calling it a failure would make the check untrustworthy enough to ignore."""
    text = read(PR_WORKFLOW)
    assert 'if [ "$code" != "0" ]; then' in text
    assert re.search(r"exit \"\$code\"", text), \
        "the workflow never fails the job when the pipeline breaks"


def test_the_daily_limit_is_neutral_and_says_no_result():
    """Six is the pipeline's code for the allowance running out. It is not a bug
    in the pull request, so it must not turn the job red, and the comment must
    not claim the code was fine."""
    text = read(PR_WORKFLOW)
    assert '[ "$code" = "6" ]' in text, "the daily limit is not noticed"
    assert "EXIT" not in text, "no note of where the number 6 comes from"
    assert "the pipeline's code for the allowance running out" in text, \
        "nothing says what 6 means, so the next reader has to guess"


def test_a_stopped_run_reaches_the_comment_as_no_result():
    """The workflow has to carry the reason across, not just notice it. Without
    this wiring a stopped run would post the scores of the files it finished
    before it ran out, under a heading that looks like a complete answer."""
    text = read(PR_WORKFLOW)
    assert 'args+=(--no-result "$STOPPED")' in text, \
        "the reason the run stopped is not passed to the comment script"
    assert 'echo "stopped=$STOPPED" >> "$GITHUB_OUTPUT"' in text, \
        "the run step never tells the build step why it stopped"


def test_the_job_has_a_timeout():
    """A run that hangs costs the shared allowance and a runner."""
    text = read(PR_WORKFLOW)
    assert "timeout-minutes: 20" in text
    assert "timeout-minutes" in read(SUITE_WORKFLOW)


# ---------------------------------------------------------------------------
# The triggers
# ---------------------------------------------------------------------------

def test_it_does_not_use_pull_request_target():
    """The important one about the trigger.

    pull_request_target runs in this repository with this repository's secrets
    and checks out the pull request's code. That is the combination the security
    note in the README is about, so the trigger must stay away from it. The
    workflow explains in a comment why, and saying so there is the point of the
    comment, so this looks for the setting and not the word."""
    for path in BOTH_WORKFLOWS:
        assert not re.search(r"^\s*pull_request_target\s*:", read(path),
                             re.M), \
            f"{path.name} triggers on pull_request_target"


def test_a_pull_request_from_a_fork_is_skipped_and_says_so():
    """GitHub does not hand a fork's workflow this repository's secrets, so a fork
    pull request cannot be scored. It is skipped rather than left silent."""
    text = read(PR_WORKFLOW)
    assert "head.repo.full_name != github.repository" in text, \
        "no fork skip condition"
    assert "head.repo.full_name == github.repository" in text, \
        "the main job does not say it needs a same-repository pull request"
    assert "comes from a fork" in text, \
        "a fork pull request is skipped without saying so"


def test_one_run_per_pull_request_and_a_new_push_cancels_the_old_one():
    text = read(PR_WORKFLOW)
    assert re.search(r"^concurrency:\s*$", text, re.M), "no concurrency block"
    assert "pull_request.number" in text.split("concurrency:", 1)[1], \
        "the concurrency group is not per pull request"
    assert "cancel-in-progress: true" in text


def test_a_manual_run_takes_two_commits():
    """So the workflow can be run by hand against any two commits, which is how
    it gets tried before anybody opens a pull request."""
    text = read(PR_WORKFLOW)
    assert "workflow_dispatch:" in text
    assert "before_sha:" in text
    assert "after_sha:" in text


def test_the_checkout_can_reach_both_commits():
    """A shallow clone does not have the base of a pull request, so git show would
    fail on exactly the commit the run is about."""
    assert "fetch-depth: 0" in read(PR_WORKFLOW)


def test_python_313_is_requested_in_both_workflows():
    for path in BOTH_WORKFLOWS:
        assert "python-version: '3.13'" in read(path), \
            f"{path.name} does not ask for Python 3.13"


# ---------------------------------------------------------------------------
# The comment
# ---------------------------------------------------------------------------

def test_the_safety_sentence_is_in_the_pull_request_workflow():
    """The fork note carries it too, so a reader meets it whichever way the run
    went. The suite workflow posts no comment, so it is not expected there."""
    assert SAFETY_SENTENCE in read(PR_WORKFLOW)


def test_the_safety_sentence_is_the_scripts_own_constant():
    module = load_comment_script()
    assert module.FIXED_SENTENCE == SAFETY_SENTENCE, \
        "the sentence in the script no longer matches the one this test holds"


def test_the_comment_always_opens_with_the_safety_sentence():
    """Not somewhere near the bottom, and not only when there is a result. The
    reader should not have to scroll to find out how much to trust this."""
    for text in (build(), build_empty(), build(functions=[]),
                 build(functions=[fake_function(catches=0)]),
                 load_comment_script().build_comment(
                     [], {"repo": "o/n", "pr": "1", "base_sha": "a",
                          "head_sha": "b", "skipped": "",
                          "no_result": "the allowance ran out"})):
        body = text.replace("**", "")
        assert SAFETY_SENTENCE in body, text[:400]
        assert text.index(SAFETY_SENTENCE) < text.index("CATCHES_CHANGE") \
            if "CATCHES_CHANGE" in text else True


def test_the_comment_carries_a_marker_so_it_can_be_updated_not_repeated():
    """Ten pushes to one pull request must not leave ten comments."""
    assert load_comment_script().MARKER in build()
    assert load_comment_script().MARKER in build_empty()


def test_the_comment_names_the_repository_the_commits_and_the_model():
    """A reader has to be able to tell what run this is about."""
    text = build()
    assert "owner/name" in text
    assert "aaa" in text and "bbb" in text
    from prsentinel import config
    assert config.GROQ_MODEL in text


def test_the_comment_shows_the_changed_file_not_the_report_name():
    text = build()
    assert "some_module.py" in text
    assert "prsentinel_1" not in text, \
        "the reader is shown the report's own name"


def test_the_comment_counts_tests_and_catching_ones():
    """2 catching, 1 with no signal, 0 of the other two, so 3 test items. A
    parametrized test with five cases counts as five, so this is not a count of
    files or of test functions."""
    text = build()
    assert "**3** tests" in text
    assert "2 catching the change" in text


def test_a_catching_test_says_how_well_the_tests_held_up():
    text = build()
    assert "100% (3 of 3 mutants killed)" in text


def test_an_undefined_mutation_score_is_not_shown_as_zero_percent():
    """Zero percent says the tests were useless. Undefined says there was no green
    starting point to measure from. Those are different facts."""
    text = build(mutation=[{"function": "do_thing", "found": 2, "killed": 0,
                            "score": None,
                            "reason": "the tests already fail on the un-mutated "
                                      "code, so there is no green starting point"}])
    assert "0% (0 of 2" not in text
    assert "not defined" in text
    assert "no green starting point" in text


def test_a_function_nothing_caught_says_so_plainly():
    text = build(functions=[fake_function(catches=0, wrong=2, odd=1)])
    assert "no test caught this change" in text
    assert "2 of them also fail on the old code" in text
    assert "the other way round" in text


def test_the_comment_does_not_call_anything_a_verified_bug():
    """The whole point of the sentence at the top is that this is a hint. A word
    like confirmed or verified anywhere in the comment would undo it.

    The sentence itself is taken out first, because it says not proof on purpose
    and that is the one place the word is allowed."""
    text = (build() + build(functions=[fake_function(real_bugs=3)])
            ).replace(SAFETY_SENTENCE, "")
    for word in ("confirmed", "verified", "proof", "proven", "guaranteed",
                 "definitely"):
        assert word not in text.lower(), \
            f"the comment says {word!r}. The tests are a hint, and the wording " \
            f"has to keep saying so."


def test_tests_judged_real_bugs_are_reported_as_judgements_not_verdicts():
    text = build(functions=[fake_function(real_bugs=3)])
    assert "3 of the catching tests were judged to point at a real bug" in text


# ---------------------------------------------------------------------------
# The comment when things went wrong
# ---------------------------------------------------------------------------

def test_a_stopped_run_says_there_is_no_result_and_does_not_pick_a_winner():
    """The hardest case to get right. Nothing was checked, so the comment must not
    read like the pull request passed."""
    module = load_comment_script()
    text = module.build_comment(
        [("some_module.py", fake_report())],
        {"repo": "owner/name", "pr": "12", "base_sha": "aaa",
         "head_sha": "bbb", "skipped": "",
         "no_result": "Groq's daily allowance ran out while scoring a.py, so "
                      "the run stopped and there is no result to report."})

    assert "### No result" in text
    assert "That is not a pass." in text
    assert "1 of 1 changed file" not in text, \
        "a stopped run reported a score for the part it finished"
    assert "100%" not in text, "a stopped run reported a mutation score"
    assert SAFETY_SENTENCE in text


def test_a_stopped_run_that_finished_nothing_still_gets_the_sentence():
    module = load_comment_script()
    text = module.build_comment([], {"repo": "o/n", "pr": "1", "base_sha": "a",
                                     "head_sha": "b", "skipped": "",
                                     "no_result": "nothing was scored"})
    assert SAFETY_SENTENCE in text
    assert "### No result" in text


def test_a_run_with_nothing_to_score_says_so_instead_of_a_zero():
    """A comment claiming 0 of 0 would read like a bad result for a good
    pull request."""
    text = build_empty()
    assert "Nothing was scored" in text
    assert "0 of 0" not in text
    assert SAFETY_SENTENCE in text


def test_a_report_with_no_functions_is_not_printed_as_a_file_with_zero():
    text = build(functions=[])
    assert "Nothing was scored for this file." in text
    assert "0 of 0" not in text


def test_a_broken_report_file_does_not_stop_the_comment_being_written(tmp_path,
                                                                     monkeypatch):
    """A truncated file on the runner should produce a quiet comment, not a
    failed job with no comment at all."""
    module = load_comment_script()
    bad = tmp_path / "broken.json"
    bad.write_text("{ not json", encoding="utf-8")

    monkeypatch.setattr(module.sys, "argv",
                        ["make_pr_comment.py", "--report", str(bad),
                         "--repo", "o/n", "--pr", "1",
                         "--base-sha", "a", "--head-sha", "b"])
    monkeypatch.setattr(module.sys, "stdout",
                        (out := __import__("io").StringIO()))
    assert module.main() == 0
    assert "Nothing was scored" in out.getvalue()


def test_fallback_being_on_is_admitted():
    """The workflow hardcodes --no-fallback, so this should never happen. If it
    does, the comment has to say the run is a mixture rather than let the numbers
    stand."""
    text = build(fallback=True)
    assert "Fallback was permitted" in text
    assert "Treat these numbers with care." in text


def test_answers_from_the_second_provider_are_admitted():
    text = build(gemini_answers=4)
    assert "second provider" in text
    assert "should be 0" in text


def test_a_file_that_could_not_be_tested_says_nothing_is_claimed():
    text = build(generation_failed=True)
    assert "could not be tested at all" in text
    assert "Nothing is claimed about those files either way." in text


def test_the_comment_says_what_was_left_out():
    module = load_comment_script()
    text = module.build_comment(
        [("a.py", fake_report())],
        {"repo": "o/n", "pr": "1", "base_sha": "a", "head_sha": "b",
         "skipped": "3 of 8 changed .py files were not scored, because this "
                    "workflow scores at most 5 per pull request",
         "no_result": ""})
    assert "Not scored:" in text
    assert "3 of 8" in text


def test_the_comment_says_it_does_not_edit_anything():
    """A pull request that gets edited by a bot is a different thing from one
    that gets a comment."""
    text = build()
    assert "Nothing here edits your code or your tests." in text


def test_the_comment_never_prints_a_runner_path():
    """The reports hold the paths they were given, which on a runner are inside
    the runner's own workspace. Useless to a reader and noise in a thread."""
    text = build()
    assert "work/1/before.py" not in text
    assert "C:\\" not in text


def test_the_comment_script_never_names_an_api_key():
    text = read(COMMENT_SCRIPT)
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        assert name not in text, f"make_pr_comment.py names {name}"
    for shape in KEY_SHAPES:
        assert not re.search(shape, text)


# ---------------------------------------------------------------------------
# make_pr_comment.py itself
# ---------------------------------------------------------------------------

def test_the_script_is_valid_python_and_names_no_import_it_should_not():
    """A CI-only script is the easiest thing in this repository to break without
    noticing, because nothing local runs it."""
    tree = ast.parse(read(COMMENT_SCRIPT))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    allowed = {"argparse", "json", "sys", "pathlib", "prsentinel"}
    for name in imported:
        root = name.split(".")[0]
        assert root in allowed, \
            f"make_pr_comment.py imports {name}. It runs on every pull request, " \
            f"so it needs to stay small and its dependencies have to be worth " \
            f"the size. prsentinel is allowed for one name only, config, and " \
            f"the test below holds that."


def test_the_script_takes_only_the_model_name_from_the_package():
    """config is the one thing it borrows, so the model name in the comment
    cannot drift from the model the pipeline used. Nothing else from src/ may
    come in, or the comment would be able to say something the pipeline did not
    measure."""
    tree = ast.parse(read(COMMENT_SCRIPT))
    from_package = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "prsentinel":
            from_package.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module == "prsentinel.config":
            from_package.extend(alias.name for alias in node.names)

    assert sorted(from_package) == ["config"], \
        f"make_pr_comment.py takes {from_package} from the package. config for " \
        f"the model name is the whole allowance."


def test_the_script_asks_the_model_nothing_and_reaches_nowhere():
    """It only reads and prints. Checked against the imports rather than the
    text, so that the words pull requests or requests in a docstring cannot be
    mistaken for a network library."""
    tree = ast.parse(read(COMMENT_SCRIPT))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    roots = {name.split(".")[0] for name in imported}
    for name in ("ask_llm", "subprocess", "socket", "urllib", "http",
                 "requests", "httpx", "urllib3"):
        assert name not in roots, \
            f"make_pr_comment.py imports {name}. It builds a comment, nothing " \
            f"more."
    assert "ask_llm" not in read(COMMENT_SCRIPT), \
        "the comment script calls the model"


def test_a_label_goes_with_the_report_before_it():
    """The workflow passes the changed file's path so the comment reads in the
    language of the pull request rather than of the runner."""
    module = load_comment_script()
    reports = [("a.py", fake_report(name="prsentinel_1"))]
    text = module.build_comment(reports, {"repo": "o/n", "pr": "1",
                                          "base_sha": "a", "head_sha": "b",
                                          "skipped": "", "no_result": ""})
    assert "### a.py" in text


def test_running_the_script_writes_the_comment_to_standard_output(tmp_path,
                                                                  monkeypatch,
                                                                  capsys):
    """That is the whole contract with the workflow: the comment is on stdout."""
    import io
    module = load_comment_script()
    report = tmp_path / "prsentinel_1.json"
    report.write_text(json.dumps(fake_report()), encoding="utf-8")

    monkeypatch.setattr(module.sys, "argv",
                        ["make_pr_comment.py", "--report", str(report),
                         "--label", "src/thing.py",
                         "--repo", "owner/name", "--pr", "12",
                         "--base-sha", "aaa", "--head-sha", "bbb",
                         "--skipped", "2 files were left out"])
    assert module.main() == 0

    out = capsys.readouterr().out
    assert "src/thing.py" in out
    assert SAFETY_SENTENCE in out
    assert "2 files were left out" in out
    assert "CATCHES_CHANGE" in out or "catching the change" in out
