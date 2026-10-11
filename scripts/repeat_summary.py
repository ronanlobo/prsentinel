#!/usr/bin/env python
"""Offline summary for repeated runs."""
import json
import math
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

PROJECT = Path(__file__).resolve().parents[1]
RESULTS_BASE = PROJECT / "results" / "repeats"


def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n if n > 0 else 0
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(max(0, (p * (1 - p) + z * z / (4 * n)) / n))
    lo = (center - margin) / denom
    hi = (center + margin) / denom
    if lo < 0.0:
        lo = 0.0
    if hi > 1.0:
        hi = 1.0
    return lo, hi


def normalize_content(s: str) -> str:
    # normalize line endings and trailing spaces
    lines = []
    for line in s.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        lines.append(line.rstrip())
    joined = "\n".join(lines)
    # collapse multiple blank lines
    while "\n\n\n" in joined:
        joined = joined.replace("\n\n\n", "\n\n")
    # remove trailing blank lines
    joined = joined.rstrip("\n")
    return joined


def content_hash(s: str) -> str:
    return hashlib.sha256(normalize_content(s).encode("utf-8")).hexdigest()


def load_all_runs(base: Path = RESULTS_BASE) -> List[Dict[str, Any]]:
    runs = []
    if not base.exists():
        return runs
    for json_path in base.rglob("run_*.json"):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            runs.append(data)
        except Exception:
            continue
    return runs


def summarize(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    valid = [r for r in runs if not r.get("invalid", False)]
    excluded = len(runs) - len(valid)

    caught = 0
    fractions = []
    hashes = set()

    for r in valid:
        if r.get("caught_yes_no") is True:
            caught += 1
        tg = r.get("tests_generated")
        tc = r.get("tests_catching")
        if tg and tg > 0:
            try:
                fractions.append(tc / tg if tg > 0 else 0.0)
            except Exception:
                pass
        th = r.get("test_content_hash")
        if th:
            hashes.add(th)

    total_valid = len(valid)
    catch_rate = caught / total_valid if total_valid > 0 else 0.0
    mean_fraction_catching = sum(fractions) / len(fractions) if fractions else 0.0
    w_lo, w_hi = wilson_interval(caught, total_valid) if total_valid >= 0 else (0.0, 1.0)

    return {
        "runs": len(runs),
        "valid": total_valid,
        "excluded": excluded,
        "caught": caught,
        "catch_rate": catch_rate,
        "wilson_lo": w_lo,
        "wilson_hi": w_hi,
        "mean_fraction_catching": mean_fraction_catching,
        "distinct_test_files": len(hashes),
    }

def main():
    runs = load_all_runs()
    groups = {}
    for r in runs:
        groups.setdefault((r["case"], r["arm"]), []).append(r)
    print(f"{'case':24} {'arm':11} {'valid':>5} {'caught':>6} {'rate':>5} "
          f"{'95% Wilson':>13} {'mean frac':>9} {'distinct':>8} {'excl':>4}")
    for (case, arm), g in sorted(groups.items()):
        s = summarize(g)
        if s["valid"] == 0:
            print(f"{case:24} {arm:11} no valid runs ({s['excluded']} excluded)")
            continue
        print(f"{case:24} {arm:11} {s['valid']:>5} {s['caught']:>6} "
              f"{s['catch_rate']:>5.2f} {s['wilson_lo']:>6.2f}-{s['wilson_hi']:<6.2f} "
              f"{s['mean_fraction_catching']:>9.2f} {s['distinct_test_files']:>8} "
              f"{s['excluded']:>4}")
    print("\nIf distinct = 1 for a group, all valid runs produced the same tests, "
          "so they are not independent samples.")


if __name__ == "__main__":
    main()
