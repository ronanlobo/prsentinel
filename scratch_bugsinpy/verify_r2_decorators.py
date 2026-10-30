"""Task 1 verification: decorators and transitive cross-module helpers.

Read-only. Prints, for thefuck bugs 1, 11 and 18:
  - every decorator on the changed function and where its name resolves;
  - the helpers the current script reports;
  - the same-file / cross-module closure when helpers of helpers are followed
    across modules, with every edge shown.
"""

import ast
import sys

import analyze_r2 as a

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = a.PROJECT_REPOS / "thefuck"
META = a.BUGSINPY_META / "projects" / "thefuck" / "bugs"

_cache = {}


def load(sha, path):
    key = (sha, path)
    if key in _cache:
        return _cache[key]
    src = a.show_file(REPO, sha, path)
    if src is None:
        _cache[key] = None
        return None
    tree = ast.parse(src)
    funcs, classes = a.top_level_maps(tree)
    mod = {
        "path": path,
        "tree": tree,
        "funcs": funcs,
        "classes": classes,
        "constants": a.module_constants(tree),
        "imports": a.module_import_map(tree),
    }
    _cache[key] = mod
    return mod


def resolve(sha, mod, name):
    if name not in mod["imports"]:
        return None
    level, module, original = mod["imports"][name]
    modpath = a.resolve_project_module(mod["path"], level, module)
    if modpath is None:
        return None
    for cand in a.module_candidates(modpath):
        target = load(sha, cand)
        if target is None:
            continue
        if original in target["funcs"]:
            return target, "function", original
        if original in target["classes"]:
            return target, "class", original
        if original in target["constants"]:
            return target, "constant", original
        return target, "other", original
    return None


def describe_name(sha, mod, name):
    if name in mod["funcs"]:
        return "same-file function"
    if name in mod["classes"]:
        return "same-file class"
    if name in mod["constants"]:
        return "module constant (not a helper)"
    result = resolve(sha, mod, name)
    if result is None:
        return "not a project import (builtin/third-party)"
    target, kind, original = result
    return kind + " " + target["path"] + ":" + original


def walk(sha, start_path, start_name):
    same, cross, not_counted = set(), {}, set()
    edges = []
    seen = set()
    queue = [(start_path, start_name)]
    while queue:
        path, name = queue.pop(0)
        if (path, name) in seen:
            continue
        seen.add((path, name))
        mod = load(sha, path)
        node = mod["funcs"].get(name)
        if node is None:
            continue
        for ref in sorted(a.referenced_names(node)):
            if (path, ref) == (start_path, start_name):
                continue
            if ref in mod["constants"]:
                not_counted.add((path, ref, "module constant/alias"))
                continue
            if ref in mod["funcs"] or ref in mod["classes"]:
                kind = "function" if ref in mod["funcs"] else "class"
                if path == start_path:
                    same.add(ref)
                else:
                    cross[(path, ref)] = kind
                edges.append((name, path, ref, path, kind))
                if kind == "function":
                    queue.append((path, ref))
                continue
            result = resolve(sha, mod, ref)
            if result is None:
                continue
            target, kind, original = result
            target_path = target["path"]
            if kind == "constant":
                not_counted.add((target_path, original, "module constant/alias"))
                edges.append((name, path, original, target_path, "constant"))
                continue
            if kind == "other":
                continue
            if target_path == start_path:
                same.add(original)
            else:
                cross[(target_path, original)] = kind
            edges.append((name, path, original, target_path, kind))
            if kind == "function":
                queue.append((target_path, original))
    return same, cross, not_counted, edges


for bid in ("1", "11", "18"):
    print("===== thefuck bug " + bid + " =====")
    info = a.bug_info(a.read_text_any(META / bid / "bug.info"))
    patch = a.read_text_any(META / bid / "bug_patch.txt")
    path = a.patch_changed_path(patch)
    sha = info["fixed_commit_id"]
    src = a.show_file(REPO, sha, path)
    tree = ast.parse(src)
    funcs, _classes = a.top_level_maps(tree)
    _ok, changed, _reasons = a.r1_check(
        a.show_file(REPO, info["buggy_commit_id"], path), src
    )
    func = changed[0]
    node = funcs[func]
    mod = load(sha, path)

    print("file: " + path)
    print("function: " + func)
    print("decorators:")
    if not node.decorator_list:
        print("    (none)")
    for dec in node.decorator_list:
        text = ast.unparse(dec)
        print("    " + text)
        names = sorted(
            {
                n.id
                for n in ast.walk(dec)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
            }
        )
        for name in names:
            print("        " + name + " -> " + describe_name(sha, mod, name))

    current_same = a.same_file_helpers(tree, func)
    current_cross, current_not_counted = a.cross_module_helpers(
        REPO, sha, path, tree, func, current_same
    )
    print("old-logic same-file helpers: " + str(current_same))
    print("old-logic cross-module helpers: " + str(current_cross))
    print(
        "old-logic R2 total: "
        + str(len(current_same) + len(current_cross))
    )

    fixed_same, fixed_cross, fixed_not_counted = a.collect_helpers(
        REPO, sha, path, tree, func
    )
    print("fixed script same-file helpers: " + str(fixed_same))
    print("fixed script cross-module helpers: " + str(fixed_cross))
    print(
        "fixed script R2 total: "
        + str(len(fixed_same) + len(fixed_cross))
    )
    print("fixed script not counted: " + str(fixed_not_counted))

    same, cross, not_counted, edges = walk(sha, path, func)
    cross_list = sorted(p + ":" + n for (p, n) in cross)
    print("transitive same-file helpers (" + str(len(same)) + "): " + str(sorted(same)))
    print(
        "transitive cross-module helpers ("
        + str(len(cross_list))
        + "): "
        + str(cross_list)
    )
    print("transitive R2 total: " + str(len(same) + len(cross_list)))
    print("edges:")
    for (src_name, src_path, dst_name, dst_path, kind) in edges:
        print(
            "    "
            + src_path
            + ":"
            + src_name
            + " -> "
            + dst_path
            + ":"
            + dst_name
            + " ("
            + kind
            + ")"
        )
    print("not counted: " + str(sorted(not_counted)))
    print("")
