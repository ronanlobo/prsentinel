import analyze_r2 as a
from pathlib import Path

repo = a.PROJECT_REPOS / "fastapi"
meta = a.BUGSINPY_META / "projects" / "fastapi" / "bugs"
bug_dirs = [d for d in meta.iterdir() if d.is_dir() and d.name.isdigit()]
groups = a.requirement_groups(bug_dirs)
for bid in ("4", "5", "9", "10", "11", "16"):
    info = a.bug_info(a.read_text_any(meta / bid / "bug.info"))
    sha = info["fixed_commit_id"]
    req = a.read_text_any(meta / bid / "requirements.txt").strip()
    pkgs = a.parse_requirements(req)
    group = groups.get(req, [bid])
    imported = a.project_imported_modules(repo, sha)
    norm = {a.normalize_pkg(x) for x in imported}
    unrelated = [p for p in pkgs if a.normalize_pkg(p) not in norm]
    print(bid, "sha", sha[:8], "group", group, "pkgs", len(pkgs),
          "imported", len(imported), "unrelated", len(unrelated))
    print("   imported sample:", sorted(imported)[:10])
