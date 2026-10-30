import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
for proj,bid,path in [("thefuck","21","thefuck/specific/git.py"),("thefuck","31","thefuck/utils.py"),("thefuck","25","thefuck/utils.py"),("thefuck","25","thefuck/types.py")]:
 meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bid
 info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
 src=a.show_file(a.PROJECT_REPOS/proj,sha,path)
 print("="*90); print(proj,bid,path); print(src[:6000])
