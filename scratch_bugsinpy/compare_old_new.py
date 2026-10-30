"""Compare the OLD R1/R2 heuristic with the NEW AST-diff method, side by side.

OLD: function name taken from a regex over the raw diff lines
     (^[+ -]def NAME( )  -- which also matches CONTEXT lines),
     helpers = every ast.Name loaded inside that function that is a
     top-level name of the same file (no transitive resolution).

NEW: function name = the top-level function whose AST differs between the
     buggy commit and the fixed commit,
     helpers = project-defined top-level functions/classes referenced
     transitively inside the fixed file (constants, imported names,
     stdlib and methods excluded).
"""

import ast
import re
import subprocess
from pathlib import Path

SCRATCH = Path(
    r"C:\Users\Ronan Lobo\Desktop\capstone project\prsentinel\scratch_bugsinpy"
)
META = SCRATCH / "bugsinpy_meta" / "projects" / "youtube-dl" / "bugs"
REPO = SCRATCH / "project_repos" / "youtube-dl"

BUGS = ["11", "17", "21", "3", "37", "43", "5", "6"]


def git(*args):
    return subprocess.run(
        ["git"] + list(args), cwd=str(REPO), capture_output=True, text=True
    )


def checkout(commit):
    git("fetch", "--depth", "1", "origin", commit)
    git("checkout", "--force", commit)


def top_level(tree):
    funcs = {}
    classes = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node
        elif isinstance(node, ast.ClassDef):
            classes.add(node.name)
    return funcs, classes


def changed_by_ast(buggy_src, fixed_src):
    buggy = ast.parse(buggy_src)
    fixed = ast.parse(fixed_src)
    bf, _ = top_level(buggy)
    ff, _ = top_level(fixed)
    out = []
    for name in sorted(ff):
        if name not in bf:
            out.append((name, "added"))
        elif ast.dump(bf[name]) != ast.dump(ff[name]):
            out.append((name, "modified"))
    return out


def old_helpers(tree, funcname):
    funcs, classes = top_level(tree)
    node = funcs.get(funcname)
    if node is None:
        return None
    refs = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            refs.add(sub.id)
    return sorted(r for r in refs if (r in funcs and r != funcname) or r in classes)


def new_helpers(tree, funcname):
    funcs, classes = top_level(tree)
    constants = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            constants.add(node.target.id)

    def local_bound(node):
        bound = set()
        for sub in ast.walk(node):
            if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(sub.name)
            elif isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
                bound.add(sub.id)
            elif isinstance(sub, ast.arg):
                bound.add(sub.arg)
            elif isinstance(sub, ast.ExceptHandler) and sub.name:
                bound.add(sub.name)
            elif isinstance(sub, ast.Import):
                for alias in sub.names:
                    bound.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(sub, ast.ImportFrom):
                for alias in sub.names:
                    bound.add(alias.asname or alias.name)
        return bound

    helpers = set()
    seen = set()
    queue = [funcname]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        node = funcs.get(current)
        if node is None:
            continue
        bound = local_bound(node)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                name = sub.id
                if name in bound or name == funcname or name in constants:
                    continue
                if name in funcs and name not in seen:
                    helpers.add(name)
                    queue.append(name)
                elif name in classes:
                    helpers.add(name)
    return sorted(helpers)


for bid in BUGS:
    bugdir = META / bid
    info = (bugdir / "bug.info").read_text()
    buggy_sha = re.search(r"buggy_commit_id\s*=\s*\"([a-f0-9]+)\"", info).group(1)
    fixed_sha = re.search(r"fixed_commit_id\s*=\s*\"([a-f0-9]+)\"", info).group(1)
    patch = (bugdir / "bug_patch.txt").read_text(errors="ignore")

    header = ""
    for line in patch.splitlines():
        if line.startswith("@@"):
            header = line
            break

    old_name = None
    for m in re.finditer(r"^[+ -](def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\()", patch, re.M):
        old_name = m.group(2)

    checkout(buggy_sha)
    buggy_src = (REPO / "youtube_dl" / "utils.py").read_text(errors="ignore")
    checkout(fixed_sha)
    fixed_src = (REPO / "youtube_dl" / "utils.py").read_text(errors="ignore")
    fixed_tree = ast.parse(fixed_src)

    print("===== bug " + bid + " =====")
    print("  hunk header           : " + header)
    print("  OLD function (regex)  : " + str(old_name))
    print("  OLD helpers           : " + str(old_helpers(fixed_tree, old_name)))
    for name, how in changed_by_ast(buggy_src, fixed_src):
        print(
            "  NEW function (AST)    : "
            + name
            + " ("
            + how
            + ")  helpers="
            + str(new_helpers(fixed_tree, name))
        )
    print()
