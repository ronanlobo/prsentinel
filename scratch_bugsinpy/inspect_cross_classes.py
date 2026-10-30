import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
from audit_task_a_raw import Auditor
for proj,bid in [("scrapy","35"),("black","13"),("fastapi","9"),("thefuck","21")]:
 meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bid
 info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
 path=a.patch_changed_path(a.read_text_any(meta/"bug_patch.txt"))
 aud=Auditor(a.PROJECT_REPOS/proj, sha)
 same,cross,_=a.collect_helpers(a.PROJECT_REPOS/proj,sha,path,ast.parse(a.show_file(a.PROJECT_REPOS/proj,sha,path)),a.r1_check(a.show_file(a.PROJECT_REPOS/proj,info["buggy_commit_id"],path),a.show_file(a.PROJECT_REPOS/proj,sha,path))[1][0])
 print("="*90); print(proj,bid,"same",same,"cross",cross)
 # resolve cross refs and print class bodies
 for c in cross:
  local,target=c.split(" <- "); tp,tn=target.rsplit(":",1)
  mod=aud.module(tp)
  if mod and tn in mod["classes"]:
   node=mod["classes"][tn]
   print("CLASS",tp,tn,"bases",[ast.unparse(b) for b in node.bases],"refs",sorted(a.referenced_names(node)))
  elif mod and tn in mod["funcs"]:
   print("FUNC",tp,tn,"refs",sorted(a.referenced_names(mod["funcs"][tn])))
