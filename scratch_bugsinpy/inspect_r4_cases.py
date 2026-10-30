import sys, json
sys.path.insert(0, r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy")
import analyze_r2 as a
for proj,bid in [("thefuck","1"),("scrapy","11"),("fastapi","5")]:
 meta=a.BUGSINPY_META/"projects"/proj/"bugs"/bid
 print("="*100); print(proj,bid)
 print("=== bug.info ==="); print(a.read_text_any(meta/"bug.info"))
 print("=== run_test.sh ==="); print(a.read_text_any(meta/"run_test.sh") if (meta/"run_test.sh").exists() else "(none)")
 print("=== bug_patch.txt ==="); print(a.read_text_any(meta/"bug_patch.txt")[:8000])
 info=a.bug_info(a.read_text_any(meta/"bug.info")); sha=info["fixed_commit_id"]
 path=a.patch_changed_path(a.read_text_any(meta/"bug_patch.txt"))
 print("=== fixed source",path,"==="); print(a.show_file(a.PROJECT_REPOS/proj,sha,path)[:8000])
 test=info.get("test_file","")
 print("=== test file",test,"==="); print((a.show_file(a.PROJECT_REPOS/proj,sha,test) or "(not found)")[:8000])
