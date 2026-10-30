import re
from pathlib import Path

meta = Path(
    r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy\bugsinpy_meta\projects\youtube-dl\bugs"
)

for bid in ("3", "11", "43"):
    bugdir = meta / bid
    print("===== bug", bid, "=====")
    print("  entries:", sorted(p.name for p in bugdir.iterdir()))
    for sub in ("fixed", "buggy"):
        d = bugdir / sub
        if not d.exists():
            print("  ", sub, ": ABSENT")
            continue
        f = d / "youtube_dl" / "utils.py"
        if not f.exists():
            print("  ", sub, ": no utils.py; tree =", [str(p.relative_to(d)) for p in d.rglob("*.py")][:5])
            continue
        lines = f.read_text(errors="ignore").splitlines()
        for i, line in enumerate(lines):
            if re.match(r"^def (str_to_int|unescapeHTML|url_basename|int_or_none)\b", line):
                body = []
                for j in range(i, min(i + 8, len(lines))):
                    body.append(lines[j])
                print("  ", sub, "utils.py", i + 1)
                for b in body:
                    print("       ", b)
                break
    print()
