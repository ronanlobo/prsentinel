import sys, json
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import audit_task_a_report as r
for proj,bug in [("black","9"),("black","13"),("fastapi","6"),("fastapi","9"),("thefuck","5"),("thefuck","15"),("thefuck","4"),("thefuck","30"),("PySnooper","3"),("thefuck","25"),("thefuck","31"),("thefuck","26"),("fastapi","11")]:
 rec=r.collect(proj,bug)
 print("="*90); print(proj,bug,rec["function"],"current",rec["r2_total"])
 for it in rec["items"]:
  if it["status"]!="A":
   print(" ",it["kind"],"ref",it["ref"],"target",it["target_path"],it["target_name"],"status",it["status"],"callees",it["callees"])
