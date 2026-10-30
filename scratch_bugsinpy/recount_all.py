#!/usr/bin/env python3
"""Recompute the clarified R2 count for every R1 survivor."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from recount_r2_rule import compute

RESULTS = HERE / "results"
OUT = HERE / "r2_all_counts.json"

rows = []
for path in sorted(RESULTS.glob("*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    project = data["project"]
    for bug in data.get("bugs", []):
        if not bug.get("r1"):
            continue
        rec = compute(project, str(bug["bug"]))
        rec["old_total"] = bug.get("r2_total")
        rec["old_r2"] = bug.get("r2")
        rows.append(rec)
        print(project, bug["bug"], rec["total"], rec["verdict"], file=sys.stderr)
OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("WROTE", OUT, "rows", len(rows))
print("pass", sum(1 for r in rows if r["total"] <= 3), "excluded", sum(1 for r in rows if r["total"] > 3))
