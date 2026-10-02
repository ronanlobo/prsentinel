r"""Turn the pipeline's reports into the comment PRSentinel leaves on a pull request.

Run it like this:

    python scripts/make_pr_comment.py --report reports/prsentinel_1.json --repo owner/name --pr 12 --base-sha abc123 --head-sha def456

Everything it prints goes straight into a pull request comment, so it says one
fixed thing about what the tests are before it says anything about what they
found. That sentence is a constant at the top of this file and a test holds it,
so it cannot be quietly softened into something that sounds more confident than
the evidence is.

It asks no questions of a model and makes no network calls. It reads report files
that already exist and writes markdown to standard output. Every test for it
runs offline against a made-up report, which is why there is no live number
anywhere in this file.

When a run is stopped by the daily allowance, --no-result wins over any reports
that were already written. A partial score sitting under a heading that says
nothing was scored reads like a complete result for a smaller pull request, so
the comment says there is no result and stops. The partial reports are still
saved and still uploaded as artifacts, so nothing measured is thrown away.

What it deliberately does not do
--------------------------------
This script is self-contained on purpose. The evaluation script already has the
report counting code, but importing it would pull the folder-holding check
script and the evaluation data's paths into the code path that runs on every
pull request, including pull requests from strangers. An evaluation-only folder
has no business in the path of a CI job, so the few lines of counting live here
instead and are held to the same rule: tests count pytest test items, and a
test counts as catching the change when the runner labelled it CATCHES_CHANGE,
which means it passed on before.py and failed on after.py.

Nothing here names an API key. The model name comes from config, so it cannot
drift from the model the pipeline actually used.
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, str(PROJECT / "src"))

from prsentinel import config  # noqa: E402

# The one sentence that is always true and always comes first. It is what stops a
# reader taking CATCHES_CHANGE as proof that a bug is real.
FIXED_SENTENCE = "Tests are AI-generated. A catching test is a hint, not proof."

# A marker in the body, so the workflow can find this comment and edit it instead
# of leaving a new one on every push to the same pull request. An HTML comment
# renders as nothing.
MARKER = "<!-- prsentinel-report -->"

# The labels the runner puts on each test. Spelled out here rather than imported
# so that this file stays standalone: nothing outside it can change what these
# numbers mean.
CATCHES_CHANGE = "CATCHES_CHANGE"
TEST_WRONG_ON_BEFORE = "TEST_WRONG_ON_BEFORE"
NO_SIGNAL = "NO_SIGNAL"
ODD = "ODD"

RULE = "-" * 60


def count_function(function: dict) -> dict:
    """The four numbers the comment shows for one changed function.

    tests counts pytest test items, so a parametrized test with five cases counts
    as five. It is not a count of files and not a count of test functions.
    """
    counts = function.get("counts") or {}

    real_bug = 0
    for judgement in function.get("judgements") or []:
        if judgement.get("verdict") == "REAL_BUG":
            real_bug += 1

    return {
        "function": function.get("function", "?"),
        "tests": sum(counts.values()),
        "catches_change": counts.get(CATCHES_CHANGE, 0),
        "wrong_on_before": counts.get(TEST_WRONG_ON_BEFORE, 0),
        "no_signal": counts.get(NO_SIGNAL, 0),
        "odd": counts.get(ODD, 0),
        "real_bug": real_bug,
    }


def mutation_line(report: dict, function_name: str) -> str:
    """How many deliberate faults the tests caught, in one short phrase.

    Three outcomes, and they are genuinely different, so all three get their own
    wording. "0%" would be a lie in the second case.
    """
    for entry in report.get("mutation") or []:
        if entry.get("function") != function_name:
            continue

        score = entry.get("score")
        if score is None:
            reason = entry.get("reason") or "no score"
            return f"not defined - {reason}"

        killed = entry.get("killed", 0)
        found = entry.get("found", 0)
        return f"{round(score * 100)}% ({killed} of {found} mutants killed)"

    return "not run"


def read_report(path: str) -> dict:
    """Read one report file. Returns {} rather than raising on a broken file."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def one_block(name: str, report: dict) -> list:
    """The lines for one file. A report with nothing in it says so."""
    functions = report.get("functions") or []

    if not functions:
        return [f"### {name}", "",
                "Nothing was scored for this file.", ""]

    lines = [f"### {name}", ""]

    for function in functions:
        counts = count_function(function)
        caught = counts["catches_change"] > 0

        lines.append(f"- `{counts['function']}` - "
                     f"**{counts['tests']}** tests, "
                     f"{counts['catches_change']} catching the change, "
                     f"mutation {mutation_line(report, counts['function'])}")

        if counts["wrong_on_before"]:
            lines.append(f"  - {counts['wrong_on_before']} of them also fail on "
                         f"the old code, so they cannot show anything about "
                         f"this change")
        if counts["odd"]:
            lines.append(f"  - {counts['odd']} of them pass on the new code and "
                         f"fail on the old, which is the other way round")
        if counts["real_bug"]:
            lines.append(f"  - {counts['real_bug']} of the catching tests were "
                         f"judged to point at a real bug")
        if not caught:
            lines.append("  - no test caught this change")

    return lines + [""]


def headline(reports: list) -> str:
    """One line saying how many files caught their change."""
    caught = 0
    for _name, report in reports:
        for function in report.get("functions") or []:
            if (function.get("counts") or {}).get(CATCHES_CHANGE, 0):
                caught += 1
                break

    files = len([1 for _n, r in reports if r.get("functions")])
    if not files:
        return "Nothing was scored, so there is nothing to say about this pull request."

    return (f"**{caught} of {files} changed "
            f"{'file' if files == 1 else 'files'} had a test that caught the "
            f"change.**")


def provenance_notes(reports: list) -> list:
    """Anything about how the run was made that a reader should know.

    With --no-fallback hardcoded in the workflow, fallback should never be on and
    Gemini should never answer. If one of these ever fires, the run was not what
    the workflow says it is, and saying so is better than staying quiet.
    """
    notes = []

    if any(report.get("fallback") for _n, report in reports):
        notes.append("Fallback was permitted in at least one of these runs, "
                     "which this workflow does not do. Treat these numbers with "
                     "care.")

    gemini = sum(report.get("gemini_answers") or 0 for _n, report in reports)
    if gemini:
        notes.append(f"{gemini} of these answers came from the second provider "
                     f"rather than from {config.GROQ_MODEL}. This workflow "
                     f"turns that provider off, so this number should be 0.")

    if any(report.get("generation_failed") for _n, report in reports):
        notes.append("At least one file could not be tested at all. Nothing is "
                     "claimed about those files either way.")

    return notes


def build_comment(reports: list, facts: dict) -> str:
    """The whole comment, as one string.

    reports is a list of (name, report) pairs. facts holds the run's own details:
    repo, pr, base_sha, head_sha, and the two optional sentences about what was
    not scored and why there is no result.
    """
    lines = [
        MARKER,
        "",
        "## PRSentinel",
        "",
        f"**{FIXED_SENTENCE}**",
        "",
    ]

    # What ran, so a reader can tell what this comment is about.
    run = [f"Pull request #{facts.get('pr')} in `{facts.get('repo')}`",
           f"from `{facts.get('base_sha')}` to `{facts.get('head_sha')}`",
           f"model {config.GROQ_MODEL}, one provider only"]
    lines.extend(f"- {item}" for item in run if item)
    lines.append("")

    # A run that did not finish says so before anything else, because there is
    # nothing below it to read.
    if facts.get("no_result"):
        lines.extend([
            "### No result",
            "",
            f"{facts['no_result']}",
            "",
            "Nothing was scored, so this comment says nothing about whether "
            "the change is safe. That is not a pass.",
            "",
        ])
        return "\n".join(lines) + "\n"

    for name, report in reports:
        lines.extend(one_block(name, report))

    lines.append(RULE)
    lines.append("")
    lines.append(headline(reports))
    lines.append("")

    notes = provenance_notes(reports)
    for note in notes:
        lines.append(f"> {note}")
    if notes:
        lines.append("")

    if facts.get("skipped"):
        lines.extend([f"> Not scored: {facts['skipped']}", ""])

    lines.extend([
        RULE,
        "",
        "Each test above was written by the model from the old and new source of "
        "one function, then run against both. A test that passes on the old code "
        "and fails on the new one is labelled `CATCHES_CHANGE`. Nothing here "
        "edits your code or your tests.",
        "",
        "The numbers come from the report files attached to this run, so they can "
        "be read rather than taken on trust.",
        "",
    ])

    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the PRSentinel comment from saved reports.")
    parser.add_argument("--report", action="append", default=[],
                        help="a report .json file. May be given more than once. "
                             "None at all is allowed, and says so rather than "
                             "failing, because a run that scored nothing still "
                             "has a reason worth leaving on the pull request.")
    parser.add_argument("--label", action="append", default=[],
                        help="what to call the report that comes before it, in "
                             "the same order. The workflow uses this to show the "
                             "changed file's path instead of the report's own "
                             "name. Any report without one keeps its own name.")
    parser.add_argument("--repo", default="", help="owner/name")
    parser.add_argument("--pr", default="", help="pull request number")
    parser.add_argument("--base-sha", default="", help="the older commit")
    parser.add_argument("--head-sha", default="", help="the newer commit")
    parser.add_argument("--skipped", default="",
                        help="a sentence saying what was not scored and why")
    parser.add_argument("--no-result", default="",
                        help="a sentence saying why there is no result at all")

    args = parser.parse_args(argv)

    # A label belongs to the report in the same place. A report past the end of
    # the labels keeps its own name, so a short list cannot lose a result.
    labels = list(args.label) + [None] * (len(args.report) - len(args.label))

    reports = []
    for path, label in zip(args.report, labels):
        reports.append((label or Path(path).stem, read_report(path)))

    facts = {"repo": args.repo, "pr": args.pr,
             "base_sha": args.base_sha, "head_sha": args.head_sha,
             "skipped": args.skipped, "no_result": args.no_result}

    sys.stdout.write(build_comment(reports, facts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
