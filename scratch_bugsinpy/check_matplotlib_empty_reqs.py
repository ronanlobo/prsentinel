"""Diagnostic: empty requirements.txt projects and their test imports."""

import sys

import analyze_r2 as a

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CASES = {
    "matplotlib": ["16", "17", "24", "26", "30"],
}

for project, bids in CASES.items():
    repo = a.PROJECT_REPOS / project
    meta = a.BUGSINPY_META / "projects" / project / "bugs"
    for bid in bids:
        bugdir = meta / bid
        info = a.bug_info(a.read_text_any(bugdir / "bug.info"))
        req_path = bugdir / "requirements.txt"
        raw = req_path.read_bytes() if req_path.exists() else b""
        cmd_path = bugdir / "run_test.sh"
        cmd = a.read_text_any(cmd_path).strip() if cmd_path.exists() else ""
        print("=== " + project + " bug " + bid + " ===")
        print("requirements.txt bytes: " + str(len(raw)))
        print("run_test.sh: " + cmd)
        evaluated, hits, imports, files = a.r3_from_tests(
            repo, info["fixed_commit_id"], info, cmd
        )
        print("test R3 evaluated=" + str(evaluated))
        print("test third-party imports: " + str(imports))
        print("test heavy hits: " + str(hits))
        print("test files: " + files)
