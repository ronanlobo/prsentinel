import sys
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import audit_task_a_report as r
for proj,bug in [("thefuck","21"),("thefuck","31"),("thefuck","26"),("thefuck","25"),("thefuck","4"),("thefuck","30"),("PySnooper","3")]:
    rec=r.collect(proj,bug)
    print("="*90)
    print(proj,bug,rec["function"],"current",rec["r2_total"],"same",rec["same"],"cross",rec["cross"])
    for it in rec["items"]:
        if it["status"]!="A" or it["kind"]=="module-alias" or "namedtuple" in (it.get("rhs") or ""):
            print(" ",it["kind"],"ref=",it["ref"],"target=",it["target_name"],"path=",it["target_path"],"status",it["status"],"directB",it["direct_b"],"transB",it["transitive_b"],"callees",it["callees"],"rhs",(it.get("rhs") or "")[:160])
