"""Task A audit (read-only): list not-counted items for the 58 usable bugs."""

import ast
import sys
from pathlib import Path

import analyze_r2 as a

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

USABLE = {
    "youtube-dl": ["1", "3", "5", "7", "10", "11", "13", "15", "17", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "41", "43"],
    "PySnooper": ["3"],
    "tornado": ["9"],
    "cookiecutter": ["1", "3"],
    "fastapi": ["5", "6", "9", "10", "11", "16"],
    "black": ["9", "13", "16", "21"],
    "scrapy": ["11", "15", "17", "29", "35", "36", "38"],
    "thefuck": ["1", "2", "4", "5", "10", "15", "18", "21", "25", "26", "27", "30", "31", "32"],
    "keras": ["9"],
    "luigi": ["21"],
}


def main():
    total = 0
    for project, bugs in USABLE.items():
        repo = a.PROJECT_REPOS / project
        meta = a.BUGSINPY_META / "projects" / project / "bugs"
        for bid in bugs:
            total += 1
            info = a.bug_info(a.read_text_any(meta / bid / "bug.info"))
            patch = a.read_text_any(meta / bid / "bug_patch.txt")
            path = a.patch_changed_path(patch)
            sha = info["fixed_commit_id"]
            src = a.show_file(repo, sha, path)
            tree = ast.parse(src)
            _ok, changed, _reasons = a.r1_check(
                a.show_file(repo, info["buggy_commit_id"], path), src
            )
            func = changed[0]
            same, cross, not_counted = a.collect_helpers(repo, sha, path, tree, func)
            print("=== " + project + " bug " + bid + " | " + func + " | " + path + " ===")
            print("R2 total: " + str(len(same) + len(cross)))
            print("same: " + str(same))
            print("cross: " + str(cross))
            print("not counted: " + str(not_counted))
            print("")
    print("TOTAL BUGS: " + str(total))


if __name__ == "__main__":
    main()
