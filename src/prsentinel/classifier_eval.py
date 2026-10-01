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

The five classifiers being compared:

    rule                  plain Python, no AI, results only
    llm_full              the AI, with the code and the run results
    llm_full_with_intent  the same, plus the description of why the change was
                          made
    llm_full_v2           the same as llm_full, plus one section explaining what
                          it means when the same test gives different results
                          when it is run again
    llm_code_only         the AI, with the code but not the run results

Comparing llm_full with llm_code_only tells us whether the AI is reading the
code or just reading the numbers off the table. Comparing llm_full with
llm_full_with_intent tells us whether the description helps. Comparing
llm_full with llm_full_v2 tells us whether saying what the rerun numbers mean
helps.

Every answer about llm_full_v2 is a sample, because the AI is not the same
twice. Use --repeats to see how much a single number moves.

Two options change what gets asked, not how it is judged:

    --only rule,llm_full     run only these classifiers. Useful when you want to
                             compare two and the daily allowance is tight.
    --no-fallback           stop the whole run if a provider runs out for the
                             day, instead of answering the rest from the other
                             model. A score made half from one model and half
                             from another is not a score.
"""

import argparse
import json
import sys
from pathlib import Path

from prsentinel import classifier as cl
from prsentinel import llm_client

# Where the answer key lives. This file sits in src/prsentinel/, so we have to
# step up out of that folder and out of src as well.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_FOLDER = PROJECT_ROOT / "examples" / "classifier_cases"

# The classifiers we are scoring, in the order they run.
CLASSIFIERS = ("rule", "llm_full", "llm_full_with_intent", "llm_full_v2",
               "llm_code_only")

# The ones that ask the AI. The giveaway check only makes sense for these,
# because the rule does not write a reason for us to read.
AI_CLASSIFIERS = tuple(name for name in CLASSIFIERS if name != "rule")

# The classifier the repeat summary is about. It is the one this experiment is
# testing, so the summary names it directly instead of making the reader go
# looking. Until that classifier is in CLASSIFIERS there is nothing to report
# and the summary stays quiet.
SUMMARY_CLASSIFIER = "llm_full_v2"

# The classifiers --only picked, or None to run all of them. This is set once in
# main() from the command line and read by everything that loops over
# classifiers, so there is only ever one answer to "which ones are we running".
CHOSEN = None


def chosen():
    """Return the classifiers to run, in CLASSIFIERS order.

    Order matters: the table, the accuracy list and the provider counts all
    follow it, so the columns stay in the same place whatever was chosen. Names
    the user gave out of order, or repeated, are therefore tidied up for them.
    """
    if CHOSEN is None:
        return CLASSIFIERS
    picked = set(CHOSEN)
    return tuple(name for name in CLASSIFIERS if name in picked)


# Raised by run_case when a provider runs out for the day and the run was told
# not to fall back. It is separate from the client's own error so the two layers
# are not confused: that one is about a provider, this one is about the run.
class DailyLimitStop(RuntimeError):
    """The run was stopped because a provider is out for the day."""


# The providers we could get an answer from, in the order we try them.
PROVIDERS = ("Groq", "Gemini")

# How many answers each classifier got from each provider. It is filled in as the
# run goes and printed at the end, so a score can be read alongside where the
# answers came from. Two different models can give two different scores, and a
# score with no provenance is not much use.
#
# Only a provider name is ever stored. No key, no header, no part of a key.
PROVIDER_TALLY = {}

# Whether we have already printed the notice about Gemini being used. We print
# it once, the first time, so it cannot be scrolled past unnoticed.
GEMINI_ANNOUNCED = False

# How many times each case is rerun when we work out whether it is flaky. We use
# the same number for every case, so a flaky case has to be mixed within this
# many runs or we call it something else. It is printed with the results.
RERUN_TIMES = 12

# A phrase that only ever turns up in the flaky cases. If an AI says this in
# its reason, it has spotted the tell rather than worked the case out, so we
# report it separately from the score.
GIVEAWAY_PHRASE = "RUN_INDEX"

# Widths for the printed table. Five classifiers will not fit across a normal
# terminal at the old width, so the headings are shortened and the cells are
# only as wide as the longest label plus the star.
NAME_WIDTH = 32
CELL_WIDTH = 10

# The short name for each classifier, used in the table headings. The full name
# is still what appears in the accuracy list and in every heading above a wrong
# answer, so nothing is ever ambiguous about which classifier is which.
SHORT_NAMES = {
    "rule": "rule",
    "llm_full": "full",
    "llm_full_with_intent": "intent",
    "llm_full_v2": "v2",
    "llm_code_only": "code_only",
}


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
    for name in chosen():
        # One at a time, on purpose. Running them together would make the rate
        # limits much easier to hit, and ask_llm already retries those.
        #
        # Cleared first so a provider can only ever be counted from the call we
        # are about to make, and not left over from an earlier one.
        llm_client.LAST_PROVIDER = ""
        try:
            results[name] = cl.classify(evidence, classifier=name)
            note_provider(name)
        except llm_client.DailyLimitReached as error:
            # Only reachable with --no-fallback, because otherwise ask_llm falls
            # back to the other provider on its own. Ending the whole run is the
            # point of the flag: a score made from part of the cases is worse
            # than no score at all.
            print_stopped_on_daily_limit(error)
            raise DailyLimitStop(error)
        except cl.ClassifierError as error:
            # One unreadable reply should not throw away the other 17 answers.
            results[name] = {"label": "AI_ERROR", "confidence": "", "reason": ""}
            errors[name] = str(error)

    return {"folder": folder.name, "results": results, "errors": errors}


def reset_provider_tally():
    """Start the provider counts again from nothing."""
    global GEMINI_ANNOUNCED

    PROVIDER_TALLY.clear()
    GEMINI_ANNOUNCED = False
    llm_client.CALLS_MADE = 0


def print_stopped_on_daily_limit(error):
    """Say clearly that the run stopped early and its numbers mean nothing.

    A run that dies half way has most of a report in it, and that report looks
    exactly like a finished one. Without this, someone could read an accuracy
    off a run that never finished and believe it.
    """
    print()
    print("!" * 70)
    print("! THE RUN STOPPED EARLY. A PROVIDER IS OUT FOR THE DAY.")
    print("!")
    print(f"! {error}")
    print("!")
    print(f"! Model calls completed before the stop: {llm_client.CALLS_MADE}")
    print("!")
    print("! Do not trust any score from this run. It did not finish, and the")
    print("! answers it did get came from only part of the case set, so an")
    print("! accuracy printed from them would be measuring the cases that were")
    print("! reached first, not how good the classifier is.")
    print("!")
    print("! Wait for the daily allowance to reset and run it again.")
    print("!" * 70)
    print()


def note_provider(name):
    """Count which provider answered for one classifier.

    Reads the name ask_llm left behind, and counts nothing if there is no name,
    which is what a rule classifier and a failed call both look like.
    """
    global GEMINI_ANNOUNCED

    provider = llm_client.LAST_PROVIDER
    if provider not in PROVIDERS:
        return

    counts = PROVIDER_TALLY.setdefault(name, {})
    counts[provider] = counts.get(provider, 0) + 1

    if provider == "Gemini" and not GEMINI_ANNOUNCED:
        # Said once, and said loudly. A score that came partly from the fallback
        # model is not the same measurement as one that came from Groq alone.
        GEMINI_ANNOUNCED = True
        print()
        print("!" * 70)
        print("! SOME ANSWERS CAME FROM GEMINI, THE FALLBACK PROVIDER.")
        print("! Groq could not answer every question, so these scores mix")
        print("! two different models. The counts are at the end of this report.")
        print("!" * 70)
        print()


def print_provider_counts():
    """Print how many answers each classifier got from each provider.

    Only the provider names and the counts are printed. Nothing from a call
    other than the name of who answered it ever reaches this table.
    """
    print(f"\n=== Where the answers came from ===")

    if not PROVIDER_TALLY:
        print("  No answers were counted, so no provider can be named.")
        return

    width = max(12, max(len(name) for name in PROVIDER_TALLY) + 2)

    header = f"{'classifier':<{width}}" + "".join(
        f"{provider:>12}" for provider in PROVIDERS)
    print(header)
    print("-" * len(header))

    for name in chosen():
        counts = PROVIDER_TALLY.get(name)
        if not counts:
            # The rule classifier asks nobody, so it has no row to be missing
            # from. We say so rather than leaving a silent gap.
            if name == "rule":
                print(f"{name:<{width}}{'asks nobody':>12}")
            continue
        cells = "".join(f"{counts.get(provider, 0):>12}"
                        for provider in PROVIDERS)
        print(f"{name:<{width}}{cells}")

    print("-" * len(header))

    groq = sum(counts.get("Groq", 0) for counts in PROVIDER_TALLY.values())
    gemini = sum(counts.get("Gemini", 0) for counts in PROVIDER_TALLY.values())
    print(f"{'total':<{width}}{groq:>12}{gemini:>12}")
    print("rule asks nobody, so it is not in the totals.")


def print_table(rows):
    """Print the case-by-case comparison.

    The loop is over the chosen classifiers, so choosing fewer needs no change
    here.
    """
    running = chosen()
    header = f"{'case':{NAME_WIDTH}} {'expected':{CELL_WIDTH}}" + "".join(
        f"{SHORT_NAMES.get(name, name):{CELL_WIDTH}}" for name in running)
    print("=" * len(header))
    print(header)
    print("=" * len(header))

    for row in rows:
        wanted = row["expected"]
        cells = [mark_right_or_wrong(row["results"][name]["label"], wanted)
                 for name in running]
        print(f"{row['folder']:{NAME_WIDTH}} {wanted:{CELL_WIDTH}}"
              + "".join(f"{cell:{CELL_WIDTH}}" for cell in cells))

    print("=" * len(header))
    print("A star means the answer did not match the answer key.")
    print("Columns: " + ", ".join(
        f"{SHORT_NAMES.get(name, name)} is {name}" for name in running))


def print_accuracy(rows):
    """Print how many each classifier got right, out of how many."""
    total = len(rows)
    print("\n=== Accuracy ===")

    for name in chosen():
        right = sum(1 for row in rows
                    if row["results"][name]["label"] == row["expected"])
        share = (right / total * 100) if total else 0.0
        print(f"  {name:{16}} {right}/{total}  ({share:.0f}%)")


def print_wrong_answers(rows, heading="=== Wrong answers ==="):
    """Print every wrong answer, with the reason the classifier gave.

    heading lets a repeated run say which run it belongs to. With a single run it
    is the same line it has always been.
    """
    print(f"\n{heading}")

    any_wrong = False
    for row in rows:
        for name in chosen():
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


def print_giveaway_check(rows, heading=None):
    """Report whether any AI reason mentions the known giveaway phrase."""
    if heading is None:
        heading = f"=== Does any reason mention {GIVEAWAY_PHRASE}? ==="
    print(f"\n{heading}")

    for name in chosen():
        if name == "rule":
            # The rule writes no reason for us to read, so there is nothing to
            # check. Skipped rather than printed as a misleading "no".
            continue

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


def right_count(rows, name):
    """How many of these rows the named classifier got right."""
    return sum(1 for row in rows
               if row["results"][name]["label"] == row["expected"])


def print_repeat_accuracy(runs):
    """Print every run's accuracy for each classifier, then the mean and range.

    A single number can hide a lot. One run of a small answer key is a sample,
    and for the flaky cases the evidence is different every time as well, so a
    classifier can look steady by luck. Showing the lowest and the highest says
    how much it actually moved.
    """
    total = len(runs[0])
    print("\n=== Accuracy, every run ===")

    for name in chosen():
        counts = [right_count(rows, name) for rows in runs]
        shares = [(count / total * 100) if total else 0.0 for count in counts]

        each = "  ".join(f"run {number}: {count}/{total} ({share:.0f}%)"
                         for number, (count, share)
                         in enumerate(zip(counts, shares), start=1))
        print(f"  {name}")
        print(f"      {each}")

        mean = sum(shares) / len(shares)
        print(f"      mean {mean:.0f}%   lowest {min(shares):.0f}%"
              f"   highest {max(shares):.0f}%")


def print_wrong_counts(runs):
    """Print how many of the runs each case was wrong for, per classifier.

    A case the classifier got wrong every single time is a different thing from
    one it got wrong once, and a single table of labels cannot show that. This
    says it directly: "2/3" means wrong on two of the three runs.
    """
    runs_count = len(runs)
    width = 9
    gap = "  "

    header = f"{'case':{NAME_WIDTH}}" + gap + gap.join(
        f"{SHORT_NAMES.get(name, name):>{width}}" for name in chosen())
    print("\n=== How many of the runs each case was wrong ===")
    print("=" * len(header))
    print(header)
    print("=" * len(header))

    for position, first_row in enumerate(runs[0]):
        cells = []
        for name in chosen():
            wrong = sum(1 for rows in runs
                        if rows[position]["results"][name]["label"]
                        != first_row["expected"])
            share = f"{wrong}/{runs_count}"
            # Zero is good news, so it is marked the same way the table marks a
            # right answer. Anything else is counted plainly.
            cells.append(share if wrong == 0 else f"{share} *")
        print(f"{first_row['folder']:{NAME_WIDTH}}" + gap + gap.join(
            f"{cell:>{width}}" for cell in cells))

    print("=" * len(header))
    print("A star means it was wrong at least once.")


def print_summary(runs):
    """List the cases the classifier we are testing got wrong, and how often.

    The per-case table above covers every classifier, but this is the one being
    tried out, so it gets its own short list at the end.
    """
    name = SUMMARY_CLASSIFIER
    if name not in chosen():
        # Left out by --only, so there is nothing of ours to report on.
        return

    runs_count = len(runs)
    print(f"\n=== {name}: cases it got wrong ===")

    listed = 0
    for position, first_row in enumerate(runs[0]):
        wrong = sum(1 for rows in runs
                    if rows[position]["results"][name]["label"]
                    != first_row["expected"])
        if not wrong:
            continue
        listed += 1
        print(f"  {first_row['folder']:<34} wrong in {wrong} of {runs_count} runs")

    if not listed:
        print("  none, it got every case right in every run")


def parse_args():
    """Read the command line."""
    parser = argparse.ArgumentParser(
        description="Score the classifiers against the answer key.")
    parser.add_argument("--repeats", type=int, default=1,
                        help="run the whole set this many times and report the "
                             "accuracy of each run. Everything is collected "
                             "again from scratch each time, so a case whose "
                             "results change from run to run is measured "
                             "honestly rather than asked about the same fixed "
                             "evidence several times. Default is 1.")
    parser.add_argument("--only", default=None,
                        help="run only these classifiers, separated by commas. "
                             f"Choose from: {', '.join(CLASSIFIERS)}. Default "
                             "is all of them. Use this to spend fewer model "
                             "calls when you only want to compare two.")
    parser.add_argument("--no-fallback", action="store_true",
                        help="do not fall back to the second provider. If a "
                             "provider runs out for the day, stop the whole run "
                             "and say so, because a score made half from one "
                             "model and half from another is not a score. "
                             "Default is off, so we fall back as usual.")
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats has to be 1 or more")

    if args.only is not None:
        args.only = check_only_names(args.only, parser)

    return args


def check_only_names(text, parser):
    """Check the --only list and give it back as a tuple of real names.

    A name we do not recognise is refused here rather than being quietly
    ignored, because a misspelled name that is skipped looks exactly like a
    classifier that was never asked anything.
    """
    wanted = [piece.strip() for piece in text.split(",")]
    wanted = [piece for piece in wanted if piece]

    if not wanted:
        parser.error("--only was given nothing to run. Write at least one of: "
                     f"{', '.join(CLASSIFIERS)}")

    unknown = [piece for piece in wanted if piece not in CLASSIFIERS]
    if unknown:
        # Every unknown name is listed, not just the first, so one go is enough
        # to fix them all.
        parser.error(
            "--only does not know: " + ", ".join(unknown) + "\n"
            f"       choose from: {', '.join(CLASSIFIERS)}")

    return tuple(wanted)


def run_all_cases(folders, repeats):
    """Run every case through every classifier, once per repeat.

    The evidence is gathered again for every repeat on purpose. The reruns are
    what tell us a test is flaky, and for a flaky case those results are
    different every time, so reusing one set of results would make the repeated
    runs agree for the wrong reason.

    Every model call still happens one at a time. Nothing here runs two things
    at once, so the rate limits behave the same as they always have.
    """
    runs = []

    for number in range(1, repeats + 1):
        if repeats > 1:
            print(f"\n########## Run {number} of {repeats} ##########")

        rows = []
        for position, folder in enumerate(folders, start=1):
            print(f"[{position}/{len(folders)}] {folder.name}")
            outcome = run_case(folder)

            # Only now, with every classifier finished, do we look up the answer.
            outcome["expected"] = read_expected(folder)["label"]
            rows.append(outcome)

        runs.append(rows)

    return runs


def main() -> int:
    """Run every case through every classifier and print the results."""
    # The AI writes its own reasons, so they can contain any character at all.
    # The default Windows console encoding cannot print some of them and stops
    # with an error, which used to cut the report off part way through. Asking
    # for utf-8 with replacements means a strange character turns into a "?"
    # instead of ending the run.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        # Not every stdout can do this. Some are not text streams at all, and
        # some are already closed. Neither is worth stopping the run for.
        pass

    args = parse_args()

    # From here on, chosen() is the single answer to "which classifiers run".
    # Everything else reads it, so there is no way for the table and the calls to
    # disagree about what was asked for.
    global CHOSEN
    CHOSEN = args.only

    # Every count in this run starts at zero, so a second call to main() in the
    # same process cannot inherit the first one's numbers.
    reset_provider_tally()

    # Set once, before any call, so llm_client can read it.
    llm_client.ALLOW_FALLBACK = not args.no_fallback

    folders = case_folders()
    if not folders:
        print(f"No cases found in {CASES_FOLDER}")
        return 1

    running = chosen()
    print(f"Scoring {len(folders)} cases with {len(running)} classifiers.")
    print(f"Each case is rerun {RERUN_TIMES} times to check whether it is "
          f"flaky.")
    print(f"Answers come from one model call at a time, so this takes a "
          f"while.\n")

    if args.repeats > 1:
        print(f"Running the whole set {args.repeats} times. Everything is "
              f"collected again each time.\n")

    try:
        runs = run_all_cases(folders, args.repeats)
    except DailyLimitStop:
        # The reason has already been printed in full by run_case, in the shape
        # that is meant to be impossible to miss. Nothing more is added here,
        # and in particular no accuracy table is printed: a half-finished run has
        # no accuracy to report.
        return 2

    print()

    # With one run this is exactly the report we have always printed. With more
    # than one, the per-case table is only shown for the first run, because the
    # same table repeated N times is just N times as much to read.
    print_table(runs[0])

    if args.repeats == 1:
        print_accuracy(runs[0])
        print_wrong_answers(runs[0])
        print_giveaway_check(runs[0])
        print_provider_counts()
        return 0

    print_repeat_accuracy(runs)
    print_wrong_counts(runs)

    for number, rows in enumerate(runs, start=1):
        print_wrong_answers(rows, heading=f"=== Wrong answers, run {number} ===")
        print_giveaway_check(
            rows, heading=(f"=== Does any reason mention {GIVEAWAY_PHRASE}?, "
                           f"run {number} ==="))

    print_summary(runs)
    print_provider_counts()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
