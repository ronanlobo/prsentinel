import json, sys
sys.stdout.reconfigure(encoding="utf-8")
rows=json.load(open(r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy\r2_new_counts.json",encoding="utf-8"))
for r in rows:
    if r["total"]>3 or r["project"] in ("thefuck","PySnooper") and r["bug"] in ("4","25","26","30","31","1","2","21","3"):
        print("="*80)
        print(r["project"],r["bug"],r["function"],"total",r["total"],r["verdict"])
        for k in ("functions","classes","initializers","namedtuples","namespaces"):
            print(" ",k,"=",r[k])
