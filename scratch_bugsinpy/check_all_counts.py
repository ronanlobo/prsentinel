import json, collections, sys, os
sys.stdout.reconfigure(encoding="utf-8")
base=r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy"
allc=json.load(open(os.path.join(base,"r2_all_counts.json"),encoding="utf-8"))
print("all by project", dict(collections.Counter(r["project"] for r in allc)))
for f in ["youtube-dl","PySnooper","tornado","tqdm","cookiecutter","fastapi","black","scrapy","thefuck","pandas","keras","ansible","matplotlib","luigi","sanic","spacy","httpie"]:
 p=os.path.join(base,"results",f+".json")
 try: d=json.load(open(p,encoding="utf-8"))
 except FileNotFoundError: continue
 bugs=d.get("bugs",[])
 print(f, "n",len(bugs),"r1true",sum(1 for b in bugs if b.get("r1")), "r1false",sum(1 for b in bugs if b.get("r1") is False), "r1none",sum(1 for b in bugs if b.get("r1") is None), "counts",sum(1 for r in allc if r["project"]==f))
