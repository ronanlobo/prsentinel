import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
meta=a.BUGSINPY_META/"projects"/"thefuck"/"bugs"/"4"
info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
src=a.show_file(a.PROJECT_REPOS/"thefuck",sha,"thefuck/utils.py")
print("\n".join(src.splitlines()[:40]))
print("Path import context:")
for i,l in enumerate(src.splitlines(),1):
 if "Path" in l: print(i,l)
