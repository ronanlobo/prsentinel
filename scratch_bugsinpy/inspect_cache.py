import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
meta=a.BUGSINPY_META/"projects"/"thefuck"/"bugs"/"4"
info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
src=a.show_file(a.PROJECT_REPOS/"thefuck",sha,"thefuck/utils.py")
tree=ast.parse(src); funcs,classes=a.top_level_maps(tree)
node=classes["Cache"]
print(ast.get_source_segment(src,node)[:5000])
print("REFS", sorted(a.referenced_names(node)))
