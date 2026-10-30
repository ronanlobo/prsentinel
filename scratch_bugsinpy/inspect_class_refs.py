import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
for proj,bid in [("scrapy","35"),("scrapy","15"),("scrapy","17"),("thefuck","21"),("black","9"),("fastapi","9")]:
 meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bid
 info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
 path=a.patch_changed_path(a.read_text_any(meta/"bug_patch.txt"))
 src=a.show_file(a.PROJECT_REPOS/proj,sha,path)
 tree=ast.parse(src); funcs,classes=a.top_level_maps(tree)
 _,changed,_=a.r1_check(a.show_file(a.PROJECT_REPOS/proj,info["buggy_commit_id"],path),src)
 start=changed[0]
 print("="*90); print(proj,bid,path,start,"current",a.collect_helpers(a.PROJECT_REPOS/proj,sha,path,tree,start)[:2])
 # print class nodes referenced by current helper names
 same,cross,_=a.collect_helpers(a.PROJECT_REPOS/proj,sha,path,tree,start)
 names=set(same)|set(x.split(" <- ")[0] for x in cross)
 for n in sorted(names):
  node=funcs.get(n)
  if node is not None:
   print(" FUNC",n,"refs",sorted(a.referenced_names(node)))
  if n in classes:
   print(" CLASS",n,"refs",sorted(a.referenced_names(classes[n])))
