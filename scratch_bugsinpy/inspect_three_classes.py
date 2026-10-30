import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
for proj,bid in [("luigi","21"),("cookiecutter","1"),("thefuck","4")]:
 meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bid
 info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
 path=a.patch_changed_path(a.read_text_any(meta/"bug_patch.txt"))
 src=a.show_file(a.PROJECT_REPOS/proj,sha,path); tree=ast.parse(src)
 _,ch,_=a.r1_check(a.show_file(a.PROJECT_REPOS/proj,info["buggy_commit_id"],path),src); start=ch[0]
 print("="*90); print(proj,bid,path,start)
 same,cross,_=a.collect_helpers(a.PROJECT_REPOS/proj,sha,path,tree,start)
 print("same",same,"cross",cross)
 for n in same:
  funcs,classes=a.top_level_maps(tree)
  if n in classes:
   print("CLASS",n, ast.get_source_segment(src,classes[n])[:2500])
 for c in cross:
  local,target=c.split(" <- ",1); tp,tn=target.rsplit(":",1)
  msrc=a.show_file(a.PROJECT_REPOS/proj,sha,tp); mt=ast.parse(msrc); mf,mc=a.top_level_maps(mt)
  if tn in mc:
   print("CROSS CLASS",tn,tp,ast.get_source_segment(msrc,mc[tn])[:2500])
