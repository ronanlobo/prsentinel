import sys
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
meta=a.BUGSINPY_META/"projects"/"thefuck"/"bugs"/"4"; info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]; repo=a.PROJECT_REPOS/"thefuck"
for p in ["thefuck/system/win32.py","thefuck/system/unix.py"]:
 src=a.show_file(repo,sha,p); print("="*40,p); print(src[:3000])
