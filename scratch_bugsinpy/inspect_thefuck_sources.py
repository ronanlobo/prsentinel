import ast, sys
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
from pathlib import Path
repo = a.PROJECT_REPOS / "thefuck"
for bid in ["4","30","5","15"]:
    meta = a.BUGSINPY_META / "projects" / "thefuck" / "bugs" / bid
    info = a.bug_info(a.read_text_any(meta / "bug.info"))
    sha = info["fixed_commit_id"]
    patch = a.read_text_any(meta / "bug_patch.txt")
    path = a.patch_changed_path(patch)
    src = a.show_file(repo, sha, path)
    tree = ast.parse(src)
    funcs, classes = a.top_level_maps(tree)
    _, changed, _ = a.r1_check(a.show_file(repo, info["buggy_commit_id"], path), src)
    start = changed[0]
    print("="*70)
    print("bug", bid, path, "function", start)
    print(a.show_file(repo, sha, path).splitlines()[:0])
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in (start, "_get_aliases", "_make_pattern", "Cache", "match", "get_new_command"):
            print("\n---", type(node).__name__, node.name, "---")
            print(ast.get_source_segment(src, node)[:3000])
    print("\n--- constants involving relevant names ---")
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            txt = ast.get_source_segment(src, node) or ""
            if any(x in txt for x in ("_cache","patterns","shell","_make_pattern","Cache")):
                print(txt[:2000])
