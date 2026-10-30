import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
import audit_task_a_report as r
from audit_task_a_raw import Auditor, USABLE

def target_of(c):
    # "path:name"
    if not c or ":" not in c: return None
    p,n=c.rsplit(":",1)
    return (p,n)

def kind_of(aud,p,n):
    m=aud.module(p)
    if not m: return None
    if n in m["funcs"]: return "function"
    if n in m["classes"]: return "class"
    if n in m["assigns"] or n in m["global_assigns"]: return "assign"
    return None

allrows=[]
for proj,bugs in USABLE.items():
 for bug in bugs:
  rec=r.collect(proj,bug)
  meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bug
  info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
  aud=Auditor(a.PROJECT_REPOS/proj,sha)
  base=set()
  for n in rec["same"]:
   k=kind_of(aud,rec["path"],n)
   if k: base.add((rec["path"],n))
  for c in rec["cross"]:
   local,target=c.split(" <- ",1); tp,tn=target.rsplit(":",1)
   base.add((tp,tn))
  namespaces=set()
  uattrs=set()
  bcallees=set()
  for it in rec["items"]:
   if it["kind"]=="module-alias":
    namespaces.add(it["target_path"])
   elif it["kind"] in ("attribute-class","attribute-function"):
    if (it["target_path"],it["target_name"]) not in r.PY3_STDLIB_ATTRS:
     uattrs.add((it["target_path"],it["target_name"]))
   elif it["direct_b"] or it["transitive_b"]:
    for c in it["callees"]:
     t=target_of(c)
     if t and kind_of(aud,*t) in ("function","class"):
      bcallees.add(t)
  # class-body refs for classes in base/uattrs/bcallees (recursive functions only)
  extra=set(); queue=[]
  for p,n in list(base)+list(uattrs)+list(bcallees):
   if kind_of(aud,p,n)=="class": queue.append((p,n))
  seen=set()
  while queue:
   p,n=queue.pop(0)
   if (p,n) in seen: continue
   seen.add((p,n))
   m=aud.module(p)
   if not m: continue
   node=m["classes"].get(n)
   if node is None: continue
   for ref in sorted(a.referenced_names(node)):
    res=aud.lookup(p,ref)
    if not res: continue
    k,tp,tn,pl=res
    if k in ("function","class"):
     if (tp,tn) not in base and (tp,tn) not in uattrs and (tp,tn) not in bcallees:
      extra.add((tp,tn))
     if k=="function": queue.append((tp,tn))
  total=len(base|uattrs|bcallees|extra)+len(namespaces)
  allrows.append((proj,bug,rec["function"],rec["r2_total"],len(base),sorted(namespaces),sorted(uattrs),sorted(bcallees),sorted(extra),total))
  print(f"{proj}|{bug}|{rec['function']}|base={len(base)}|ns={len(namespaces)}|u={len(uattrs)}|bcallee={len(bcallees)}|extra={len(extra)}|TOTAL={total}|{'PASS' if total<=3 else 'EXCLUDED'}")
  detail=[f"ns={sorted(namespaces)}",f"u={sorted(uattrs)}",f"b={sorted(bcallees)}",f"extra={sorted(extra)}"]
  print("   "+" ".join(detail))
print("SUMMARY total<=3",sum(1 for x in allrows if x[-1]<=3),"of",len(allrows))
print("EXCLUDED")
for x in allrows:
 if x[-1]>3: print(x[0],x[1],x[2],x[-1])
