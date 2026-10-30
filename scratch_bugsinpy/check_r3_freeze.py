"""Diagnostic: would the frozen R3 freeze-amendment change these blockers?"""

import sys

import analyze_r2 as a

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

CASES = {
    "luigi": ["21"],
    "spacy": ["1", "2", "4"],
}

for project, bids in CASES.items():
    repo = a.PROJECT_REPOS / project
    meta = a.BUGSINPY_META / "projects" / project / "bugs"
    bug_dirs = sorted(
        [d for d in meta.iterdir() if d.is_dir() and d.name.isdigit()],
        key=lambda d: int(d.name),
    )
    groups = a.requirement_groups(bug_dirs)
    for bid in bids:
        bugdir = meta / bid
        info = a.bug_info(a.read_text_any(bugdir / "bug.info"))
        req_text = a.read_text_any(bugdir / "requirements.txt")
        packages = a.parse_requirements(req_text)
        group = groups.get(req_text.strip(), [bid])
        freeze = a.freeze_evidence(repo, info["fixed_commit_id"], packages, group)
        print("=== " + project + " bug " + bid + " ===")
        print("requirements heavy hits: " + str(a.heavy_hits(packages)))
        if freeze is None:
            print("freeze: NO")
            continue
        print(
            "freeze: YES group="
            + str(freeze["group"])
            + " unrelated="
            + str(len(freeze["unrelated"]))
            + "/"
            + str(freeze["total"])
        )
        cmd = ""
        cmd_path = bugdir / "run_test.sh"
        if cmd_path.exists():
            cmd = a.read_text_any(cmd_path).strip()
        evaluated, hits, imports, files = a.r3_from_tests(
            repo, info["fixed_commit_id"], info, cmd
        )
        print("run_test.sh: " + cmd)
        print("test R3 evaluated=" + str(evaluated))
        print("test third-party imports: " + str(imports))
        print("test heavy hits: " + str(hits))
        print("test files: " + files)
