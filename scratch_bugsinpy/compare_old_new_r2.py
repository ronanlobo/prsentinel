"""Compare the pre-fix notes with the regenerated notes (evidence only)."""

import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OLD = Path("notes_before_r2_fix.md")
NEW = Path("../notes/bugsinpy_scan.md")


def parse(path):
    text = path.read_text(encoding="utf-8")
    sections = {}
    current = None
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        match = re.match(r"^## (.+)$", line)
        if match:
            current = match.group(1).strip()
            sections[current] = {"rows": {}, "usable": None}
            continue
        if current is None:
            continue
        match = re.match(r"^Usable for .*?: (.*)$", line)
        if match:
            sections[current]["usable"] = match.group(1).strip()
            continue
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 11 or not cells[0].isdigit():
            continue
        sections[current]["rows"][cells[0]] = {
            "function": cells[1],
            "r2_total": cells[4],
            "r3_basis": cells[5],
            "heavy": cells[7],
            "r2": cells[9],
            "r3": cells[10],
        }
    return sections


def usable_set(text):
    if text is None:
        return None
    if text.strip().lower() in ("none", "none (licence excluded)"):
        return set()
    return {part.strip() for part in text.split(",") if part.strip()}


old = parse(OLD)
new = parse(NEW)

for project in old:
    if project == "Rules applied" or project not in new:
        continue
    old_rows = old[project]["rows"]
    new_rows = new[project]["rows"]
    changes = []
    for bug in sorted(set(old_rows) | set(new_rows), key=int):
        a = old_rows.get(bug)
        b = new_rows.get(bug)
        if a is None or b is None:
            changes.append(
                "bug "
                + bug
                + ": "
                + ("only in old" if b is None else "only in new")
            )
            continue
        diffs = []
        if a["r2_total"] != b["r2_total"]:
            diffs.append("R2 total " + a["r2_total"] + " -> " + b["r2_total"])
        if a["r2"] != b["r2"]:
            diffs.append("R2 " + a["r2"] + " -> " + b["r2"])
        if a["r3"] != b["r3"]:
            diffs.append("R3 " + a["r3"] + " -> " + b["r3"])
        if a["r3_basis"] != b["r3_basis"]:
            diffs.append("R3 basis " + a["r3_basis"] + " -> " + b["r3_basis"])
        if a["heavy"] != b["heavy"]:
            diffs.append("heavy " + a["heavy"] + " -> " + b["heavy"])
        if diffs:
            changes.append("bug " + bug + ": " + "; ".join(diffs))
    old_usable = usable_set(old[project]["usable"])
    new_usable = usable_set(new[project]["usable"])
    if old_usable != new_usable and old_usable is not None and new_usable is not None:
        changes.append(
            "usable: ["
            + ", ".join(sorted(old_usable, key=int))
            + "] -> ["
            + ", ".join(sorted(new_usable, key=int))
            + "]"
        )
    if changes:
        print("=== " + project + " ===")
        for change in changes:
            print("  " + change)
        print("")
