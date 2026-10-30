import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
for proj,bid in [("thefuck","4"),("thefuck","30")]:
    meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bid
    info=a.bug_info(a.read_text_any(meta/"bug.info"))
    sha=info["fixed_commit_id"]
    path=a.patch_changed_path(a.read_text_any(meta/"bug_patch.txt"))
    src=a.show_file(a.PROJECT_REPOS/proj,sha,path)
    print("="*80); print(proj,bid,path,sha); print(src[:7000])
