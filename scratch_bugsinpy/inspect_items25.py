import sys, json
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import audit_task_a_report as r
for proj,bug in [("thefuck","25"),("thefuck","21"),("thefuck","31")]:
 rec=r.collect(proj,bug)
 print("="*90); print(proj,bug,"items",len(rec["items"]))
 for it in rec["items"]:
  print(json.dumps({k:it.get(k) for k in ("kind","ref","target_path","target_name","status","direct_b","transitive_b","callees","rhs","ctx","local")}, ensure_ascii=False)[:1000])
