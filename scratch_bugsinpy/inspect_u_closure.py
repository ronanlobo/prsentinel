import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
for proj,bid in [("thefuck","31"),("thefuck","26"),("PySnooper","3"),("thefuck","4")]:
 meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bid
 info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
 print("="*90); print(proj,bid)
 # print relevant modified files from audit? use known paths
 paths={"thefuck":["thefuck/utils.py","thefuck/shells.py","thefuck/shells/__init__.py"],"PySnooper":["pysnooper/utils.py"],"thefuck4":["thefuck/utils.py"]}.get(proj if proj!="thefuck" or bid!="4" else "thefuck4",[])
 for p in paths:
  src=a.show_file(a.PROJECT_REPOS/proj,sha,p)
  if src is None: continue
  print("---",p,"---")
  if p.endswith("utils.py") and proj=="thefuck":
   for name in ("git_support","is_app","memoize","cache","Cache","warn"):
    tree=ast.parse(src); funcs,classes=a.top_level_maps(tree)
    node=funcs.get(name) or classes.get(name)
    if node: print(name,":",ast.get_source_segment(src,node)[:1600])
  elif p.endswith("shells.py") and proj=="thefuck":
   print(src[:2500])
  elif p.endswith("__init__.py") and proj=="thefuck":
   print(src[:2500])
  elif proj=="PySnooper":
   print(src[:2500])
