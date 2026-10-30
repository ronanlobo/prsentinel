"""Diagnostic: are pandas' short buggy SHAs the fixed commit's parent?"""

import sys

import analyze_r2 as a

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = a.PROJECT_REPOS / "pandas"
META = a.BUGSINPY_META / "projects" / "pandas" / "bugs"

for bid in ["1", "2", "3", "10", "50", "100", "150", "169"]:
    info = a.bug_info(a.read_text_any(META / bid / "bug.info"))
    buggy = info["buggy_commit_id"]
    fixed = info["fixed_commit_id"]
    print("=== bug " + bid + " buggy=" + buggy + " fixed=" + fixed[:12] + " ===")
    code, _out, err = a.git(REPO, "fetch", "--depth", "2", "origin", fixed)
    if code != 0:
        print("fetch failed: " + err.strip())
        continue
    code, parent, _err = a.git(REPO, "rev-parse", fixed + "^")
    print("fixed parent: " + (parent.strip() if code == 0 else "?"))
    code, resolved, _err = a.git(REPO, "rev-parse", buggy)
    print("short resolves: " + (resolved.strip() if code == 0 else "NO"))
