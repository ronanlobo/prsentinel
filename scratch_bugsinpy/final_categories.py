import json, os, sys, collections
sys.stdout.reconfigure(encoding="utf-8")
base=r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy"
allc={(r["project"],str(r["bug"])):r for r in json.load(open(os.path.join(base,"r2_all_counts.json"),encoding="utf-8"))}
order=["youtube-dl","PySnooper","tornado","tqdm","cookiecutter","fastapi","black","scrapy","thefuck","pandas","keras","ansible","matplotlib","luigi","sanic","spacy","httpie"]
tot=collections.Counter(); final=[]; removed=[]
for proj in order:
 d=json.load(open(os.path.join(base,"results",proj+".json"),encoding="utf-8")); mode=d.get("mode"); lic=d.get("licence") or {}; lic_ex=bool(lic.get("excluded"))
 for b in d.get("bugs",[]):
  bid=str(b["bug"]); r=allc.get((proj,bid)); newtotal=r["total"] if r else b.get("r2_total"); newr2=(newtotal is not None and newtotal<=3)
  if lic_ex and mode=="r1":
   cat="licence"
  elif not b.get("r1"):
   cat="r1"
  elif lic_ex:
   cat="licence"
  elif mode=="full" and not newr2:
   cat="r2"
  elif b.get("r3") is False:
   cat="r3"
  elif mode=="r1" and not newr2:
   cat="r2"
  else:
   cat="usable"; final.append((proj,int(bid),b.get("function"),newtotal,b.get("r3_basis") or b.get("basis")))
  tot[cat]+=1
print("CATEGORIES",dict(tot),"sum",sum(tot.values()))
print("FINAL",len(final))
for x in final: print(x)
print("PER PROJECT")
for proj in order:
 d=json.load(open(os.path.join(base,"results",proj+".json"),encoding="utf-8")); mode=d.get("mode"); lic=d.get("licence") or {}; lic_ex=bool(lic.get("excluded")); c=collections.Counter()
 for b in d.get("bugs",[]):
  bid=str(b["bug"]); r=allc.get((proj,bid)); nt=r["total"] if r else b.get("r2_total"); nr=(nt is not None and nt<=3)
  if lic_ex and mode=="r1": cat="licence"
  elif not b.get("r1"): cat="r1"
  elif lic_ex: cat="licence"
  elif mode=="full" and not nr: cat="r2"
  elif b.get("r3") is False: cat="r3"
  elif mode=="r1" and not nr: cat="r2"
  else: cat="usable"
  c[cat]+=1
 print(proj,mode,"lic",lic.get("guess"),lic_ex,dict(c))
