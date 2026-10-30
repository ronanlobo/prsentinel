import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
from audit_task_a_raw import Auditor
meta=a.BUGSINPY_META/"projects"/"thefuck"/"bugs"/"4"
info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]; repo=a.PROJECT_REPOS/"thefuck"
aud=Auditor(repo,sha)
path="thefuck/utils.py"; mod=aud.module(path)
print("Path lookup", aud.lookup(path,"Path"))
print("Cache refs", sorted(a.referenced_names(mod["classes"]["Cache"])))
print("warn lookup", aud.lookup(path,"warn"))
print("resolve import Path", aud.resolve_import(path,"Path"))
