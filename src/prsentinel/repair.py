"""Ask the AI to correct one test that the pipeline judged to be the wrong test.

The pipeline writes tests for a changed function, runs them, and judges every
failure. Some failures are judged to be the fault of the test rather than the
code. When that happens, this file builds a prompt asking for that test to be
corrected, and hands the reply back.

What this file will not do, and why:

1. It never says which version of the function is at fault. The repair is only
   ever asked for a test that was already judged to be wrong, but the prompt
   still does not claim the new code is fine. It says what the old code did and
   asks for the test to expect that, which is the part the pipeline knows.
2. It never tells the writer to make the test pass. "Make it pass" would get a
   passing test and teach us nothing; the test has to pass because it now states
   the intended behaviour, and it still has to fail on code that breaks it.
3. It never repairs a test that was judged to be a real bug or to be flaky. A
   real bug must never be repaired away, and a flaky test is not a wrong test.
   That rule lives in the pipeline, which is the only caller.

The prompt asks for the whole file back, so one repair can change every test in
it. The pipeline guards against that by checking the other tests after the
candidate is run, and rejecting a repair that damages one of them.
"""

from pathlib import Path

from . import config
from . import test_generator as tg
from .llm_client import ask_llm

# The module name a repaired test should import from. The same name the writer
# used the first time, because the runner puts the module in place under it.
TARGET_MODULE = tg.TARGET_MODULE


def build_repair_prompt(function_change, test_source, failing_test_name,
                        failure_message, attempt, weakened_before=False) -> str:
    """Build the prompt that asks for one test file to be corrected.

    The prompt shows the function before and after the change, the whole test
    file, the one test that is wrong, and what it printed when it failed. It
    asks for the whole file back, with that test's expectations corrected so
    they match what the code did BEFORE the change.

    It does not say which version is right, and it does not ask for a passing
    test. Both of those would turn a repair into a game, and the point is to
    find out what the test should have said all along.

    weakened_before adds one line when the previous attempt passed its own test
    but changed how the other tests in the file behaved. The writer is told, so
    it has a chance to leave them alone this time.
    """
    name = function_change["name"]
    old_code = function_change.get("old_code") or ""
    new_code = function_change.get("new_code") or ""

    # A brand new function has no old version, so there is no earlier
    # behaviour to match. The prompt says so rather than showing an empty block.
    if old_code:
        old_part = (f"Here is the function before the change.\n"
                    f"```python\n{old_code}\n```")
    else:
        old_part = ("Here is the function before the change.\n"
                    "(This function is new, so there was no earlier version.)")

    lines = [
        f"You are correcting one pytest test file for a Python function named "
        f"`{name}`.",
        "",
        "Some tests were written for this function. One of them is failing in a",
        "way that says the test itself is wrong, rather than the code being",
        "wrong. We want that test corrected.",
        "",
        old_part,
        "",
        "Here is the function after the change.",
        "```python",
        new_code,
        "```",
        "",
        "Here is the whole test file as it stands now.",
        "```python",
        test_source.rstrip(),
        "```",
        "",
        f"The test that is wrong is: {failing_test_name}",
        "",
        "Here is what it printed when it failed.",
        "```text",
        (failure_message or "").rstrip(),
        "```",
        "",
        "Correct that test's expectations so they match what the function did "
        "BEFORE the change. That earlier behaviour is the behaviour the test "
        "should be checking, so treat it as the specification.",
        "",
        f"This is attempt {attempt} of {config.MAX_REPAIR_ATTEMPTS}.",
    ]

    if weakened_before:
        lines += [
            "The previous attempt corrected its own test but changed how the",
            "other tests in the file behaved. Leave the other tests exactly as",
            "they are and only change the expectations of the one test above.",
        ]

    lines += [
        "",
        "Rules for your answer:",
        f"- Import from a module named `{TARGET_MODULE}`, for example: "
        f"`from {TARGET_MODULE} import {name}`",
        "- Keep every other test in the file as it is.",
        "- Reply with pytest code only.",
        "- Put all of it in one single code block.",
        "- Do not explain anything outside the code block.",
    ]

    return "\n".join(lines)


def repair_test(function_change, test_source, failing_test_name,
                failure_message, attempt, weakened_before=False,
                ask=ask_llm) -> str:
    """Ask for a corrected test file and return the code from the reply.

    Returns the whole corrected file as a string. Raises ValueError, from
    test_generator.extract_code, when the reply has no code block in it, so a
    chatty reply is never saved as a test file.

    ask is the function used to reach the AI. It is a parameter so the tests can
    put a fake in its place and so no test ever calls a real model.
    """
    prompt = build_repair_prompt(function_change, test_source,
                                 failing_test_name, failure_message, attempt,
                                 weakened_before)
    reply = ask(prompt, config.GENERATION_TEMPERATURE)
    return tg.extract_code(reply)


def repair_file_name(test_file) -> str:
    """The file name a candidate repair should use.

    The runner runs the file from a folder of its own, so only the name travels.
    Keeping the original name means a failure message still names the same file.
    """
    return Path(test_file).name
