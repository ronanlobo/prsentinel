import sys, ast
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
for proj,bid in [("PySnooper","3"),("black","9"),("black","13")]:
 meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bid
 info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
 path=a.patch_changed_path(a.read_text_any(meta/"bug_patch.txt"))
 print("="*90); print(proj,bid,path)
 if proj=="PySnooper":
  print(a.show_file(a.PROJECT_REPOS/proj,sha,"pysnooper/utils.py")[:6000])
 elif proj=="black" and bid=="9":
  print(a.show_file(a.PROJECT_REPOS/proj,sha,"blib2to3/pgen2/driver.py")[:5000])
  print("--- pygram ---")
  print(a.show_file(a.PROJECT_REPOS/proj,sha,"blib2to3/pygram.py")[:4000])
