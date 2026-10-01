"""Run the whole thing with one command.

    python -m prsentinel.pipeline before.py after.py
    python -m prsentinel.pipeline before.py after.py --name my_run
    python -m prsentinel.pipeline before.py after.py --ai-second-opinion
    python -m prsentinel.pipeline before.py after.py --reuse-tests

The steps, in order:

1. Look at the two versions of the module and find the functions that were
   added or changed. Functions that were removed are skipped, because there is
   nothing left to test.
2. Ask the AI to write tests for each of those functions, and save them under
   generated_tests/<name>/.
3. Run each generated test file against both versions of the module, and label
   every test.
4. For every test that fails on the new code, work out whether it is pointing
   at a real bug, is itself wrong, or cannot be trusted. This uses the plain
   rule classifier, which needs no AI.
5. Only if --ai-second-opinion is given, also ask the AI for its opinion on each
   failing test, and flag it when the two disagree. Without that flag this
   step makes no calls at all.
6. Print a report in plain words. The report says whether the tests were freshly
   generated or reused, and when they were reused it names the folder each file
   came from, so a saved report always says where its tests came from.
7. Save the same report to reports/<name>.md and reports/<name>.json.

Two flags change what happens:

--ai-second-opinion   also ask the AI about each failing test, and say when it
                      disagrees with the rule. Without it, no extra AI call is
                      made at all.
--reuse-tests         do not ask the AI for any new tests. Run the test files
                      already saved in generated_tests/<name>/. If a function
                      has no file there, the frozen copy in baselines/<name>/
                      is used instead, so this works on a fresh clone. With this
                      flag the whole run makes no AI calls, so the same tests
                      can be run again and compared. The report always says which
                      folder each test file came from.

One function failing does not stop the others. A failure to write a test, or a
failure to read one, is recorded and carried on from.

An older copy of a test file is never overwritten. The first is kept as .bak,
the next as .bak.2, then .bak.3, and so on.

The exit code is 0 whenever the pipeline itself ran, even when it found bugs,
because finding bugs is the job. It is non-zero only when the pipeline could
not do its work at all. A run stopped by --no-fallback, because the AI is out
for the day, has an exit code of its own, so it can never be mistaken for a
finished run.

Nothing here ever writes an API key or any other secret. The report holds
results only.
"""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from prsentinel import classifier as cl
from prsentinel import config
from prsentinel import llm_client
from prsentinel import mutation as mt
from prsentinel import repair
from prsentinel import test_generator as tg
from prsentinel import test_runner as tr
from prsentinel.diff_extractor import extract_changes_from_files

# Where generated tests and reports are kept.
GENERATED_DIR = "generated_tests"
REPORTS_DIR = "reports"

# The frozen copies we keep for comparison. --reuse-tests falls back to these
# when generated_tests has no file for a function, so the tool still works on a
# fresh clone where generated_tests does not exist.
BASELINES_DIR = "baselines"

# The file extension used when we keep an older copy of a generated test.
BACKUP_SUFFIX = ".bak"

# The counts we show for each function, in this order.
COUNT_LABELS = (tr.CATCHES_CHANGE, tr.TEST_WRONG_ON_BEFORE, tr.NO_SIGNAL, tr.ODD)

# The exit code used when --no-fallback stops the run because a provider is out
# for the day. It has its own number so it can never be mistaken for a broken
# run (1) or for the --repair + --reuse-tests refusal (2).
EXIT_DAILY_LIMIT = 6


# ---------------------------------------------------------------------------
# Step 2: writing the test files
# ---------------------------------------------------------------------------

def free_backup_path(path: Path) -> Path:
    """Find a backup name that is not taken yet.

    The first backup is called test_x.py.bak, the next one test_x.py.bak.2, then
    test_x.py.bak.3, and so on. We never write over an existing backup, because
    doing that is how an earlier version gets lost for good.
    """
    first = path.with_suffix(path.suffix + BACKUP_SUFFIX)
    if not first.exists():
        return first

    number = 2
    while True:
        numbered = first.with_name(first.name + f".{number}")
        if not numbered.exists():
            return numbered
        number += 1


def write_with_backup(path: Path, code: str):
    """Write a generated test file, keeping any older copy as a backup.

    Returns a pair: the backup path, or None if there was nothing to keep, and
    True if a backup was made. Nothing is ever deleted or overwritten.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    backup = None
    if path.is_file():
        backup = free_backup_path(path)
        shutil.copyfile(path, backup)

    path.write_text(code, encoding="utf-8")
    return backup, backup is not None


def find_saved_test(name, file_name) -> tuple:
    """Find a saved test file, preferring generated_tests over baselines.

    generated_tests/<name>/ holds whatever the last run wrote. baselines/<name>/
    holds the frozen copy we keep for comparison. We prefer the live one, and
    fall back to the frozen one when there is no live file for that function.

    This is what makes --reuse-tests work on a fresh clone, where the
    generated_tests folder does not exist at all.

    Returns the path and where it came from: "generated_tests", "baselines", or
    None if neither folder has it.
    """
    for folder_name, folder in ((GENERATED_DIR, Path(GENERATED_DIR) / name),
                                (BASELINES_DIR, Path(BASELINES_DIR) / name)):
        path = folder / file_name
        if path.is_file():
            return path, folder_name

    return None, None


def describe_test_source(folders) -> str:
    """Say where the test files came from, in one line for the report.

    A run can use both, if some functions had a live test file and others only
    had the frozen one. We name the folders so the reader knows which numbers
    they are looking at.

    folders is one folder name per test file we actually reused. Repeats are
    removed and the order is fixed, so the same run always reads the same way.
    """
    # Order the folders the same way every time, not in the order they happened
    # to be found, so two identical runs produce identical reports.
    order = [GENERATED_DIR, BASELINES_DIR]
    unique = [name for name in order if name in set(folders)]

    if not unique:
        return "reused"
    if len(unique) == 1:
        return f"reused from {unique[0]}"
    return "reused from " + " and ".join(unique)


def reuse_test_files(before_file, after_file, name) -> list:
    """Use the test files we already have, and ask nobody.

    This makes no call to any AI at all. It is what --reuse-tests does, so the
    same tests can be run again and the results compared.

    Returns the same shape of list as generate_test_files. A function we have no
    test file for anywhere is recorded as a failure, so it shows up in the
    report.
    """
    changes = extract_changes_from_files(before_file, after_file)
    outcomes = []

    for change in changes:
        function = change["name"]
        change_type = change["change_type"]

        if change_type not in tg.WANTED_CHANGE_TYPES:
            outcomes.append({"function": function, "change_type": change_type,
                             "path": None, "error": "",
                             "skipped": True, "backed_up": False,
                             "backup": "", "from_folder": ""})
            continue

        file_name = f"test_{tg.safe_file_name(function)}.py"
        path, from_folder = find_saved_test(name, file_name)

        if path is None:
            print(f"[prsentinel] no saved test for {function} in "
                  f"{GENERATED_DIR} or {BASELINES_DIR}")
            outcomes.append({"function": function, "change_type": change_type,
                             "path": None,
                             "error": "there is no saved test file to "
                                      f"reuse in {GENERATED_DIR} or "
                                      f"{BASELINES_DIR}",
                             "skipped": False, "backed_up": False,
                             "backup": "", "from_folder": ""})
            continue

        print(f"[prsentinel] reusing the saved test for {function} "
              f"(from {from_folder}): {path}")
        outcomes.append({"function": function, "change_type": change_type,
                         "path": str(path), "error": "",
                         "skipped": False, "backed_up": False, "backup": "",
                         "from_folder": from_folder})

    return outcomes


def generate_test_files(before_file, after_file, name) -> list:
    """Write one test file per changed function. Uses the AI.

    Returns a list of dictionaries, one per function we tried. Each has
    "function", "path" (None if it failed) and "error" ("" if it worked).
    A failure here does not stop the next function.
    """
    changes = extract_changes_from_files(before_file, after_file)
    folder = Path(GENERATED_DIR) / name
    outcomes = []

    for change in changes:
        function = change["name"]
        change_type = change["change_type"]

        # Only added or changed functions are worth testing. A removed
        # function has nothing left to call.
        if change_type not in tg.WANTED_CHANGE_TYPES:
            print(f"[prsentinel] skipping {function}: it was {change_type}, "
                  f"not added or changed.")
            outcomes.append({"function": function, "change_type": change_type,
                             "path": None, "error": "",
                             "skipped": True, "backed_up": False})
            continue

        print(f"[prsentinel] asking for tests for {function} ({change_type})...")
        try:
            code = tg.generate_tests(change)
        except llm_client.DailyLimitReached:
            # Out for the day. With --no-fallback this ends the whole run, so it
            # must not be mistaken for one function that failed to produce tests.
            raise
        except Exception as error:
            # One function failing must not lose us the others.
            print(f"[prsentinel] could not write tests for {function}: {error}")
            outcomes.append({"function": function, "change_type": change_type,
                             "path": None, "error": str(error),
                             "skipped": False, "backed_up": False})
            continue
        warn_if_gemini()

        path = folder / f"test_{tg.safe_file_name(function)}.py"
        backup, kept_old = write_with_backup(path, code)

        if backup is not None:
            print(f"[prsentinel] kept the old copy as {backup.name}")
        print(f"[prsentinel] saved {path}")

        outcomes.append({
            "function": function,
            "change_type": change_type,
            "path": str(path),
            "error": "",
            "skipped": False,
            "backed_up": kept_old,
            "backup": backup.name if backup else "",
        })

    return outcomes


# ---------------------------------------------------------------------------
# Steps 3 to 5: running the tests and judging the failures
# ---------------------------------------------------------------------------

def run_all_three(before_file, after_file, test_file):
    """Run a test file on both versions and then rerun it on the new one.

    This is done once per test file, not once per test, because every test in
    the file shares the same three runs. Running them again for each test would
    mean starting pytest over and over for no new information.

    Returns the three runs, in the order before, after, rerun.
    """
    before_run = tr.run_tests(before_file, test_file)
    after_run = tr.run_tests(after_file, test_file)
    rerun_run = tr.rerun_failures(after_file, test_file)
    return before_run, after_run, rerun_run


def judge_one_test(before_run, after_run, rerun_run,
                   before_file, after_file, test_file, test_name,
                   label="", ai_second_opinion=False) -> dict:
    """Work out what one failing test means.

    Takes runs that have already happened, so nothing is run again here. The
    rule classifier does the deciding. If asked, the AI is asked for a second
    opinion and any disagreement is recorded.

    label is the runner's own label for this test. It is only carried along so
    the report can say what kind of test this was.
    """
    evidence = cl.build_evidence(before_run, after_run, rerun_run,
                                 before_file, after_file, test_file,
                                 test_name=test_name)

    verdict = cl.rule_classify(evidence)
    result = {
        "test": test_name,
        "label": label,
        "verdict": verdict["label"],
        "reason": verdict["reason"],
        "before": evidence["before_result"],
        "after": evidence["after_result"],
        "rerun": evidence["rerun"],
    }

    if ai_second_opinion:
        # Only reached when the flag is on. Without it there is no extra call.
        second = cl.llm_classify(evidence, cl.MODE_FULL)
        warn_if_gemini()
        result["ai_verdict"] = second["label"]
        result["ai_confidence"] = second["confidence"]
        result["ai_reason"] = second["reason"]
        result["ai_agrees"] = (second["label"] == verdict["label"])
    else:
        result["ai_verdict"] = ""
        result["ai_confidence"] = ""
        result["ai_reason"] = ""
        result["ai_agrees"] = None

    return result


def unknown_judgement(row, error):
    """A placeholder for a test we could not work out, so we still list it."""
    return {
        "test": row["name"],
        "label": row["label"],
        "verdict": "UNKNOWN",
        "reason": f"we could not work this out: {error}",
        "before": row["before"],
        "after": row["after"],
        "rerun": {},
        "ai_verdict": "",
        "ai_confidence": "",
        "ai_reason": "",
        "ai_agrees": None,
    }


def check_one_file(before_file, after_file, test_file,
                   ai_second_opinion=False) -> dict:
    """Run one generated test file on both versions and judge the failures."""
    rows = tr.evaluate_tests(before_file, after_file, test_file)

    counts = {label: 0 for label in COUNT_LABELS}
    for row in rows:
        counts[row["label"]] = counts.get(row["label"], 0) + 1

    # Two kinds of test are worth judging.
    #
    # A test that fails on the new code, because something about the change
    # matters to it. That includes every TEST_WRONG_ON_BEFORE row, which by
    # definition fails on the new code too, and which we still want a verdict
    # on so we can say plainly that the test itself is the problem.
    #
    # A test that fails on the old code and passes on the new one is ODD. We do
    # not judge it, we just point at it, because a rule cannot tell whether the
    # test is wrong or the change simply added behaviour.
    to_judge = [row for row in rows
                if row["after"] in (tr.FAILED, tr.TEST_ERROR)
                or row["label"] == tr.TEST_WRONG_ON_BEFORE]
    odd = [row for row in rows if row["label"] == tr.ODD]

    judgements = []

    if to_judge:
        # One set of runs, shared by every test in this file.
        before_run, after_run, rerun_run = run_all_three(before_file,
                                                        after_file,
                                                        test_file)
        for row in to_judge:
            print(f"[prsentinel] judging {row['display']}...")
            try:
                judgements.append(
                    judge_one_test(before_run, after_run, rerun_run,
                                   before_file, after_file, test_file,
                                   row["name"], label=row["label"],
                                   ai_second_opinion=ai_second_opinion))
            except llm_client.DailyLimitReached:
                # Out for the day. This ends the whole run rather than skipping
                # one judgement.
                raise
            except Exception as error:
                # A judgement we cannot make is worth reporting, not worth
                # crashing the whole run over.
                print(f"[prsentinel] could not judge {row['display']}: {error}")
                judgements.append(unknown_judgement(row, error))

    return {
        "test_file": Path(test_file).name,
        "counts": counts,
        "judgements": judgements,
        "needs_a_look": [row["name"] for row in odd],
    }


def check_all_files(before_file, after_file, outcomes, ai_second_opinion) -> list:
    """Run every generated test file we managed to write."""
    results = []
    for outcome in outcomes:
        if outcome["path"] is None:
            continue
        results.append(check_one_file(before_file, after_file, outcome["path"],
                                      ai_second_opinion))
    return results


# ---------------------------------------------------------------------------
# Step 5b: repairing a test that was judged to be the wrong test
# ---------------------------------------------------------------------------
# Only a test judged to be the wrong test is ever repaired. A test judged to be
# pointing at a real bug is never touched, because repairing it would hide the
# bug, and a test judged to be flaky is never touched, because it is not wrong.
#
# A repair is a candidate file, never an edit. It is written to a folder of its
# own, run there, and copied over the real file only when it is accepted. So a
# repair that fails, or that damages another test, or that crashes, leaves the
# real file exactly as it was.

def labelled_rows(before_run, after_run) -> list:
    """Label every test from runs we already have.

    The same rule the runner uses, read off runs that have already happened
    rather than running the file twice more to find out.
    """
    names = list(before_run["tests"].keys()) or list(after_run["tests"].keys())

    rows = []
    for name in names:
        before_result = before_run["tests"].get(name, tr.TEST_ERROR)
        after_result = after_run["tests"].get(name, tr.TEST_ERROR)
        rows.append({
            "name": name,
            "before": before_result,
            "after": after_result,
            "label": tr.label_for(before_result, after_result),
        })
    return rows


def suite_weakened(baseline_rows, candidate_rows, before_run) -> bool:
    """True when a candidate file is worse than the file it would replace.

    Two things count, and either one throws the whole candidate away:

    - a test that used to catch the change no longer catches it, so a real bug
      would slip past a test that was working;
    - a test that used to pass on the old code now fails on it, so the file is
      now wrong about behaviour it used to get right.

    It is checked across the whole file, not only the test being repaired,
    because a repair rewrites the whole file and can damage its neighbours.
    """
    candidate_by_name = {row["name"]: row for row in candidate_rows}

    for row in baseline_rows:
        new = candidate_by_name.get(row["name"])

        if row["label"] == tr.CATCHES_CHANGE:
            if new is None or new["label"] != tr.CATCHES_CHANGE:
                return True

        if row["before"] in (tr.PASSED, tr.SKIPPED):
            new_before = before_run["tests"].get(row["name"], tr.TEST_ERROR)
            if new_before not in (tr.PASSED, tr.SKIPPED):
                return True

    return False


def failure_message_for(rows, test_name) -> str:
    """The message the failing test printed, from the rows we already have."""
    for row in rows:
        if row["name"] == test_name:
            return row.get("detail_full") or row.get("detail") or ""
    return ""


def test_candidate(before_file, after_file, original_test_file, candidate_text,
                   test_name, baseline_rows, work_dir) -> dict:
    """Run one candidate repair somewhere harmless and say what it did.

    Returns whether it passes on the old code, whether it weakened the file, and
    the verdict for the test it was asked to fix. Nothing is written to the real
    test file here. That only happens if the caller accepts the candidate.
    """
    candidate_path = Path(work_dir) / Path(original_test_file).name
    candidate_path.write_text(candidate_text, encoding="utf-8")

    before_run, after_run, rerun_run = run_all_three(before_file, after_file,
                                                     candidate_path)
    rows = labelled_rows(before_run, after_run)

    before_result = before_run["tests"].get(test_name, tr.TEST_ERROR)
    label = next((row["label"] for row in rows
                  if row["name"] == test_name), "")

    verdict = cl.rule_classify(
        cl.build_evidence(before_run, after_run, rerun_run,
                          before_file, after_file, candidate_path, test_name))

    # rule_classify answers one question: what does this failing test mean? It
    # has three answers and none of them is "this test is fine now", so a
    # candidate whose test passes on both versions falls through to its last
    # resort and comes back as BAD_TEST. The runner's label says what actually
    # happened, so when the test no longer fails on the old code, say that
    # instead of calling a corrected test wrong. A flaky candidate is left
    # alone here so the caller can still see it and throw it away.
    if (label == tr.NO_SIGNAL
            and before_result in (tr.PASSED, tr.SKIPPED)
            and verdict["label"] != cl.FLAKY):
        verdict = {
            "label": tr.NO_SIGNAL,
            "reason": ("After the repair it passes on the old code and on the "
                       "new code, so it no longer says anything about the "
                       "change."),
        }

    return {
        "passes_on_before": before_result in (tr.PASSED, tr.SKIPPED),
        "weakened": suite_weakened(baseline_rows, rows, before_run),
        "verdict": verdict["label"],
        "reason": verdict["reason"],
        "label": label,
    }


def repair_one_test(before_file, after_file, test_file, change, judgement,
                    baseline_rows, budget, ask) -> dict:
    """Try to correct one test that was judged to be the wrong test.

    A repair counts as done when the corrected test passes on the old code and
    is no longer judged to be the wrong test. A repair that damages another test
    is thrown away and tried again, with a line in the prompt saying so.

    Returns a record of what happened. Nothing is returned with the original
    file changed unless the repair was accepted.
    """
    test_name = judgement["test"]
    failure_message = failure_message_for(baseline_rows, test_name)

    record = {
        "function": change["name"],
        "test_file": Path(test_file).name,
        "test": test_name,
        "attempts": 0,
        "outcome": "unrepaired BAD_TEST",
        "final_verdict": judgement["verdict"],
        "final_reason": judgement["reason"],
        "final_label": judgement["label"],
    }

    last_was_weakened = False
    every_attempt_weakened = True

    for attempt in range(1, config.MAX_REPAIR_ATTEMPTS + 1):
        if budget["calls"] >= budget["limit"]:
            record["outcome"] = "not attempted, repair budget reached"
            return record

        budget["calls"] += 1
        record["attempts"] = attempt

        print(f"[prsentinel] repairing {test_name} (attempt {attempt} of "
              f"{config.MAX_REPAIR_ATTEMPTS})...")

        try:
            candidate_text = repair.repair_test(
                change, Path(test_file).read_text(encoding="utf-8"),
                test_name, failure_message, attempt,
                weakened_before=last_was_weakened, ask=ask)
        except llm_client.DailyLimitReached:
            # Out for the day. With --no-fallback this ends the whole run, so it
            # must not be treated as one attempt that came back empty.
            raise
        except Exception as error:
            # A reply with no code in it, or a call that failed. That is one
            # used attempt, and the next one may do better.
            print(f"[prsentinel] attempt {attempt} for {test_name} gave no "
                  f"usable code: {error}")
            every_attempt_weakened = False
            last_was_weakened = False
            continue
        warn_if_gemini()

        try:
            result = test_candidate(before_file, after_file, test_file,
                                    candidate_text, test_name, baseline_rows,
                                    budget["work_dir"])
        except Exception as error:
            # The candidate could not even be run. That is a used attempt, and
            # the real file is untouched, which is the important part.
            print(f"[prsentinel] attempt {attempt} for {test_name} could not "
                  f"be run: {error}")
            every_attempt_weakened = False
            last_was_weakened = False
            continue

        # A repair is kept when the corrected test now passes on the old code
        # and is no longer the runner's "wrong on the old code" case, the file
        # is not weaker, and the test is not flaky. rule_classify cannot say
        # "this test is fine now", so the runner's label is what decides whether
        # the test stopped being wrong; the classifier is only used to catch a
        # candidate that turned the test flaky.
        accepted = (result["passes_on_before"]
                    and result["label"] != tr.TEST_WRONG_ON_BEFORE
                    and result["verdict"] != cl.FLAKY
                    and not result["weakened"])

        if accepted:
            # Only now is the real file touched. The backup is made here, at the
            # moment of acceptance, so a rejected repair never makes one.
            backup, kept_old = write_with_backup(Path(test_file), candidate_text)
            if backup is not None:
                print(f"[prsentinel] kept the old copy as {backup.name}")
            record["outcome"] = "repaired"
            record["final_verdict"] = result["verdict"]
            record["final_reason"] = result["reason"]
            record["final_label"] = result["label"]
            record["backup"] = backup.name if backup else ""
            print(f"[prsentinel] {test_name} was corrected and now says "
                  f"{result['verdict']}.")
            return record

        if result["weakened"]:
            # Its own test may be fixed, but it broke a neighbour. Thrown away,
            # and the next attempt is told what went wrong.
            print(f"[prsentinel] attempt {attempt} for {test_name} weakened "
                  f"the rest of the file, so it was thrown away.")
            last_was_weakened = True
        else:
            print(f"[prsentinel] attempt {attempt} for {test_name} did not "
                  f"fix it: it is still {result['verdict']}.")
            last_was_weakened = False
            every_attempt_weakened = False

    if every_attempt_weakened and record["attempts"]:
        record["outcome"] = "weakened"

    record["backup"] = record.get("backup", "")
    return record


def repair_bad_tests(before_file, after_file, outcomes, results, ask=None) -> list:
    """Repair every test judged to be the wrong test, one at a time.

    The budget of calls is shared across the whole run, so a file with many
    wrong tests cannot spend more than the setting allows.

    Returns one record per test that was considered, in a fixed order.
    """
    if ask is None:
        ask = repair.ask_llm

    changes = {change["name"]: change
               for change in extract_changes_from_files(before_file, after_file)}

    paired = list(zip([o for o in outcomes if o["path"]], results))
    budget = {"calls": 0, "limit": config.MAX_REPAIR_CALLS_PER_RUN,
              "work_dir": ""}
    records = []

    for outcome, result in paired:
        wrong = [j for j in result["judgements"]
                 if j["verdict"] == cl.BAD_TEST]
        if not wrong:
            continue

        change = changes.get(outcome["function"])
        if change is None:
            # No code to show the writer, so there is nothing to repair with.
            for judgement in wrong:
                records.append({
                    "function": outcome["function"],
                    "test_file": Path(outcome["path"]).name,
                    "test": judgement["test"],
                    "attempts": 0,
                    "outcome": "unrepaired BAD_TEST",
                    "final_verdict": judgement["verdict"],
                    "final_reason": judgement["reason"],
                    "final_label": judgement["label"],
                    "backup": "",
                })
            continue

        baseline_rows = tr.evaluate_tests(before_file, after_file,
                                          outcome["path"])

        # A folder of its own, so a candidate is never run in place. Removed
        # afterwards whether or not anything worked.
        budget["work_dir"] = tempfile.mkdtemp(prefix="prsentinel_repair_")
        try:
            for judgement in wrong:
                record = repair_one_test(before_file, after_file,
                                         outcome["path"], change, judgement,
                                         baseline_rows, budget, ask)
                records.append(record)

                judgement["repair"] = {
                    "attempts": record["attempts"],
                    "outcome": record["outcome"],
                    "final_verdict": record["final_verdict"],
                    "final_label": record["final_label"],
                }
                if record["outcome"] == "repaired":
                    # The test now says something different, so the report says
                    # what it says now rather than what the old file said.
                    judgement["verdict"] = record["final_verdict"]
                    judgement["reason"] = record["final_reason"]
                    judgement["label"] = record["final_label"]
        finally:
            shutil.rmtree(budget["work_dir"], ignore_errors=True)
            budget["work_dir"] = ""

    return records


# ---------------------------------------------------------------------------
# Step 5c: mutation testing, when --mutation was given
# ---------------------------------------------------------------------------

def measure_mutation(before_file, outcomes) -> list:
    """Check how many faults each changed function's tests catch.

    Only a modified function has an old version to mutate, so an added or a
    removed function is listed as not defined instead. Every mutant is run
    through the ordinary test runner, which keeps the child environment
    allow-listed and writes only to a temporary folder.
    """
    results = []
    for outcome in outcomes:
        function = outcome["function"]
        change_type = outcome["change_type"]

        if change_type != "modified":
            results.append({
                "function": function,
                "change_type": change_type,
                "defined": False,
                "reason": "not defined (no old version)",
            })
            continue

        if outcome["path"] is None:
            results.append({
                "function": function,
                "change_type": change_type,
                "defined": False,
                "reason": "not defined (no test file was produced)",
            })
            continue

        print(f"[prsentinel] checking the tests for {function} against small "
              f"deliberate faults...")
        measured = mt.run_mutation(before_file, outcome["path"], function)
        measured["change_type"] = change_type

        if measured.get("capped"):
            print(f"[prsentinel] note: {function} offered {measured['found']} "
                  f"mutants, but only the first {measured['cap']} were used "
                  f"(the cap).")
        results.append(measured)

    return results


# ---------------------------------------------------------------------------
# Step 6: the report
# ---------------------------------------------------------------------------

def build_summary_line(report: dict) -> str:
    """Write the one plain sentence that says what we found.

    Only tests that caught the change AND were judged a real bug are counted,
    because a test that was itself wrong is not evidence of a bug. A wrong test
    that the repair loop corrected is a second, separate result, so it is added
    to the same sentence rather than mixed into the bug count.
    """
    parts = []
    for function in report["functions"]:
        # Counted row by row, not per function, so only a test that both caught
        # the change and was judged a real bug is counted. A test that was
        # itself wrong is not evidence of a bug.
        real_bugs = sum(1 for judgement in function["judgements"]
                        if judgement["label"] == tr.CATCHES_CHANGE
                        and judgement["verdict"] == cl.REAL_BUG)
        if real_bugs == 0:
            continue

        name = function["function"]
        if real_bugs == 1:
            parts.append(f"1 test points to a real bug in {name}")
        else:
            parts.append(f"{real_bugs} tests point to a real bug in {name}")

    # A repair that was accepted rewrote a test the writer had got wrong. That
    # is worth saying out loud. It is kept out of the bug count above, because a
    # corrected test says something about the test, not about the code.
    repaired = sum(1 for item in report.get("repairs") or []
                   if item["outcome"] == "repaired")
    if repaired == 1:
        parts.append("1 wrong test was corrected")
    elif repaired > 1:
        parts.append(f"{repaired} wrong tests were corrected")

    if not parts:
        return "No test points to a real bug in the code."

    sentence = "; ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def make_report(before_file, after_file, name, outcomes, results,
                tests_source="generated", repairs=None,
                repair_tests=False, fallback_allowed=True,
                gemini_answers=0, mutation=None) -> dict:
    """Put everything we found into one dictionary, ready to save.

    repair_tests is whether --repair was given, which is not the same question
    as whether any repair happened. A run can have repair on and nothing to
    repair, so the report says which of the two it was rather than making the
    reader guess from an empty list.

    fallback_allowed is the setting, not what happened: True means the run was
    allowed to fall back to the second provider (the default), False means
    --no-fallback was given. gemini_answers is how many answers actually came
    from that fallback provider, so a reader can tell the two apart.

    mutation is None unless --mutation was given. Only then does the report
    grow a mutation section, so an ordinary run reads exactly as it did before.
    """
    functions = []
    for outcome, result in zip([o for o in outcomes if o["path"]],
                               results):
        functions.append({
            "function": outcome["function"],
            "change_type": outcome["change_type"],
            "test_file": result["test_file"],
            "from_folder": outcome.get("from_folder", ""),
            "counts": result["counts"],
            "judgements": result["judgements"],
            "needs_a_look": result["needs_a_look"],
        })

    report = {
        "name": name,
        "before": Path(before_file).name,
        "after": Path(after_file).name,
        "tests_source": tests_source,
        "functions": functions,
        "generation_failed": [
            {"function": o["function"], "error": o["error"]}
            for o in outcomes if o["path"] is None and not o["skipped"]
        ],
        "skipped": [
            {"function": o["function"], "change_type": o["change_type"]}
            for o in outcomes if o["skipped"]
        ],
        "repairs": list(repairs or []),
        "repair": bool(repair_tests),
        "fallback": bool(fallback_allowed),
        "gemini_answers": int(gemini_answers),
    }
    # Only a run that asked for mutation testing carries the section, so an
    # ordinary saved report is byte for byte what it always was.
    if mutation is not None:
        report["mutation"] = list(mutation)
    report["summary"] = build_summary_line(report)
    return report


def format_mutation(mutation) -> list:
    """Write the mutation section: do the tests really catch a fault?

    Only ever reached when --mutation was given. A function with no old version
    has nothing to mutate, so it is listed as not defined rather than scored.
    """
    lines = []
    lines.append("--- Mutation (do the tests really catch a fault?) ---")
    lines.append("  A mutant is a copy of the changed function with one small")
    lines.append("  deliberate fault, such as + changed to - or < changed to")
    lines.append("  <=. If a test fails on it the mutant is killed; if every")
    lines.append("  test still passes it survived. Some survivors may be")
    lines.append("  equivalent mutants, which no test could ever kill, so the")
    lines.append("  score is a lower bound, not an exact grade.")

    for item in mutation:
        lines.append("")
        lines.append(f"  {item['function']}  ({item.get('change_type', '')})")

        if not item.get("defined"):
            lines.append("    mutation score  : not defined")
            lines.append(f"    reason          : {item.get('reason', '')}")
            continue

        lines.append(f"    version mutated : {item.get('version', '')} "
                     "(the version the tests pass on)")
        lines.append(f"    mutants found   : {item['found']}")
        if item.get("capped"):
            lines.append(f"    note            : only the first {item['cap']} "
                         "were used (the cap)")
        lines.append(f"    killed          : {item['killed']}")
        lines.append(f"    survived        : {item['survived']}")
        lines.append(f"    equivalent      : {item['equivalent']}")
        lines.append(f"    timed out       : {item['timed_out']}")
        lines.append(f"    could not run   : {item['could_not_run']}")

        if item.get("score") is None:
            lines.append("    mutation score  : not defined")
            lines.append(f"    reason          : {item.get('reason', '')}")
        else:
            counted = item["killed"] + item["survived"]
            percent = round(item["score"] * 100)
            lines.append(f"    mutation score  : {percent}% "
                         f"({item['killed']} of {counted})")

        duds = [t["test"] for t in item.get("tests", []) if t.get("dud")]
        if duds:
            lines.append("    tests that killed nothing (possible duds):")
            for name in duds:
                lines.append(f"      {name}")

    return lines


def format_report(report: dict) -> str:
    """Write the whole report out in plain words, for the screen."""
    lines = []
    lines.append("=" * 72)
    lines.append(f"PRSentinel report for {report['name']}")
    lines.append("=" * 72)
    lines.append(f"Old file: {report['before']}")
    lines.append(f"New file: {report['after']}")
    lines.append(f"Tests: {report.get('tests_source', 'generated')}")
    lines.append(f"repair: {'on' if report.get('repair') else 'off'}")
    lines.append(f"fallback: {'on' if report.get('fallback', True) else 'off'}")
    lines.append(f"answers from Gemini: {report.get('gemini_answers', 0)}")
    lines.append("")

    if not report["functions"]:
        lines.append("No test files were produced, so there is nothing to report.")
        lines.append("")
        return "\n".join(lines)

    lines.append("--- Per function ---")
    for function in report["functions"]:
        lines.append("")
        lines.append(f"{function['function']}  ({function['change_type']})")
        lines.append(f"  test file: {function['test_file']}")
        if function.get("from_folder"):
            lines.append(f"  came from: {function['from_folder']}")
        for label in COUNT_LABELS:
            lines.append(f"  {label:<24} {function['counts'].get(label, 0)}")

        if not function["judgements"] and not function["needs_a_look"]:
            lines.append("  No test failed on the new code, so there is "
                         "nothing to judge.")
            continue

        if function["judgements"]:
            lines.append("  Tests we judged:")
            for judgement in function["judgements"]:
                lines.append(f"    {judgement['test']}  "
                             f"({judgement['label']})")
                lines.append(f"      verdict : {judgement['verdict']}")
                lines.append(f"      why     : {judgement['reason']}")

                if judgement["ai_verdict"]:
                    mark = "agrees" if judgement["ai_agrees"] else "DISAGREES"
                    lines.append(f"      AI says : {judgement['ai_verdict']} "
                                 f"({judgement['ai_confidence']}) - {mark}")
                    lines.append(f"                {judgement['ai_reason']}")

        if function["needs_a_look"]:
            lines.append("  Tests that need a human look:")
            for name in function["needs_a_look"]:
                lines.append(f"    {name} - needs a human look "
                             "(fails on the old code, passes on the new one)")

    if report.get("mutation") is not None:
        lines.append("")
        lines.extend(format_mutation(report["mutation"]))

    if report.get("repairs") or report.get("repair"):
        lines.append("")
        lines.append("--- Repairs ---")
        lines.append("  A test judged to be the wrong test was sent back to the")
        lines.append("  writer to be corrected. Nothing was changed unless the")
        lines.append("  corrected test passed on the old code and left the rest of")
        lines.append("  the file as strong as it was.")
        if not report.get("repairs"):
            # Repair was on and every test was fine, so the section is still
            # shown, with zeros. A run that says nothing would leave a reader
            # unable to tell "nothing needed repair" from "repair was off".
            lines.append("  No test was judged to be the wrong test, so there was")
            lines.append("  nothing to repair.")
        counted = {"repaired": 0, "unrepaired BAD_TEST": 0, "weakened": 0,
                   "not attempted, repair budget reached": 0}
        for item in report.get("repairs") or []:
            counted[item["outcome"]] = counted.get(item["outcome"], 0) + 1
            lines.append("")
            lines.append(f"  {item['function']} / {item['test']}")
            lines.append(f"    attempts    : {item['attempts']}")
            lines.append(f"    outcome     : {item['outcome']}")
            lines.append(f"    final label : {item['final_verdict']}")
            if item.get("final_label"):
                lines.append(f"    runner said : {item['final_label']}")
        lines.append("")
        lines.append(f"  repaired: {counted['repaired']}   "
                     f"unrepaired: {counted['unrepaired BAD_TEST']}   "
                     f"weakened: {counted['weakened']}")

    if report["generation_failed"]:
        lines.append("")
        lines.append("--- Functions we could not write tests for ---")
        for item in report["generation_failed"]:
            lines.append(f"  {item['function']}: {item['error']}")

    if report["skipped"]:
        lines.append("")
        lines.append("--- Functions we skipped ---")
        for item in report["skipped"]:
            lines.append(f"  {item['function']}: {item['change_type']}")

    lines.append("")
    lines.append("--- Summary ---")
    lines.append(report["summary"])
    return "\n".join(lines)


def print_report(report: dict) -> None:
    """Print the report, with a blank line either side."""
    print()
    print(format_report(report))


# ---------------------------------------------------------------------------
# Step 7: saving
# ---------------------------------------------------------------------------

def save_report(report: dict, reports_dir: str = REPORTS_DIR) -> dict:
    """Write the report to reports/<name>.md and reports/<name>.json.

    Returns the two paths. Nothing secret is ever written, because the report
    only holds results and names.
    """
    folder = Path(reports_dir)
    folder.mkdir(parents=True, exist_ok=True)

    markdown_path = folder / f"{report['name']}.md"
    json_path = folder / f"{report['name']}.json"

    markdown_path.write_text(format_report(report) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return {"markdown": str(markdown_path), "json": str(json_path)}


# ---------------------------------------------------------------------------
# Stopping when the AI is out for the day, and naming the fallback
# ---------------------------------------------------------------------------
# With --no-fallback, a provider that is out for the whole day ends the run
# instead of quietly switching models. Half a run is not a smaller run: the
# report it would write is missing the functions and tests it never reached, and
# it would look exactly like a finished one. So we print a loud notice and stop.
#
# The notice has the same shape as the one classifier_eval prints, because both
# runs share the same danger: numbers taken from a run that did not finish.

class DailyLimitStop(RuntimeError):
    """The run was stopped because the AI is out for the day."""


# Whether we have already warned that an answer came from Gemini. Said once, the
# first time it happens, so it cannot be scrolled past unnoticed.
GEMINI_ANNOUNCED = False

# How many answers this run got from Gemini, the fallback provider. Reset at the
# start of every run, so the number belongs to one run and not to the process.
GEMINI_ANSWERS = 0


def reset_gemini_warning():
    """Start the once-per-run warning and the Gemini count again from nothing."""
    global GEMINI_ANNOUNCED, GEMINI_ANSWERS
    GEMINI_ANNOUNCED = False
    GEMINI_ANSWERS = 0


def warn_if_gemini():
    """Count the answer, and say clearly the first time it came from Gemini.

    Reads the provider name ask_llm leaves behind after every call. A Groq
    answer, a failed call, and a run that asked no AI at all all leave it empty
    or set to Groq, so nothing is counted and nothing is printed for those.

    Every AI call in the pipeline calls this once, so the count is the number of
    answers this run was built on that came from the fallback model.
    """
    global GEMINI_ANNOUNCED, GEMINI_ANSWERS
    if llm_client.LAST_PROVIDER != "Gemini":
        return

    GEMINI_ANSWERS += 1
    if GEMINI_ANNOUNCED:
        return

    GEMINI_ANNOUNCED = True
    print()
    print("!" * 70)
    print("! AN ANSWER CAME FROM GEMINI, THE FALLBACK PROVIDER.")
    print("! Groq could not answer every question, so this run mixes two")
    print("! different models. Treat its output as a mixture, not as a run")
    print("! that came from Groq alone.")
    print("!" * 70)
    print()


def print_stopped_on_daily_limit(error):
    """Say clearly that the run stopped early and its output means nothing.

    A run that dies half way has most of a report in it, and that report looks
    exactly like a finished one. Without this, someone could read results off a
    run that never finished and believe them.
    """
    print()
    print("!" * 70)
    print("! THE RUN STOPPED EARLY. A PROVIDER IS OUT FOR THE DAY.")
    print("!")
    print(f"! {error}")
    print("!")
    print(f"! Model calls completed before the stop: {llm_client.CALLS_MADE}")
    print("!")
    print("! No results should be trusted. The run did not finish, so the")
    print("! report it would have written is missing every function and test it")
    print("! never reached, and no report was saved.")
    print("!")
    print("! Wait for the daily allowance to reset and run it again.")
    print("!" * 70)
    print()


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------

def run_pipeline(before_file, after_file, name=None,
                 ai_second_opinion=False, reuse_tests=False,
                 repair_tests=False, ask=None,
                 fallback_allowed=True, mutation=False) -> dict:
    """Do all seven steps and return the report.

    With reuse_tests we skip writing tests and use the ones already saved. That
    makes no call to any AI. The report says which of the two happened, so a
    saved report always says where its tests came from.

    With repair_tests, any test judged to be the wrong test is sent back to the
    writer to be corrected, then checked again. That only ever happens to a test
    judged to be the wrong test; a real bug and a flaky test are left alone.

    ask is the function used to reach the AI for a repair. It is a parameter so
    a test can put a fake in its place.

    fallback_allowed is carried into the report, so a saved report can say
    whether the run was allowed to fall back to the second provider. It is the
    setting, not whether a fallback actually happened.

    With mutation, every changed function is checked against small deliberate
    faults to see how many of them the tests catch. That asks no AI at all, and
    it adds a mutation section to the report.
    """
    before_path = Path(before_file)
    after_path = Path(after_file)

    if name is None:
        # The folder the old file sits in, which is how the examples are named.
        name = before_path.resolve().parent.name

    print(f"[prsentinel] pipeline for {name}")

    # The fallback warning is once per run, so start clean. A new run also starts
    # with no provider named, so a run that asks no AI cannot look like it got
    # its answers from the fallback.
    reset_gemini_warning()
    llm_client.LAST_PROVIDER = ""

    # The AI can run out for the day. With --no-fallback that stops the whole
    # run here: the notice is printed once and nothing is saved, because a report
    # that covers only the functions reached first is not a finished report.
    try:
        # Steps 1 and 2.
        if reuse_tests:
            print("[prsentinel] --reuse-tests was given, so no AI is asked for "
                  "new tests. Using the saved ones.")
            outcomes = reuse_test_files(before_path, after_path, name)
        else:
            outcomes = generate_test_files(before_path, after_path, name)

        # Steps 3, 4 and 5.
        results = check_all_files(before_path, after_path, outcomes,
                                  ai_second_opinion)

        # Step 5b. Only when --repair was given. Repairs run after the first
        # judgement, because it is that judgement that decides which tests are
        # wrong.
        repairs = []
        if repair_tests:
            print("[prsentinel] --repair was given, so any test judged to be "
                  "the wrong test will be corrected and checked again.")
            repairs = repair_bad_tests(before_path, after_path, outcomes,
                                       results, ask=ask)
    except llm_client.DailyLimitReached as error:
        print_stopped_on_daily_limit(error)
        raise DailyLimitStop(error)

    # Step 5c. Only when --mutation was given. This asks no AI at all: it makes
    # small faults in each changed function and checks whether the tests notice.
    mutation_results = None
    if mutation:
        print("[prsentinel] --mutation was given, so each changed function will "
              "be checked against small deliberate faults.")
        mutation_results = measure_mutation(before_path, outcomes)

    # Step 6. When we reused tests, the report names the folder each file came
    # from, so a saved report always says whether it was a live file or a
    # frozen baseline.
    if reuse_tests:
        tests_source = describe_test_source(
            [o["from_folder"] for o in outcomes if o.get("from_folder")])
    else:
        tests_source = "generated"

    report = make_report(before_path, after_path, name, outcomes, results,
                         tests_source=tests_source, repairs=repairs,
                         repair_tests=repair_tests,
                         fallback_allowed=fallback_allowed,
                         gemini_answers=GEMINI_ANSWERS,
                         mutation=mutation_results)
    print_report(report)

    # Step 7.
    saved = save_report(report)
    print()
    print(f"[prsentinel] saved the report to {saved['markdown']}")
    print(f"[prsentinel] saved the full data to {saved['json']}")

    return report


def main() -> int:
    """Let us run this from the terminal."""
    parser = argparse.ArgumentParser(
        description="Generate tests for a changed module, run them, and say "
                    "what they found.")
    parser.add_argument("before_file", help="path to the old version of the module")
    parser.add_argument("after_file", help="path to the new version of the module")
    parser.add_argument("--name", default=None,
                        help="folder name to use under generated_tests and "
                             "reports. Defaults to the folder the old file is in.")
    parser.add_argument("--ai-second-opinion", action="store_true",
                        help="also ask the AI what it thinks of each failing "
                             "test, and flag any disagreement with the rule")
    parser.add_argument("--reuse-tests", action="store_true",
                        help="do not ask the AI for new tests. Use the test "
                             "files already in generated_tests/<name>/, or the "
                             "frozen ones in baselines/<name>/ when there is no "
                             "live file for a function. Makes no AI calls at all.")
    parser.add_argument("--repair", action="store_true",
                        help="when a failing test is judged to be the wrong "
                             "test, ask the writer to correct that test, then "
                             "check it again. Only ever touches a test judged "
                             "to be the wrong test. Off by default.")
    parser.add_argument("--no-fallback", action="store_true",
                        help="do not fall back to the second provider. If a "
                             "provider runs out for the day, stop the whole run "
                             "and say so, because results made part from one "
                             "model and part from another are not results. "
                             "Default is off, so we fall back as usual.")
    parser.add_argument("--mutation", action="store_true",
                        help="also check how many small deliberate faults in "
                             "each changed function the tests catch. This asks "
                             "no AI. Off by default, so an ordinary run reads "
                             "exactly as it did before.")
    args = parser.parse_args()

    # Repaired tests are written for the code that is running, so they cannot be
    # combined with the frozen baseline files. Refused before anything happens,
    # so this costs nothing and starts no AI call.
    if args.repair and args.reuse_tests:
        print("RUN REFUSED. --repair and --reuse-tests cannot be used together.")
        print()
        print("--reuse-tests runs tests that were saved earlier, and --repair")
        print("corrects tests for the code in front of it. A corrected test is")
        print("not the test that was saved, so the two mean opposite things and")
        print("the report would have to lie about which one it used. Run them")
        print("as two separate runs instead.")
        return 2

    for path in (args.before_file, args.after_file):
        if not Path(path).is_file():
            print(f"Cannot read that file: {path}")
            return 1

    # Turn the fallback on or off for this run. Off by default, so a run
    # without the flag behaves exactly as it always did. The same answer goes
    # into the report, so a saved report can say what the setting was.
    llm_client.ALLOW_FALLBACK = not args.no_fallback
    fallback_allowed = not args.no_fallback

    try:
        run_pipeline(args.before_file, args.after_file, args.name,
                     args.ai_second_opinion, args.reuse_tests, args.repair,
                     fallback_allowed=fallback_allowed,
                     mutation=args.mutation)
    except DailyLimitStop:
        # The notice has already been printed in full, and no report was saved,
        # so there is nothing to add here. This has its own exit code so a
        # stopped run can never be mistaken for a finished one.
        return EXIT_DAILY_LIMIT
    except Exception as error:
        # The pipeline could not do its job, which is the one thing that is
        # worth a non-zero exit.
        print(f"[prsentinel] the pipeline broke: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
