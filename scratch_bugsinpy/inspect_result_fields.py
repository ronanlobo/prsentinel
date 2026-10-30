import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
base=r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy\results"
d=json.load(open(os.path.join(base,"thefuck.json"),encoding="utf-8"))
print("TOP",{k:v for k,v in d.items() if k!="bugs"})
for b in d["bugs"][:4]:
 print(json.dumps(b,indent=2,ensure_ascii=False)[:4000])
