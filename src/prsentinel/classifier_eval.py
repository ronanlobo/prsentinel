"""Score the four classifiers against the answer key.

Run it like this:

    python -m prsentinel.classifier_eval

It walks through every folder in `examples/classifier_cases/`. For each one it

1. collects the evidence, with no knowledge of the answer,
2. runs all four classifiers, one after another, never in parallel,
3. and only then opens expected.json to see what the right answer was.

The order matters. The classifiers are finished before the answer key is
looked at, so nothing they do can depend on it.

This file and heldback_eval.py are the only two places allowed to read
expected.json. If the classifiers could read it too, the whole score would be
meaningless.

This only scores the tuning set. The cases we kept back are scored by
heldback_eval.py, which is a separate command on a separate folder.

The four classifiers being compared:

    rule                  plain Python, no AI, results only
    llm_full              the AI, with the code and the run results
    llm_full_with_intent  the same, plus the description of why the change was
                          made
    llm_code_only         the AI, with the code but not the run results

Comparing llm_full with llm_code_only tells us whether the AI is reading the
code or just reading the numbers off the table. Comparing llm_full with
llm_full_with_intent tells us whether the description helps.
"""

import json
from pathlib import Path

from prsentinel import classifier as cl

# Where the answer key lives. This file sits in src/prsentinel/, so we have to
# step up out of that folder and out of src as well.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_FOLDER = PROJECT_ROOT / "examples" / "classifier_cases"

# The classifiers we are scoring, in the order they run.
CLASSIFIERS = ("rule", "llm_full", "llm_full_with_intent", "llm_code_only")

# How many times each case is rerun when we work out whether it is flaky. We use
# the same number for every case, so a flaky case has to be mixed within this
# many runs or we call it something else. It is printed with the results.
RERUN_TIMES = 12

# A phrase that only ever turns up in the flaky cases. If an AI says this in
# its reason, it has spotted the tell rather than worked the case out, so we
# report it separately from the score.
GIVEAWAY_PHRASE = "RUN_INDEX"

# Widths for the printed table.
NAME_WIDTH = 32
CELL_WIDTH = 22


def case_folders():
    """Return every case folder, sorted so the run order never changes."""
    return sorted(path for path in CASES_FOLDER.iterdir() if path.is_dir())


def read_expected(folder):
    """Read one case's answer key.

    This is one of only two places in the project that open expected.json, and
    it is only ever called after the classifiers have already finished. The
    other is heldback_eval.py, which scores the cases we kept back.
    """
    return json.loads((folder / "expected.json").read_text(encoding="utf-8"))


def read_description(folder):
    """Read the case's description, or "" when it does not have one.

    Only the full_with_intent mode is shown this. The cases we keep back have
    none, and the older nine have none either, so this is usually "".
    """
    path = folder / "description.txt"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def mark_right_or_wrong(got, wanted):
    """Return the label with a star when it does not match the answer."""
    return got if got == wanted else f"{got} *"


def run_case(folder):
    """Collect the evidence and ask all the classifiers.

    Returns {"folder", "results", "errors"}. The answer key is not read here.
    """
    evidence = cl.collect_evidence(
        folder / "before.py",
        folder / "after.py",
        folder / "test_case.py",
        rerun_times=RERUN_TIMES,
        description=read_description(folder),
    )

    results = {}
    errors = {}
    for name in CLASSIFIERS:
        # One at a time, on purpose. Running them together would make the rate
        # limits much easier to hit, and ask_llm already retries those.
        try:
            results[name] = cl.classify(evidence, classifier=name)
        except cl.ClassifierError as error:
            # One unreadable reply should not throw away the other 17 answers.
            results[name] = {"label": "AI_ERROR", "confidence": "", "reason": ""}
            errors[name] = str(error)

    return {"folder": folder.name, "results": results, "errors": errors}


def print_table(rows):
    """Print the case-by-case comparison."""
    header = (
        f"{'case':{NAME_WIDTH}} {'expected':{CELL_WIDTH}}"
        f"{'rule':{CELL_WIDTH}}{'llm_full':{CELL_WIDTH}}"
        f"{'intent':{CELL_WIDTH}}llm_code_only"
    )
    print("=" * len(header))
    print(header)
    print("=" * len(header))

    for row in rows:
        wanted = row["expected"]
        cells = [mark_right_or_wrong(row["results"][name]["label"], wanted)
                 for name in CLASSIFIERS]
        print(f"{row['folder']:{NAME_WIDTH}} {wanted:{CELL_WIDTH}}"
              f"{cells[0]:{CELL_WIDTH}}{cells[1]:{CELL_WIDTH}}"
              f"{cells[2]:{CELL_WIDTH}}{cells[3]}")

    print("=" * len(header))
    print("A star means the answer did not match the answer key.")
    print("intent is llm_full_with_intent, shortened so the table fits.")


def print_accuracy(rows):
    """Print how many each classifier got right, out of how many."""
    total = len(rows)
    print("\n=== Accuracy ===")

    for name in CLASSIFIERS:
        right = sum(1 for row in rows
                    if row["results"][name]["label"] == row["expected"])
        share = (right / total * 100) if total else 0.0
        print(f"  {name:{16}} {right}/{total}  ({share:.0f}%)")


def print_wrong_answers(rows):
    """Print every wrong answer, with the reason the classifier gave."""
    print("\n=== Wrong answers ===")

    any_wrong = False
    for row in rows:
        for name in CLASSIFIERS:
            answer = row["results"][name]
            if answer["label"] == row["expected"]:
                continue

            any_wrong = True
            print(f"\n  {row['folder']}  [{name}]")
            print(f"    expected : {row['expected']}")
            print(f"    got      : {answer['label']}"
                  f"  (confidence: {answer['confidence'] or 'none'})")
            print(f"    reason   : {answer['reason'] or '(none given)'}")

        for name, message in row["errors"].items():
            print(f"\n  {row['folder']}  [{name}] could not be read")
            print(f"    {message}")

    if not any_wrong:
        print("  none, every classifier got every case right")


def print_giveaway_check(rows):
    """Report whether any AI reason mentions the known giveaway phrase."""
    print(f"\n=== Does any reason mention {GIVEAWAY_PHRASE}? ===")

    for name in ("llm_full", "llm_full_with_intent", "llm_code_only"):
        hits = []
        for row in rows:
            reason = row["results"][name]["reason"]
            if GIVEAWAY_PHRASE in reason.upper():
                hits.append(row["folder"])

        if hits:
            print(f"  {name}: yes, in {len(hits)} of {len(rows)} cases")
            for folder in hits:
                print(f"      - {folder}")
        else:
            print(f"  {name}: no")


def main() -> int:
    """Run every case through every classifier and print the results."""
    folders = case_folders()
    if not folders:
        print(f"No cases found in {CASES_FOLDER}")
        return 1

    print(f"Scoring {len(folders)} cases with {len(CLASSIFIERS)} classifiers.")
    print(f"Each case is rerun {RERUN_TIMES} times to check whether it is "
          f"flaky.")
    print(f"Answers come from one model call at a time, so this takes a "
          f"while.\n")

    rows = []
    for position, folder in enumerate(folders, start=1):
        print(f"[{position}/{len(folders)}] {folder.name}")
        outcome = run_case(folder)

        # Only now, with every classifier finished, do we look up the answer.
        outcome["expected"] = read_expected(folder)["label"]
        rows.append(outcome)

    print()
    print_table(rows)
    print_accuracy(rows)
    print_wrong_answers(rows)
    print_giveaway_check(rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
