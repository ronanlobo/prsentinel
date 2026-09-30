"""Decide what to say about one failing test.

A failing test on its own does not tell us much. It could mean:

    REAL_BUG   the test is asking for something reasonable and the changed code
               no longer does what it was meant to do
    BAD_TEST   the test is asking for something the code was never meant to do,
               or the change was deliberate and the test has not been kept up
    FLAKY      whether the test passes or fails comes down to chance, such as
               randomness, the current time, or the order things come back in,
               rather than to the code itself

There are two ways to reach that answer here:

    rule_classify   plain Python, no AI. It only uses the results.
    llm_classify    asks an AI, in one of two modes:

        "full"       the AI also sees how the test behaved when it was run
        "code_only"   the AI only sees the code and the failure message

Keeping the two modes apart is how we find out whether the AI is reading the
code or just reading the results off the table.

Nothing in this file may read `expected.json`. That file is the answer key for
the whole project, and a classifier that can see it is not being tested at all.
`classifier_eval.py` is the only file allowed to open it.
"""

import difflib
import json
import re
from pathlib import Path

from prsentinel import test_runner as tr
from prsentinel.llm_client import ask_llm

# ---------------------------------------------------------------------------
# The three answers.
# ---------------------------------------------------------------------------

REAL_BUG = "REAL_BUG"
BAD_TEST = "BAD_TEST"
FLAKY = "FLAKY"
ALL_LABELS = (REAL_BUG, BAD_TEST, FLAKY)

# The two ways we can ask the AI.
MODE_FULL = "full"
MODE_CODE_ONLY = "code_only"
ALL_MODES = (MODE_FULL, MODE_CODE_ONLY)

# How much of each file we put in the prompt, so one huge file cannot fill it.
MAX_CODE_CHARS = 4000

# A word for "low", "medium" or "high".
CONFIDENCE_LEVELS = ("low", "medium", "high")

# Anything that looks like a file path is swapped for this before we send on a
# failure message. Pytest sometimes includes one, and a path can carry the
# folder name, which would give the answer away.
PATH_LIKE = re.compile(r"[A-Za-z]:[\\/][^\s'\"]*|/(?:[\w.\-]+/)*[\w.\-]+\.\w+")
PATH_PLACEHOLDER = "<path>"


class ClassifierError(RuntimeError):
    """Raised when we cannot get a usable answer out of the AI."""


# ---------------------------------------------------------------------------
# Gathering the evidence
# ---------------------------------------------------------------------------

def _read_code(path) -> str:
    """Read a file and keep it inside the size limit."""
    text = Path(path).read_text(encoding="utf-8")
    if len(text) > MAX_CODE_CHARS:
        text = text[:MAX_CODE_CHARS] + "\n# ... cut off here ..."
    return text


def make_diff(old_code: str, new_code: str) -> str:
    """Return a readable line-by-line difference between the two versions.

    The labels are plain words, never real file names, so nothing about where
    the files live can leak into the prompt.
    """
    lines = difflib.unified_diff(
        old_code.splitlines(),
        new_code.splitlines(),
        fromfile="before",
        tofile="after",
        lineterm="",
    )
    return "\n".join(lines)


def remove_paths(text: str) -> str:
    """Swap anything that looks like a file path for a harmless placeholder."""
    if not text:
        return ""
    return PATH_LIKE.sub(PATH_PLACEHOLDER, text)


def _pick_test_name(before_run: dict, after_run: dict, test_name) -> str:
    """Work out which one test we are talking about.

    A test only makes sense one at a time. If we were given a name we use it.
    Otherwise we take the first test that failed on the new code, because that
    is the one we are being asked about, and fall back to the first test there
    is.
    """
    if test_name:
        return test_name

    failed = sorted(
        name for name, result in after_run["tests"].items()
        if result in (tr.FAILED, tr.TEST_ERROR)
    )
    if failed:
        return failed[0]

    every_name = sorted(after_run["tests"]) or sorted(before_run["tests"])
    return every_name[0] if every_name else ""


def _result_for(run: dict, name: str) -> str:
    """Return one test's result, or a sensible stand-in when it is missing."""
    if name in run["tests"]:
        return run["tests"][name]
    if not run["tests"]:
        # The whole file could not be loaded, so there are no per-test results.
        return run["status"]
    # It ran on one side only, which means we know nothing about this test.
    return tr.TEST_ERROR


def _rerun_for(rerun: dict, name: str) -> dict:
    """Return the rerun numbers for one test, or zeroes if it is not there."""
    if name in rerun["tests"]:
        return rerun["tests"][name]
    return {"passes": 0, "fails": 0, "verdict": "UNKNOWN"}


def build_evidence(before_run, after_run, rerun_run,
                   before_file, after_file, test_file, test_name=None) -> dict:
    """Build the evidence for one test out of runs we already have.

    collect_evidence does this, but it also has to run the tests. When a caller
    has already run them, this saves running everything again for every single
    test it wants to look at.
    """
    chosen = _pick_test_name(before_run, after_run, test_name)

    old_code = _read_code(before_file)
    new_code = _read_code(after_file)

    # A file-level error has no per-test message, so use that instead.
    message = after_run["failures_full"].get(chosen, "")
    if not message:
        message = after_run.get("error", "")

    return {
        "test_name": chosen,
        "old_code": old_code,
        "new_code": new_code,
        "diff": make_diff(old_code, new_code),
        "test_code": _read_code(test_file),
        "failure_message": remove_paths(message)[:tr.FULL_MESSAGE_CHARS],
        "before_result": _result_for(before_run, chosen),
        "after_result": _result_for(after_run, chosen),
        "rerun": _rerun_for(rerun_run, chosen),
    }


def collect_evidence(before_file, after_file, test_file,
                     test_name=None, rerun_times=None) -> dict:
    """Gather everything needed to talk about one failing test.

    Runs the test file against both versions of the module, runs it several
    more times against the new one, and collects the results next to the code
    and the failure message.

    test_name     which test to talk about. Leave it out and we pick the first
                  one that failed on the new code.
    rerun_times   how many reruns to do. Leave it out and we use the setting in
                  config.py. The tests use a small number to stay quick.

    Returns a dictionary with these keys:
        "old_code"          the code before the change
        "new_code"          the code after the change
        "diff"              a line-by-line difference between the two
        "test_code"         the test file
        "failure_message"   what the test printed on the new code, cleaned and
                            cut to a sensible length
        "before_result"     passed, failed or error on the old code
        "after_result"      the same on the new code
        "rerun"             {"passes", "fails", "verdict"} on the new code
        "test_name"         which test we are talking about

    Nothing in here is a folder name, a file path, or anything from the answer
    key. Only code and results.
    """
    before_run = tr.run_tests(before_file, test_file)
    after_run = tr.run_tests(after_file, test_file)
    rerun_run = tr.rerun_failures(after_file, test_file, times=rerun_times)

    return build_evidence(before_run, after_run, rerun_run,
                          before_file, after_file, test_file, test_name)


# ---------------------------------------------------------------------------
# The plain baseline. No AI at all.
# ---------------------------------------------------------------------------

def rule_classify(evidence: dict) -> dict:
    """Work out the label using only the results. No AI, no reading of code.

    The order of the checks matters. A test whose result changes from run to
    run tells us nothing else, so flakiness is checked first and wins.

    Returns {"label", "reason"}.
    """
    rerun = evidence.get("rerun") or {}
    before = evidence.get("before_result")
    after = evidence.get("after_result")
    fails_on_before = before in (tr.FAILED, tr.TEST_ERROR)

    # It passed at least once and failed at least once, so it is not telling
    # us anything reliable about the code.
    if rerun.get("passes") and rerun.get("fails"):
        return {
            "label": FLAKY,
            "reason": (
                f"Running it again gave {rerun.get('passes')} passes and "
                f"{rerun.get('fails')} failures, so the result depends on "
                f"chance rather than on the code."
            ),
        }

    # It failed even on the code we already had working, so the test itself is
    # the thing to look at.
    if fails_on_before:
        return {
            "label": BAD_TEST,
            "reason": (
                f"It failed on the old code as well ({before}), so the test "
                f"is not agreeing with code that was already working."
            ),
        }

    # It passed before and fails now, so the change is what broke it.
    if before == tr.PASSED and after in (tr.FAILED, tr.TEST_ERROR):
        return {
            "label": REAL_BUG,
            "reason": (
                f"It passed on the old code and fails on the new one ({after}), "
                f"so the change is what broke it."
            ),
        }

    # We should not normally get here. Say so plainly rather than guessing.
    return {
        "label": BAD_TEST,
        "reason": (
            f"Nothing in the results was conclusive (before={before}, "
            f"after={after}), so this falls back to looking at the test."
        ),
    }


# ---------------------------------------------------------------------------
# The AI classifiers
# ---------------------------------------------------------------------------

# The wording of the three labels, used in the prompt. These describe the ideas
# only. They never mention any particular case, folder, or expected answer.
LABEL_MEANINGS = (
    (REAL_BUG,
     "the test is reasonable and the new code broke intended behavior"),
    (BAD_TEST,
     "the test expects something the code was never meant to do, or the "
     "change was intentional and the test is now outdated"),
    (FLAKY,
     "the test result depends on chance (randomness, time, ordering) rather "
     "than on the code"),
)

# The shape we ask for. Kept in one place so the prompt and the parser agree.
JSON_SHAPE = (
    '{"label": "REAL_BUG" | "BAD_TEST" | "FLAKY", '
    '"confidence": "low" | "medium" | "high", '
    '"reason": "one or two plain sentences"}'
)

# What we add when the reply could not be read. Asking again with the same
# words works far better than repeating the identical prompt.
NUDGE = (
    "\n\nYour last reply could not be read. Please reply with JSON only, "
    f"using exactly this shape:\n{JSON_SHAPE}\n"
    "No other text, and no code fence."
)

# A code fence, with or without a language word after the backticks.
CODE_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\s*\n(.*?)```", re.DOTALL)


def _label_list_text() -> str:
    """Write out the three labels and what they mean, one per line."""
    return "\n".join(f"- {label}: {meaning}" for label, meaning in LABEL_MEANINGS)


def _results_text(evidence: dict) -> str:
    """Write out how the test behaved when it was run.

    Only the raw numbers go in. We do not hand over the word FLAKY or any other
    label, because the point is to see whether the AI can work it out.
    """
    rerun = evidence.get("rerun") or {}
    return (
        "Here is how this test behaved when it was run.\n"
        "\n"
        f"Result on the code before the change: {evidence.get('before_result')}\n"
        f"Result on the code after the change: {evidence.get('after_result')}\n"
        f"When the test was run again several times on the new code, it gave "
        f"{rerun.get('passes', 0)} pass and {rerun.get('fails', 0)} fail.\n"
    )


def build_prompt(evidence: dict, mode: str) -> str:
    """Build the prompt for one of the two AI modes.

    "full"       shows the results as well as the code
    "code_only"  shows only the code, the diff, the test and the message
    """
    if mode not in ALL_MODES:
        raise ValueError(
            f"Unknown mode {mode!r}. Use one of: {', '.join(ALL_MODES)}."
        )

    parts = [
        "You are looking at one failing test and trying to work out what is "
        "going on.",
        "",
        "Here is the code before the change.",
        "```python",
        evidence.get("old_code", ""),
        "```",
        "",
        "Here is the code after the change.",
        "```python",
        evidence.get("new_code", ""),
        "```",
        "",
        "Here is the difference between them.",
        "```diff",
        evidence.get("diff", "") or "(the two are the same)",
        "```",
        "",
        "Here is the test.",
        "```python",
        evidence.get("test_code", ""),
        "```",
        "",
        "Here is what the test printed when it failed.",
        "```text",
        evidence.get("failure_message", "") or "(nothing was printed)",
        "```",
        "",
    ]

    if mode == MODE_FULL:
        parts.append(_results_text(evidence))
        parts.append("")

    parts.extend([
        "Choose exactly one label:",
        _label_list_text(),
        "",
        "Base your answer on what the code is trying to do and what the test "
        "is checking. You cannot see any folder names or file paths, so do "
        "not try to guess from them.",
        "",
        f"Reply with JSON only, using exactly this shape:\n{JSON_SHAPE}\n"
        "No other text.",
    ])

    return "\n".join(parts)


def parse_reply(reply: str):
    """Read the AI's answer. Return a dictionary, or None if it is not usable.

    The reply may be plain JSON, or JSON inside a code fence, or JSON with a
    little text around it. The label has to be one of the three; that is the
    one thing we cannot guess at. The confidence and the reason are not
    important enough to throw the whole answer away, so we fill them in when
    they are missing.
    """
    if not reply or not reply.strip():
        return None

    text = reply.strip()

    # If there is a code fence, we only look at what is inside the first one.
    fenced = CODE_FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    label = str(data.get("label", "")).strip().upper()
    if label not in ALL_LABELS:
        return None

    confidence = str(data.get("confidence", "")).strip().lower()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "medium"

    return {
        "label": label,
        "confidence": confidence,
        "reason": str(data.get("reason", "")).strip(),
    }


def llm_classify(evidence: dict, mode: str) -> dict:
    """Ask the AI for one of the three labels.

    mode is "full" or "code_only", which decides how much we show it.

    If the reply cannot be read we ask once more, with a short note saying so.
    If the second reply cannot be read either we give up and raise
    ClassifierError, rather than guessing at an answer.
    """
    if mode not in ALL_MODES:
        raise ValueError(
            f"Unknown mode {mode!r}. Use one of: {', '.join(ALL_MODES)}."
        )

    prompt = build_prompt(evidence, mode)

    first = parse_reply(ask_llm(prompt))
    if first is not None:
        return first

    print("[prsentinel] the reply could not be read, asking once more...")

    second = parse_reply(ask_llm(prompt + NUDGE))
    if second is not None:
        return second

    raise ClassifierError(
        "The AI did not give a usable answer after two tries. It has to reply "
        f"with JSON only, using this shape: {JSON_SHAPE}"
    )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def classify(evidence: dict, classifier: str = "rule",
             mode: str = MODE_FULL) -> dict:
    """Run one classifier over the evidence and always give the same keys.

    classifier is "rule", "llm_full" or "llm_code_only".
    """
    if classifier == "rule":
        answer = rule_classify(evidence)
        answer.setdefault("confidence", "")
        return answer
    if classifier == "llm_full":
        return llm_classify(evidence, MODE_FULL)
    if classifier == "llm_code_only":
        return llm_classify(evidence, MODE_CODE_ONLY)

    raise ValueError(
        f"Unknown classifier {classifier!r}. Use rule, llm_full or "
        f"llm_code_only."
    )
