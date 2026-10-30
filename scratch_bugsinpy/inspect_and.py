import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
meta=a.BUGSINPY_META/"projects"/"thefuck"/"bugs"/"26"
info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
src=a.show_file(a.PROJECT_REPOS/"thefuck",sha,"thefuck/shells.py")
tree=ast.parse(src); funcs,classes=a.top_level_maps(tree)
node=funcs["and_"]
print(ast.get_source_segment(src,node))
print("refs", sorted(a.referenced_names(node)))
print("collect", a.collect_helpers(a.PROJECT_REPOS/"thefuck",sha,"thefuck/shells.py",tree,"and_"))
print("=== all funcs ===")
print([n for n in funcs])
