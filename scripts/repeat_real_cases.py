#!/usr/bin/env python
"""Repeated runs helpers and script structure (skeleton for tests)."""
import json
import os
from pathlib import Path
from typing import Any, Dict

PROJECT = Path(__file__).resolve().parents[1]
REAL_CASES = ("real_youtube-dl_bug3", "real_youtube-dl_bug43", "real_PySnooper_bug3")
RESULTS_BASE = PROJECT / "results" / "repeats"
REPORTS_DIR = PROJECT / "reports"
REQUIRED_KEYS = [
    "case", "arm", "run_index", "timestamp", "provider", "model",
    "temperature", "gemini_answers", "fallback_used", "tests_generated",
    "tests_catching", "tests_wrong_on_before", "tests_odd", "caught_yes_no",
    "invalid", "invalid_reason", "exit_code", "error", "test_content_hash",
]


def should_skip_run(path: Path) -> bool:
    """Return True if run exists and is valid; raise RuntimeError if unreadable."""
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raise RuntimeError("unreadable run file")
    for k in REQUIRED_KEYS:
        if k not in data:
            raise RuntimeError("missing required key")
    return True


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# The runner (Pieces 2 and 3). Appended below the helpers above.
# Run from the project root:  python -m scripts.repeat_real_cases --runs 10
# ---------------------------------------------------------------------------
import argparse
import datetime
import shutil
import sys
import tempfile
from contextlib import contextmanager

EXIT_DAILY_LIMIT = 6
EXIT_STOPPED = 2
ARMS = ("prsentinel", "baseline")
CATCHES, WRONG_ON_BEFORE, ODD = "CATCHES_CHANGE", "TEST_WRONG_ON_BEFORE", "ODD"


class RecordingAsk:
    """Forwards every call unchanged and remembers the temperature it saw."""

    def __init__(self, original):
        self.original = original
        self.temperatures = []

    def __call__(self, prompt, *args, **kwargs):
        self.temperatures.append(args[0] if args else kwargs.get("temperature"))
        return self.original(prompt, *args, **kwargs)


@contextmanager
def recording(llm_client, tg):
    """Swap in the recording wrapper for one run, always put the originals back."""
    original_llm, original_tg = llm_client.ask_llm, tg.ask_llm
    wrapper = RecordingAsk(original_llm)
    llm_client.ask_llm = wrapper
    tg.ask_llm = wrapper
    try:
        yield wrapper
    finally:
        llm_client.ask_llm = original_llm
        tg.ask_llm = original_tg


def build_record(case, arm, idx, code, rows, provider, temps, expected_temp,
                 whole_file_name, error=None):
    """Turn one run into the JSON record. Pure, so it is easy to test."""
    from scripts import repeat_summary as rs
    rows = rows or []
    real_rows = [r for r in rows if r.get("name") != whole_file_name]
    catching = sum(1 for r in real_rows if r.get("label") == CATCHES)
    wrong = sum(1 for r in real_rows if r.get("label") == WRONG_ON_BEFORE)
    odd = sum(1 for r in real_rows if r.get("label") == ODD)

    provider_text = str(provider or "")
    is_groq = "groq" in provider_text.lower()
    gemini = 1 if "gemini" in provider_text.lower() else 0

    reason = ""
    if not temps:
        reason = "no model call was recorded"
    elif not is_groq:
        reason = f"answer did not come from Groq (provider: {provider_text or 'none'})"
    elif any(t != expected_temp for t in temps):
        reason = f"temperature sent {temps} differs from expected {expected_temp}"

    return {
        "case": case, "arm": arm, "run_index": idx,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "provider": provider_text, "model": "openai/gpt-oss-120b",
        "temperature": temps[0] if temps else None,
        "gemini_answers": gemini, "fallback_used": bool(gemini),
        "tests_generated": len(real_rows), "tests_catching": catching,
        "tests_wrong_on_before": wrong, "tests_odd": odd,
        "caught_yes_no": catching > 0,
        "invalid": bool(reason), "invalid_reason": reason,
        "exit_code": None, "error": error,
        "test_content_hash": rs.content_hash(code or ""),
        "test_content": code or "",
    }


def run_all(cases, runs, do_run, base=RESULTS_BASE, limit_exc=None):
    """Loop over case x arm x run. Resume, write atomically, stop on a daily limit."""
    done, missing = 0, []
    for case in cases:
        for arm in ARMS:
            for n in range(1, runs + 1):
                path = base / case / arm / f"run_{n:02d}.json"
                try:
                    if should_skip_run(path):
                        continue
                except RuntimeError as err:
                    print(f"STOP: {path} exists but is not usable ({err}). "
                          f"Nothing was overwritten. Decide what to do with it.")
                    return EXIT_STOPPED
                try:
                    record = do_run(case, arm, n)
                except Exception as err:
                    if limit_exc is not None and isinstance(err, limit_exc):
                        missing.append(f"{case}/{arm}/run_{n:02d}")
                        print(f"DAILY LIMIT reached after {done} runs this session. "
                              f"Finished runs are kept. Do not trust a partial summary.")
                        return EXIT_DAILY_LIMIT
                    raise
                atomic_write_json(path, record)
                done += 1
                print(f"saved {path.relative_to(base)}  caught={record['caught_yes_no']}"
                      f"  invalid={record['invalid']}")
    print(f"finished: {done} new runs written")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--only", default=None)
    args = parser.parse_args(argv)
    cases = [args.only] if args.only else list(REAL_CASES)
    for c in cases:
        if c not in REAL_CASES:
            print(f"unknown case {c}; choose from {REAL_CASES}")
            return EXIT_STOPPED
    print(f"planned: {len(cases)} cases x {len(ARMS)} arms x {args.runs} runs "
          f"= {len(cases) * len(ARMS) * args.runs} model calls (already-saved runs are skipped)")

    from prsentinel import config, llm_client
    from prsentinel import test_generator as tg
    from prsentinel import test_runner as tr
    from scripts import baseline_single_prompt as bsp
    llm_client.ALLOW_FALLBACK = False

    def do_run(case, arm, idx):
        folder = PROJECT / "examples" / "real_cases" / case
        before, after = str(folder / "before.py"), str(folder / "after.py")
        change = bsp.the_modified_change({"name": case, "folder": folder})
        llm_client.LAST_PROVIDER = None
        code, rows, error = "", [], None
        with recording(llm_client, tg) as wrapper:
            try:
                if arm == "prsentinel":
                    code = tg.generate_tests(change)
                else:
                    reply = llm_client.ask_llm(bsp.build_prompt(change),
                                               config.GENERATION_TEMPERATURE)
                    code = tg.extract_code(reply)
            except llm_client.DailyLimitReached:
                raise
            except Exception as err:
                error = f"no usable tests: {err}"
        provider = getattr(llm_client, "LAST_PROVIDER", None)
        if code:
            scratch = Path(tempfile.mkdtemp(dir=PROJECT, prefix="rep_scratch_"))
            try:
                test_file = scratch / f"test_{change['name']}.py"
                test_file.write_text(code, encoding="utf-8")
                rows = tr.evaluate_tests(before, after, str(test_file))
            finally:
                shutil.rmtree(scratch, ignore_errors=True)
        return build_record(case, arm, idx, code, rows, provider,
                            wrapper.temperatures, config.GENERATION_TEMPERATURE,
                            tr.WHOLE_FILE, error)

    return run_all(cases, args.runs, do_run, limit_exc=llm_client.DailyLimitReached)


if __name__ == "__main__":
    sys.exit(main())