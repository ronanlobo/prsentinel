import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
repo=a.PROJECT_REPOS/"thefuck"
# fixed sha of bug 4
meta=a.BUGSINPY_META/"projects"/"thefuck"/"bugs"/"4"
info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
src=a.show_file(repo,sha,"thefuck/utils.py")
print(src[:9000])
