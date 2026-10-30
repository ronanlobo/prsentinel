import sys
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import audit_task_a_report as r
for proj,bug in [("thefuck","4"),("thefuck","30"),("thefuck","5"),("thefuck","15"),("thefuck","25"),("thefuck","26"),("thefuck","31"),("black","9"),("black","13"),("fastapi","6"),("fastapi","9"),("fastapi","11"),("PySnooper","3")]:
    rec=r.collect(proj,bug)
    print("="*80)
    print(proj,bug,rec["function"],"current",rec["r2_total"],"same",rec["same"],"cross",rec["cross"])
    for it in rec["items"]:
        if it["status"]!="A" or it["callees"] or it["kind"]=="module-alias":
            print(" ",it["kind"],it["ref"],"->",it["target_path"],it["target_name"],"status",it["status"],"directB",it["direct_b"],"transB",it["transitive_b"],"callees",it["callees"],"parent",it.get("parent"))
