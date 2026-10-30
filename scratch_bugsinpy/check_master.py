import re
import subprocess
from pathlib import Path

REPO = Path(
    r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy\project_repos\youtube-dl"
)


def git(*args):
    return subprocess.run(
        ["git"] + list(args), cwd=str(REPO), capture_output=True, text=True
    )


git("fetch", "--depth", "1", "origin", "master")
git("checkout", "--force", "FETCH_HEAD")
print("HEAD now:", git("rev-parse", "HEAD").stdout.strip())
lines = (REPO / "youtube_dl" / "utils.py").read_text(errors="ignore").splitlines()
for i, line in enumerate(lines):
    if re.match(r"^def (str_to_int|int_or_none|preferredencoding|get_subprocess_encoding)\b", line):
        print("utils.py", i + 1, line)
        for j in range(i + 1, min(i + 7, len(lines))):
            print("      ", lines[j])
            if lines[j].startswith("def "):
                break
        print()
