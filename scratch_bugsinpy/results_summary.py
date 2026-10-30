import json, glob, os, sys
sys.stdout.reconfigure(encoding="utf-8")
for f in sorted(glob.glob(r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy\results\*.json")):
    d=json.load(open(f,encoding="utf-8"))
    bugs=d.get("bugs",[])
    r1=sum(1 for b in bugs if b.get("r1"))
    r1f=sum(1 for b in bugs if b.get("r1") is False)
    r2f=sum(1 for b in bugs if b.get("r1") and b.get("r2") is False)
    r3f=sum(1 for b in bugs if b.get("r1") and b.get("r2") and b.get("r3") is False)
    usable=sum(1 for b in bugs if b.get("r1") and b.get("r2") and b.get("r3"))
    lic=d.get("licence") or {}
    print(os.path.basename(f), "mode",d.get("mode"),"n",len(bugs),"r1pass",r1,"r1fail",r1f,"r2fail",r2f,"r3fail",r3f,"usable",usable,"licence",lic.get("guess"),"excluded",lic.get("excluded"),"stage",lic.get("stage"))
    # show r2/r3 None counts
    none2=sum(1 for b in bugs if b.get("r1") and b.get("r2") is None)
    none3=sum(1 for b in bugs if b.get("r1") and b.get("r3") is None)
    if none2 or none3: print("   none2",none2,"none3",none3)
