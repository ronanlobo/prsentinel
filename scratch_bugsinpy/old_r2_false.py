import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
base=r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy"
allc={(r["project"],str(r["bug"])):r for r in json.load(open(os.path.join(base,"r2_all_counts.json"),encoding="utf-8"))}
print("OLD R2 FALSE -> NEW")
for f in os.listdir(os.path.join(base,"results")):
 if not f.endswith(".json"): continue
 d=json.load(open(os.path.join(base,"results",f),encoding="utf-8")); p=d["project"]
 for b in d.get("bugs",[]):
  if b.get("r1") and b.get("r2") is False:
   r=allc.get((p,str(b["bug"])))
   print(p,b["bug"],"old",b.get("r2_total"),"new",r["total"] if r else None,"verdict",r["verdict"] if r else None)
