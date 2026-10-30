import sys
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
meta=a.BUGSINPY_META/"projects"/"thefuck"/"bugs"/"4"
info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]; repo=a.PROJECT_REPOS/"thefuck"
print("resolve", a.resolve_project_module("thefuck/utils.py",1,"system"))
print("cands", a.module_candidates("thefuck/system"))
import subprocess
print(a.run(["git","ls-tree","-r","--name-only",sha],cwd=repo)[:4000])
