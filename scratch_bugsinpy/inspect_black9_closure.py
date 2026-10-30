import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
meta=a.BUGSINPY_META/"projects"/"black"/"bugs"/"9"
info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
src=a.show_file(a.PROJECT_REPOS/"black",sha,"blib2to3/pgen2/driver.py")
tree=ast.parse(src); funcs,classes=a.top_level_maps(tree)
for n in ("load_packaged_grammar","load_grammar"):
 print("---",n,"---"); print(ast.get_source_segment(src,funcs[n])[:3000]); print("collect",a.collect_helpers(a.PROJECT_REPOS/"black",sha,"blib2to3/pgen2/driver.py",tree,n))
