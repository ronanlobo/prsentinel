import sys
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
from audit_task_a_raw import Auditor
meta=a.BUGSINPY_META/"projects"/"thefuck"/"bugs"/"4"; info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]; repo=a.PROJECT_REPOS/"thefuck"
src=a.show_file(repo,sha,"thefuck/system/__init__.py")
print(src)
aud=Auditor(repo,sha)
print("lookup in init", aud.lookup("thefuck/system/__init__.py","Path"))
print("module imports", aud.module("thefuck/system/__init__.py")["imports"])
