import re
import subprocess
from pathlib import Path

repo = Path(
    r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy\project_repos\youtube-dl"
)
meta = Path(
    r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy\bugsinpy_meta\projects\youtube-dl\bugs"
)

for bid in ("11", "43"):
    info = (meta / bid / "bug.info").read_text()
    fixed = re.search(r"fixed_commit_id\s*=\s*\"([a-f0-9]+)\"", info).group(1)
    subprocess.run(["git", "fetch", "--depth", "1", "origin", fixed], cwd=str(repo), capture_output=True)
    subprocess.run(["git", "checkout", "--force", fixed], cwd=str(repo), capture_output=True)
    print("===== bug", bid, "fixed", fixed, "=====")
    for fname in ("youtube_dl/utils.py", "youtube_dl/compat.py"):
        p = repo / fname
        if not p.exists():
            continue
        lines = p.read_text(errors="ignore").splitlines()
        for i, line in enumerate(lines):
            if re.match(r"^def (int_or_none|str_to_int|unescapeHTML|_htmlentity_transform|url_basename)\b", line):
                print(fname, i + 1, line)
                for j in range(i + 1, min(i + 6, len(lines))):
                    print("      ", lines[j])
                    if lines[j].strip().startswith("def "):
                        break
    print()
