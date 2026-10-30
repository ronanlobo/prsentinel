import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
from audit_task_a_raw import Auditor
meta=a.BUGSINPY_META/"projects"/"thefuck"/"bugs"/"4"
info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]; repo=a.PROJECT_REPOS/"thefuck"
print("src system Path lines")
src=a.show_file(repo,sha,"thefuck/system.py")
for i,l in enumerate(src.splitlines(),1):
 if "Path" in l or "pathlib" in l: print(i,l)
aud=Auditor(repo,sha)
mod=aud.module("thefuck/utils.py")
print("import info", mod["imports"].get("Path"))
print("base", a.resolve_project_module("thefuck/utils.py",1,"system"))
