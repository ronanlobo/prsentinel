"""Score the cases we kept back, and print nothing else.

Run it like this:

    python -m prsentinel.heldback_eval

This scores `examples/classifier_cases_heldback/`, the cases that were set
aside before the work started and never looked at while the tool was being
built. Which case is in which set is written down in SPLIT.md at the top of the
project, and that file is not to be changed.

The output is deliberately tiny: how many cases there were, how many reruns
each one got, which classifiers are being scored, and one accuracy line per
classifier. There is no case-by-case table and no reasons from the AI. A held-back
score is only worth having if nothing about it can be used to pick answers, so
printing the working would undercut the point of holding the cases back in the
first place.

Three things stop this run from producing a number it should not:

- it refuses to start while the tuning scores are still unfilled in, because
  scoring the kept-back cases first would let somebody choose the prompt on the
  one set that is supposed to be unspent;
- it never falls back to the second provider, so a score cannot be made half
  from one model and half from another;
- if any answer did come from the other provider anyway, it says the run is not
  valid and prints no accuracy at all.

Each of those exits with its own code, so a caller can tell a finished valid run
from a refused, a stopped and a mixed one. 0 means valid and nothing else.

Every run also appends one line to heldback_runs.log, so the runs cannot be
quietly repeated until a good number turns up. Refused, stopped and not-valid
runs are logged too, each marked, and none of them carries a score.

This is one of only two files allowed to read expected.json, the other being
classifier_eval.py. This is the only file allowed to name the held-back folder.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from prsentinel import classifier as cl
from prsentinel import llm_client

# Where the kept-back cases live. This file sits in src/prsentinel/, so we have
# to step up out of that folder and out of src as well.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
HELDBACK_FOLDER = PROJECT_ROOT / "examples" / "classifier_cases_heldback"

# The classifiers we are scoring, in the order we print them.
#
# Three, and no more. `llm_full_with_intent` and `llm_code_only` are not scored
# here. This is the one set the prompt was never tuned against, so it is kept as
# small as the question needs it to be: `rule` as a free baseline, and the two
# prompts that were actually measured against each other on the tuning set.
CLASSIFIERS = ("rule", "llm_full", "llm_full_v2")

# How many times each case is rerun to check whether it is flaky. The same
# number the tuning set uses, so the two scores are measured the same way.
RERUN_TIMES = 12

# The record of what has been run.
LOG_FILE = PROJECT_ROOT / "heldback_runs.log"

# Where the prompts are written down. This run refuses to start until that file
# says the tuning scores were measured, because scoring the kept-back cases
# before the prompt is measured on the tuning set would mean picking which of
# the two prompts looks better here and calling that the answer.
PROMPT_LOG = PROJECT_ROOT / "PROMPT_LOG.md"

# The two phrases that mean the tuning scores have not been filled in yet. The
# refusal triggers on either one, so a half-finished log cannot slip through.
UNMEASURED_PHRASES = ("not measured yet", "not yet run")

# Widths for the one line per classifier.
NAME_WIDTH = 22

# The exit codes. Each one means something different, and 0 has to mean a
# finished, valid run and nothing else, because that is what a caller checks.
EXIT_OK = 0
EXIT_NO_CASES = 1
EXIT_REFUSED = 2
EXIT_DAILY_LIMIT = 3
EXIT_NOT_VALID = 4


class DailyLimitStop(RuntimeError):
    """A provider is out for the day, so this run has to stop.

    This run never falls back to the other provider. A kept-back score made half
    from one model and half from another is not a kept-back score, and there is
    no flag to turn this off, because there is nothing worth turning it on for.
    """


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
        #
        # Cleared first, so a provider can only be read from the call we are
        # about to make and never left over from an earlier one.
        llm_client.LAST_PROVIDER = ""
        try:
            results[name] = cl.classify(evidence, classifier=name)
        except llm_client.DailyLimitReached:
            # Never falls back here, so this ends the whole run. There is no
            # switch for it on this command, on purpose.
            raise
        except cl.ClassifierError:
            # An unreadable reply counts against the classifier, rather than
            # being quietly left out of the score.
            results[name] = {"label": "AI_ERROR", "confidence": "", "reason": ""}

        # Which provider answered, kept with the answer. This is only the name
        # of a provider, never a key or any part of one, and it is how we find
        # out afterwards whether the whole run came from the model we meant.
        #
        # A classifier that failed has no provider, which is recorded as "". It
        # must not be left out, or a failed call would be invisible in the count
        # and a run could look entirely Groq while half of it failed.
        results[name]["provider"] = llm_client.LAST_PROVIDER

    return results


def add_to_log(cases, scores, outcome, extra=""):
    """Append one line saying this run happened and what it scored.

    If two runs of the kept-back set could differ, and nobody could tell, then
    reporting the better one would be easy and impossible to notice.

    Every run is logged, not only the good ones. A run that stopped or produced
    a mixed-model score is exactly the sort of run somebody might forget about
    and rerun until a clean one turned up, so its line is marked as not valid
    and carries no score to be misread later.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if outcome == "valid":
        parts = [f"{name}={right}/{cases}" for name, right in scores.items()]
        detail = f"cases={cases}  " + "  ".join(parts)
    else:
        # No scores on purpose. A number here could be quoted as a kept-back
        # result later, which is the one thing this file exists to prevent.
        detail = f"cases={cases}  NO SCORE"

    line = f"{stamp}  {outcome}"
    if extra:
        line += f"  {extra}"
    line += f"  {detail}\n"

    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(line)


def prompt_log_is_measured():
    """Return the phrase that means the tuning scores are not in yet, or "".

    Reads the log rather than trusting anything else, so the check reflects the
    file as it is on disk right now.
    """
    if not PROMPT_LOG.is_file():
        return f"{PROMPT_LOG.name} is missing"

    text = PROMPT_LOG.read_text(encoding="utf-8").lower()
    for phrase in UNMEASURED_PHRASES:
        if phrase in text:
            return phrase

    return ""


def print_refused(reason):
    """Say why this run will not start, before any case is touched.

    Scoring the kept-back cases before the prompt has been measured on the
    tuning set would let somebody pick whichever prompt looks better here. That
    is the thing these cases exist to prevent, so it is refused rather than
    warned about.
    """
    print("RUN REFUSED. The tuning scores have not been measured yet.")
    print()
    print(f"Why: {PROMPT_LOG.name} still says \"{reason}\".")
    print()
    print("The kept-back cases are only worth scoring once the prompt has a")
    print("tuning score to be compared against. Scoring them first would mean")
    print("choosing which of the two prompts looks better on the very set that")
    print("is supposed to be unspent, and calling that the result.")
    print()
    print(f"Fill the scores into {PROMPT_LOG.name} and run this again.")


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

    # The rule and one model each, never two models mixed into one score. This
    # has no flag to undo it, which is the point.
    llm_client.ALLOW_FALLBACK = False
    llm_client.CALLS_MADE = 0

    # Refused before anything is collected and before anybody is asked, so a
    # refused run costs nothing and leaves no trace on the cases.
    reason = prompt_log_is_measured()
    if reason:
        print_refused(reason)
        add_to_log(0, {}, "REFUSED", f"prompt_log={reason}")
        return EXIT_REFUSED

    folders = case_folders()
    if not folders:
        print(f"No kept-back cases found in {HELDBACK_FOLDER}")
        return EXIT_NO_CASES

    # How many answers each provider gave, so we can say afterwards whether all
    # of them came from the one model we meant to use.
    providers = {"Groq": 0, "Gemini": 0}

    right = {name: 0 for name in CLASSIFIERS}

    try:
        for folder in folders:
            results = run_case(folder)

            # Counted before the answer is read, and after every classifier has
            # finished, so nothing about the answer can reach this.
            for name in CLASSIFIERS:
                provider = results[name].get("provider")
                if provider in providers:
                    providers[provider] += 1

            # Only now, with every classifier finished, do we look up the answer.
            answer = read_expected(folder)["label"]

            for name in CLASSIFIERS:
                if results[name]["label"] == answer:
                    right[name] += 1
    except llm_client.DailyLimitReached as error:
        # Stopped part way through. The cases reached so far are a subset, and an
        # accuracy from a subset would measure which cases came first rather than
        # how good the classifier is, so nothing is printed that could be read as
        # a score.
        print()
        print("RUN STOPPED. A provider is out for the day.")
        print()
        print(f"Why: {error}")
        print()
        print(f"Model calls completed before the stop: {llm_client.CALLS_MADE}")
        print()
        print("No accuracy is printed, and none should be taken from this run. It")
        print("did not finish, so any score from it would only cover the cases")
        print("that were reached first. This run does not fall back to the other")
        print("model, because a score from two models is not a score.")
        print()
        print("Wait for the daily allowance to reset and run this again.")
        add_to_log(len(folders), {}, "STOPPED daily limit",
                   f"calls={llm_client.CALLS_MADE}")
        return EXIT_DAILY_LIMIT

    total = len(folders)

    if providers["Gemini"]:
        # Said instead of any score. A score here would be half one model and
        # half another, which reads exactly like a kept-back result.
        print("RUN NOT VALID: answers came from more than one model")
        print()
        print(f"{providers['Gemini']} of "
              f"{providers['Groq'] + providers['Gemini']} answers came from the "
              f"fallback provider instead of {llm_client.config.GROQ_MODEL}.")
        print()
        print("A score made from more than one model is not a score. No accuracy")
        print("is printed, and none should be written down. Wait for the daily")
        print("allowance to reset and run this again on one model.")
        add_to_log(total, {}, "NOT VALID",
                   f"gemini_answers={providers['Gemini']}")
        return EXIT_NOT_VALID

    print(f"cases: {total}")
    print(f"reruns per case: {RERUN_TIMES}")
    print(f"classifiers: {', '.join(CLASSIFIERS)}")

    scores = {}
    for name in CLASSIFIERS:
        share = right[name] / total * 100
        print(f"{name:{NAME_WIDTH}} {right[name]}/{total}  ({share:.0f}%)")
        scores[name] = right[name]

    add_to_log(total, scores, "valid")

    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())