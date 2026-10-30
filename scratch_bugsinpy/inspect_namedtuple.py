import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
for proj,bid,path in [("black","13","blib2to3/pgen2/tokenize.py"),("thefuck","25","thefuck/rules/mkdir_p.py")]:
 meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bid
 info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
 src=a.show_file(a.PROJECT_REPOS/proj,sha,path); tree=ast.parse(src)
 print("="*90); print(proj,bid)
 for node in tree.body:
  if isinstance(node, ast.Assign):
   txt=ast.get_source_segment(src,node) or ""
   if "namedtuple" in txt or any(x in txt for x in ("TokenInfo","Command")):
    print(txt[:1000])
 # references in changed func
 bsrc=a.show_file(a.PROJECT_REPOS/proj,info["buggy_commit_id"],path); _,ch,_=a.r1_check(bsrc,src); start=ch[0]
 funcs,_=a.top_level_maps(tree)
 print("changed",start,"refs",sorted(a.referenced_names(funcs[start])))
