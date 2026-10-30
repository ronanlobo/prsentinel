import json, os, sys
sys.stdout.reconfigure(encoding="utf-8")
base=r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy"
rows=json.load(open(os.path.join(base,"r2_all_counts.json"),encoding="utf-8"))
print("TOTAL",len(rows),"pass",sum(r["total"]<=3 for r in rows),"excluded",sum(r["total"]>3 for r in rows))
print("\nEXCLUDED")
for r in rows:
 if r["total"]>3:
  print(f'{r["project"]} {r["bug"]} {r["function"]} total={r["total"]} old={r.get("old_total")} funcs={len(r["functions"])} classes={len(r["classes"])} init={len(r["initializers"])} nt={len(r["namedtuples"])} ns={len(r["namespaces"])}')
print("\nPASS >=2")
for r in rows:
 if r["total"]<=3 and r["total"]>=2:
  print(f'{r["project"]} {r["bug"]} {r["function"]} total={r["total"]} old={r.get("old_total")} funcs={r["functions"]} classes={r["classes"]} init={r["initializers"]} nt={r["namedtuples"]} ns={r["namespaces"]}')
