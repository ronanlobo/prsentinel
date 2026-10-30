#!/usr/bin/env python3
"""Apply the 2026-10-26 clarified R2 counts to results/*.json.

R1 and R3 are untouched. Old R2 values are retained as old_r2_total/old_r2 so
the notes can show exactly what moved. The new count is the one the notes and
funnel use.
"""
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
RESULTS = BASE / "results"
COUNTS = BASE / "r2_all_counts.json"


def main():
    rows = json.loads(COUNTS.read_text(encoding="utf-8"))
    by_key = {(r["project"], str(r["bug"])): r for r in rows}
    changed = 0
    for path in sorted(RESULTS.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        project = data["project"]
        for bug in data.get("bugs", []):
            rec = by_key.get((project, str(bug["bug"])))
            if rec is None:
                continue
            bug["old_r2_total"] = bug.get("r2_total")
            bug["old_r2"] = bug.get("r2")
            bug["r2_total"] = rec["total"]
            bug["r2"] = rec["total"] <= 3
            bug["r2_rule"] = "2026-10-26 data-name clarification"
            bug["r2_helpers"] = {
                "functions": rec["functions"],
                "classes": rec["classes"],
                "initializers": rec["initializers"],
                "namedtuples": rec["namedtuples"],
                "namespaces": rec["namespaces"],
            }
            changed += 1
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("updated", changed, "R1-survivor records")


if __name__ == "__main__":
    main()
