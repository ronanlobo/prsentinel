"""Score the cases we kept back, and print nothing else.

Run it like this:

    python -m prsentinel.heldback_eval

This scores `examples/classifier_cases_heldback/`, the cases that were set
aside before the work started and never looked at while the tool was being
built. Which case is in which set is written down in SPLIT.md at the top of the
project, and that file is not to be changed.

The output is deliberately tiny: how many cases there were, how many reruns
each one got, and one accuracy line per classifier. There is no case-by-case
table and no reasons from the AI. A held-back score is only worth having if
nothing about it can be used to pick answers, so printing the working would
undercut the point of holding the cases back in the first place.

Every run also appends one line to heldback_runs.log, so the runs cannot be
quietly repeated until a good number turns up.

This is one of only two files allowed to read expected.json, the other being
classifier_eval.py. This is the only file allowed to name the held-back folder.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from prsentinel import classifier as cl

# Where the kept-back cases live. This file sits in src/prsentinel/, so we have
# to step up out of that folder and out of src as well.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HELDBACK_FOLDER = PROJECT_ROOT / "examples" / "classifier_cases_heldback"

# The classifiers we are scoring, in the order we print them.
CLASSIFIERS = ("rule", "llm_full", "llm_full_with_intent", "llm_code_only")

# How many times each case is rerun to check whether it is flaky. The same
# number the tuning set uses, so the two scores are measured the same way.
RERUN_TIMES = 12

# The record of what has been run.
LOG_FILE = PROJECT_ROOT / "heldback_runs.log"

# Widths for the one line per classifier.
NAME_WIDTH = 22


def case_folders():
    """Return every kept-back case folder, sorted so the order never changes."""
    if not HELDBACK_FOLDER.is_dir():
        return []
    return sorted(path for path in HELDBACK_FOLDER.iterdir() if path.is_dir())


def read_expected(folder):
    """Read one kept-back case's answer key.

    This is called only after every classifier has already finished, so nothing
    they do can depend on the answer.
    """
    return json.loads((folder / "expected.json").read_text(encoding="utf-8"))


def read_description(folder):
    """Read the case's description, or "" when it does not have one."""
    path = folder / "description.txt"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def run_case(folder):
    """Collect the evidence and ask every classifier about this one case."""
    evidence = cl.collect_evidence(
        folder / "before.py",
        folder / "after.py",
        folder / "test_case.py",
        rerun_times=RERUN_TIMES,
        description=read_description(folder),
    )

    results = {}
    for name in CLASSIFIERS:
        # One at a time, on purpose. Running them together would make the rate
        # limits much easier to hit, and ask_llm already retries those.
        try:
            results[name] = cl.classify(evidence, classifier=name)
        except cl.ClassifierError:
            # An unreadable reply counts against the classifier, rather than
            # being quietly left out of the score.
            results[name] = {"label": "AI_ERROR", "confidence": "", "reason": ""}

    return results


def add_to_log(cases, scores):
    """Append one line saying this run happened and what it scored.

    If two runs of the kept-back set could differ, and nobody could tell, then
    reporting the better one would be easy and impossible to notice.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    parts = [f"{name}={right}/{cases}" for name, right in scores.items()]
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(f"{stamp}  cases={cases}  " + "  ".join(parts) + "\n")


def main() -> int:
    """Score every kept-back case and print only the totals."""
    # The AI writes its own reasons. We do not print them here, but the scores
    # are read from the same replies, so the stream is made safe the same way as
    # in classifier_eval.py. A reason that cannot be printed must not be able to
    # stop a held-back run halfway.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        # Not every stdout can do this, and not being able to is not a reason to
        # refuse to score the cases.
        pass

    folders = case_folders()
    if not folders:
        print(f"No kept-back cases found in {HELDBACK_FOLDER}")
        return 1

    wanted = []
    right = {name: 0 for name in CLASSIFIERS}

    for folder in folders:
        results = run_case(folder)

        # Only now, with every classifier finished, do we look up the answer.
        answer = read_expected(folder)["label"]
        wanted.append(answer)

        for name in CLASSIFIERS:
            if results[name]["label"] == answer:
                right[name] += 1

    total = len(folders)
    print(f"cases: {total}")
    print(f"reruns per case: {RERUN_TIMES}")

    scores = {}
    for name in CLASSIFIERS:
        share = right[name] / total * 100
        print(f"{name:{NAME_WIDTH}} {right[name]}/{total}  ({share:.0f}%)")
        scores[name] = right[name]

    add_to_log(total, scores)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())