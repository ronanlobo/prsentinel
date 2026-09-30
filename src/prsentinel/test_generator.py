"""Ask the AI to write pytest tests for one changed function.

The idea: PRSentinel takes one change that diff_extractor found, builds a
prompt describing the old code and the new code, and asks the AI for tests.

Two things this file is careful about:

1. We never tell the AI which version is right or which is wrong. In real use
   we will not know that ourselves. The AI only ever sees old and new code.
2. We keep only the Python from the AI's reply, so the rest of the chatty
   text never ends up inside a saved test file.
"""

import argparse
import re
from pathlib import Path

from .diff_extractor import extract_changes_from_files
from .llm_client import ask_llm

# The only change types we write tests for. A removed function has nothing
# left to test, and an unchanged function has nothing new to check.
WANTED_CHANGE_TYPES = ("modified", "added")

# The module name the generated tests will import from.
TARGET_MODULE = "target"

# A code block that says it holds Python.
PYTHON_BLOCK = re.compile(r"```[Pp]ython[ \t]*\r?\n(.*?)```", re.DOTALL)

# A code block with no language label. Used when the AI forgets to say python.
PLAIN_BLOCK = re.compile(r"```[ \t]*\r?\n(.*?)```", re.DOTALL)

# Where generated test files are saved, if the caller does not say.
DEFAULT_OUTPUT_DIR = "generated_tests"


def build_prompt(change: dict) -> str:
    """Build the prompt that asks the AI for tests for one change.

    The prompt names the function, shows the old code and the new code, and
    lists the line numbers in each file. It never says which version is
    correct, because we do not know that ourselves.
    """
    name = change["name"]
    old_code = change["old_code"] or ""
    new_code = change["new_code"] or ""
    change_type = change["change_type"]

    # A brand new function has no old version to compare against.
    if old_code:
        old_part = f"OLD CODE:\n```python\n{old_code}\n```"
        old_lines = (f"- old file lines {change['old_start_line']}"
                     f" to {change['old_end_line']}")
    else:
        old_part = ("OLD CODE:\n(this function is new, so there is no old version)")
        old_lines = "- old file lines: none, this function is new"

    lines = [
        f"You are writing pytest tests for a Python function named `{name}`.",
        "",
        "A developer has just changed this function. The change type is "
        f"'{change_type}'.",
        "",
        old_part,
        "",
        "NEW CODE:",
        "```python",
        new_code,
        "```",
        "",
        "CHANGED LINE NUMBERS:",
        old_lines,
        f"- new file lines {change['new_start_line']} to {change['new_end_line']}",
        "",
        "Please write pytest tests for this function.",
        "",
        "What the tests should do:",
        "- Check that the function still does what the OLD version did. That "
        "OLD behaviour is the intended behaviour, so treat it as the "
        "specification.",
        "- Look for anything the change could have made worse.",
        "- Include the edge cases the change may have affected, such as empty "
        "input, one item, a size of zero, and sizes larger or smaller than "
        "the input.",
        "",
        "Rules for your answer:",
        f"- Import the function from a module named `{TARGET_MODULE}`, for "
        f"example: `from {TARGET_MODULE} import {name}`",
        "- Reply with pytest code only.",
        "- Put all of it in one single code block.",
        "- Do not explain anything outside the code block.",
    ]

    return "\n".join(lines)


def extract_code(reply: str) -> str:
    """Pull the Python out of the AI's reply.

    Returns just the code from inside the code block. Raises ValueError if
    there is no code block, so we never save chatty text as a test file.
    """
    if not reply or not reply.strip():
        raise ValueError("The AI sent an empty reply, so there is no code.")

    for pattern in (PYTHON_BLOCK, PLAIN_BLOCK):
        found = pattern.search(reply)
        if found:
            code = found.group(1)
            if code.strip():
                return code.strip() + "\n"

    raise ValueError(
        "The AI's reply has no code block in it, so there is no test code "
        "to save. Full reply:\n" + reply
    )


def generate_tests(change: dict) -> str:
    """Ask the AI for tests aimed at one change, and return the test code."""
    prompt = build_prompt(change)
    reply = ask_llm(prompt)
    return extract_code(reply)


def safe_file_name(function_name: str) -> str:
    """Turn a function name into something safe to use as a file name.

    A method is called 'Cart.add_item_to_cart'. The dot is fine on disk but
    it reads badly, so we swap it for an underscore.
    """
    return function_name.replace(".", "_").replace("<", "").replace(">", "")


def generate_for_two_files(before_path: str, after_path: str,
                           output_dir: str = DEFAULT_OUTPUT_DIR,
                           ask=ask_llm) -> dict:
    """Generate one test file per changed function, and report what happened.

    Only 'modified' and 'added' functions are used. 'removed' ones are
    skipped, because there is nothing left to test.

    Returns a dictionary with the example name, the files written, and the
    functions that failed. One failure does not stop the others.
    """
    example_name = Path(before_path).resolve().parent.name
    destination = Path(output_dir) / example_name
    changes = extract_changes_from_files(before_path, after_path)

    report = {"example_name": example_name, "written": [], "skipped": [],
              "failed": [], "output_dir": str(destination)}

    for change in changes:
        name = change["name"]
        if change["change_type"] not in WANTED_CHANGE_TYPES:
            report["skipped"].append((name, change["change_type"]))
            print(f"[prsentinel] skipping {name} because it is "
                  f"{change['change_type']}, not modified or added.")
            continue

        print(f"[prsentinel] writing tests for {name} ({change['change_type']})...")
        try:
            code = generate_tests(change)
        except Exception as error:
            report["failed"].append((name, str(error)))
            print(f"[prsentinel] could not write tests for {name}: {error}")
            continue

        destination.mkdir(parents=True, exist_ok=True)
        file_path = destination / f"test_{safe_file_name(name)}.py"
        file_path.write_text(code, encoding="utf-8")
        report["written"].append(str(file_path))
        print(f"[prsentinel] saved {file_path}")

    return report


def print_report(report: dict) -> None:
    """Print a short summary of what was written and what was not."""
    print("\n=== Summary ===")
    print(f"example     : {report['example_name']}")
    print(f"saved in    : {report['output_dir']}")
    print(f"files written: {len(report['written'])}")
    for path in report["written"]:
        print(f"  OK      {path}")
    for name, reason in report["skipped"]:
        print(f"  SKIPPED {name} ({reason})")
    for name, reason in report["failed"]:
        print(f"  FAILED  {name}: {reason}")


def main() -> int:
    """Let us run this from the terminal:
    python -m prsentinel.test_generator before.py after.py
    """
    parser = argparse.ArgumentParser(
        description="Ask the AI to write pytest tests for each changed function."
    )
    parser.add_argument("before_file", help="path to the old version of the file")
    parser.add_argument("after_file", help="path to the new version of the file")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                        help=f"where to save the tests (default: {DEFAULT_OUTPUT_DIR})")
    args = parser.parse_args()

    try:
        report = generate_for_two_files(args.before_file, args.after_file,
                                        args.output_dir)
    except FileNotFoundError as error:
        print(f"Cannot read that file: {error}")
        return 1
    except SyntaxError as error:
        print(f"That file has a syntax error: {error}")
        return 1

    print_report(report)

    # Keep going through the others, but still fail loudly at the end.
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
