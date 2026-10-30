"""Task A raw audit: every module-level binding / alias skipped by R2.

Read-only.  Does not change analyze_r2.py or any verdict.
"""

import ast
import sys
from pathlib import Path

import analyze_r2 as a

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

USABLE = {
    "youtube-dl": ["1", "3", "5", "7", "10", "11", "13", "15", "17", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "41", "43"],
    "PySnooper": ["3"],
    "tornado": ["9"],
    "cookiecutter": ["1", "3"],
    "fastapi": ["5", "6", "9", "10", "11", "16"],
    "black": ["9", "13", "16", "21"],
    "scrapy": ["11", "15", "17", "29", "35", "36", "38"],
    "thefuck": ["1", "2", "4", "5", "10", "15", "18", "21", "25", "26", "27", "30", "31", "32"],
    "keras": ["9"],
    "luigi": ["21"],
}


def dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class Auditor:
    def __init__(self, repo, sha):
        self.repo = repo
        self.sha = sha
        self.cache = {}

    def module(self, path):
        if path in self.cache:
            return self.cache[path]
        src = a.show_file(self.repo, self.sha, path)
        if src is None:
            self.cache[path] = None
            return None
        try:
            tree = ast.parse(src)
        except SyntaxError:
            self.cache[path] = None
            return None
        funcs, classes = a.top_level_maps(tree)
        assigns = {}
        imports = {}
        star_imports = []
        global_assigns = {}

        def add_assign(name, value, ctx, node):
            assigns.setdefault(name, []).append(
                {"value": value, "ctx": ctx, "node": node, "src": src}
            )

        def add_import(local, info):
            imports[local] = info

        def walk(stmts, ctx):
            for node in stmts:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    funcs[node.name] = node
                    declared = set()
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Global):
                            declared.update(sub.names)
                    if declared:
                        for sub in ast.walk(node):
                            if isinstance(sub, ast.Assign):
                                for target in sub.targets:
                                    if isinstance(target, ast.Name) and target.id in declared:
                                        global_assigns.setdefault(target.id, []).append(
                                            {"value": sub.value, "func": node.name, "src": src, "node": sub}
                                        )
                            elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name) and sub.target.id in declared and sub.value is not None:
                                global_assigns.setdefault(sub.target.id, []).append(
                                    {"value": sub.value, "func": node.name, "src": src, "node": sub}
                                )
                elif isinstance(node, ast.ClassDef):
                    classes[node.name] = node
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            add_assign(target.id, node.value, ctx, node)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                    add_assign(node.target.id, node.value, ctx, node)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        local = alias.asname or alias.name.split(".")[0]
                        add_import(local, {
                            "kind": "import",
                            "module": alias.name if alias.asname else alias.name.split(".")[0],
                            "original": alias.name.split(".")[-1],
                            "full": alias.name,
                        })
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == "*":
                            star_imports.append((node.level, node.module or "", ctx))
                        else:
                            local = alias.asname or alias.name
                            add_import(local, {
                                "kind": "from",
                                "level": node.level,
                                "module": node.module or "",
                                "original": alias.name,
                                "full": (node.module or "") + "." + alias.name,
                            })
                elif isinstance(node, ast.If):
                    walk(node.body, ctx + " / if")
                    walk(node.orelse, ctx + " / else")
                elif isinstance(node, ast.Try):
                    walk(node.body, ctx + " / try")
                    for handler in node.handlers:
                        walk(handler.body, ctx + " / except")
                    walk(node.orelse, ctx + " / else")
                    walk(node.finalbody, ctx + " / finally")
                elif isinstance(node, ast.With):
                    walk(node.body, ctx + " / with")
                elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                    walk(node.body, ctx + " / loop")
                    walk(node.orelse, ctx + " / loop-else")
                elif isinstance(node, ast.Match):
                    for case in node.cases:
                        walk(case.body, ctx + " / match")

        walk(tree.body, "module")
        info = {
            "path": path,
            "src": src,
            "tree": tree,
            "funcs": funcs,
            "classes": classes,
            "assigns": assigns,
            "imports": imports,
            "star_imports": star_imports,
            "global_assigns": global_assigns,
        }
        self.cache[path] = info
        return info

    def exists(self, path):
        return a.show_file(self.repo, self.sha, path) is not None

    def submodule(self, base, name):
        for cand in (base + "/" + name + ".py", base + "/" + name + "/__init__.py"):
            if self.exists(cand):
                return cand
        return None

    def lookup(self, path, name, seen=None):
        """Find a binding in a module; return a resolution tuple or None."""
        if seen is None:
            seen = set()
        key = (path, name)
        if key in seen:
            return None
        seen.add(key)
        mod = self.module(path)
        if mod is None:
            return None
        if name in mod["funcs"]:
            return ("function", path, name, None)
        if name in mod["classes"]:
            return ("class", path, name, None)
        if name in mod["assigns"]:
            return ("assign", path, name, mod["assigns"][name])
        if name in mod["global_assigns"]:
            return ("global_assign", path, name, mod["global_assigns"][name])
        if name in mod["imports"]:
            return self.resolve_import(path, name, seen)
        # A submodule imported implicitly by `from package import name`.
        if path.endswith("/__init__.py"):
            base = path[: -len("/__init__.py")]
            sub = self.submodule(base, name)
            if sub:
                return ("module", sub, name, None)
        # Star imports.
        for level, module, _ctx in mod["star_imports"]:
            base = a.resolve_project_module(path, level, module)
            if base is None:
                continue
            for cand in a.module_candidates(base):
                if self.exists(cand):
                    res = self.lookup(cand, name, seen)
                    if res:
                        return res
        return None

    def resolve_import(self, path, name, seen=None):
        mod = self.module(path)
        if mod is None:
            return None
        info = mod["imports"].get(name)
        if info is None:
            return None
        if info["kind"] == "import":
            target = info["module"]
            target_path = a.resolve_project_module(path, 0, target)
            if target_path and self.exists(target_path):
                return ("module", target_path, target, None)
            return ("external", None, target, None)
        base = a.resolve_project_module(path, info["level"], info["module"])
        if base is None:
            name2 = (info["module"] + "." if info["module"] else "") + info["original"]
            return ("external", None, name2, None)
        # First try the module itself, if it exists.
        for cand in a.module_candidates(base):
            if self.exists(cand):
                res = self.lookup(cand, info["original"], seen)
                if res:
                    return res
        # `from package import submodule`
        sub = self.submodule(base, info["original"])
        if sub:
            return ("module", sub, info["original"], None)
        return ("other", base, info["original"], None)


def rhs_text(item):
    src = item["src"]
    try:
        text = ast.get_source_segment(src, item["value"])
    except Exception:
        text = None
    if text is None:
        try:
            text = ast.unparse(item["value"])
        except Exception:
            text = "<unparse failed>"
    text = " ".join(text.split())
    if len(text) > 240:
        text = text[:237] + "..."
    return text


def attrs_on(node, base_name):
    found = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            d = dotted(sub)
            if d and d.split(".")[0] == base_name:
                found.append(d)
    return sorted(set(found))


def audit_bug(project, bug):
    meta = a.BUGSINPY_META / "projects" / project / "bugs" / bug
    info = a.bug_info(a.read_text_any(meta / "bug.info"))
    patch = a.read_text_any(meta / "bug_patch.txt")
    path = a.patch_changed_path(patch)
    sha = info["fixed_commit_id"]
    fixed_src = a.show_file(a.PROJECT_REPOS / project, sha, path)
    fixed_tree = ast.parse(fixed_src)
    _ok, changed, _reasons = a.r1_check(
        a.show_file(a.PROJECT_REPOS / project, info["buggy_commit_id"], path), fixed_src
    )
    start = changed[0]
    aud = Auditor(a.PROJECT_REPOS / project, sha)
    baseline = a.collect_helpers(a.PROJECT_REPOS / project, sha, path, fixed_tree, start)[2]
    baseline_names = set(x.split(" <- ", 1)[0] for x in baseline)

    same = set()
    cross = {}
    items = []
    seen = set()
    queue = [(path, start)]
    while queue:
        cur_path, cur_name = queue.pop(0)
        if (cur_path, cur_name) in seen:
            continue
        seen.add((cur_path, cur_name))
        mod = aud.module(cur_path)
        if mod is None:
            continue
        node = mod["funcs"].get(cur_name)
        if node is None:
            continue
        for ref in sorted(a.referenced_names(node)):
            if (cur_path, ref) == (path, start):
                continue
            res = aud.lookup(cur_path, ref)
            if res is None:
                continue
            kind, target_path, target_name, payload = res
            if kind in ("function", "class"):
                if target_path == path:
                    same.add(target_name)
                else:
                    cross[(target_path, target_name)] = (
                        ref + " <- " + target_path + ":" + target_name
                    )
                if kind == "function":
                    queue.append((target_path, target_name))
                continue
            if kind == "assign":
                for item in payload:
                    items.append({
                        "kind": "assignment",
                        "ref": ref,
                        "target_path": target_path,
                        "target_name": target_name,
                        "rhs": rhs_text(item),
                        "ctx": item["ctx"],
                        "used_by": cur_path + ":" + cur_name,
                        "local": target_path == path,
                    })
                continue
            if kind == "global_assign":
                for item in payload:
                    items.append({
                        "kind": "global-assignment",
                        "ref": ref,
                        "target_path": target_path,
                        "target_name": target_name,
                        "rhs": rhs_text(item),
                        "ctx": "global in " + item["func"],
                        "used_by": cur_path + ":" + cur_name,
                        "local": target_path == path,
                    })
                continue
            if kind == "module":
                attrs = attrs_on(node, ref)
                items.append({
                    "kind": "module-alias",
                    "ref": ref,
                    "target_path": target_path,
                    "target_name": target_name,
                    "rhs": "",
                    "ctx": "module alias",
                    "used_by": cur_path + ":" + cur_name,
                    "local": target_path == path,
                    "attrs": attrs,
                })
                for attr in attrs:
                    first = attr.split(".")[-1] if "." not in attr else attr.split(".", 1)[1]
                    first = first.split(".")[0]
                    ares = aud.lookup(target_path, first)
                    if ares:
                        akind, apath, aname, apayload = ares
                        if akind == "assign":
                            for item in apayload:
                                items.append({
                                    "kind": "attribute-assignment",
                                    "ref": attr,
                                    "target_path": apath,
                                    "target_name": aname,
                                    "rhs": rhs_text(item),
                                    "ctx": "via " + ref + " (" + item["ctx"] + ")",
                                    "used_by": cur_path + ":" + cur_name,
                                    "local": apath == path,
                                })
                        elif akind == "global_assign":
                            for item in apayload:
                                items.append({
                                    "kind": "attribute-global-assignment",
                                    "ref": attr,
                                    "target_path": apath,
                                    "target_name": aname,
                                    "rhs": rhs_text(item),
                                    "ctx": "via " + ref + " (global in " + item["func"] + ")",
                                    "used_by": cur_path + ":" + cur_name,
                                    "local": apath == path,
                                })
                        else:
                            items.append({
                                "kind": "attribute-" + akind,
                                "ref": attr,
                                "target_path": apath,
                                "target_name": aname,
                                "rhs": "",
                                "ctx": "via " + ref,
                                "used_by": cur_path + ":" + cur_name,
                                "local": apath == path,
                            })
                    else:
                        items.append({
                            "kind": "attribute-unresolved",
                            "ref": attr,
                            "target_path": target_path,
                            "target_name": first,
                            "rhs": "",
                            "ctx": "via " + ref,
                            "used_by": cur_path + ":" + cur_name,
                            "local": False,
                        })
                continue
            if kind in ("other", "external"):
                items.append({
                    "kind": kind,
                    "ref": ref,
                    "target_path": target_path,
                    "target_name": target_name,
                    "rhs": "",
                    "ctx": kind,
                    "used_by": cur_path + ":" + cur_name,
                    "local": target_path == path,
                    "baseline": ref in baseline_names,
                })
                continue

    # Deduplicate items by all visible fields.
    uniq = []
    seen_items = set()
    for item in items:
        key = tuple(sorted((k, str(v)) for k, v in item.items()))
        if key in seen_items:
            continue
        seen_items.add(key)
        uniq.append(item)

    return {
        "project": project,
        "bug": bug,
        "function": start,
        "path": path,
        "same": sorted(same),
        "cross": sorted(cross.values()),
        "r2_total": len(same) + len(cross),
        "items": uniq,
    }


def main():
    total = 0
    for project, bugs in USABLE.items():
        for bug in bugs:
            total += 1
            rec = audit_bug(project, bug)
            print("=== " + project + " bug " + bug + " | " + rec["function"] + " | " + rec["path"] + " ===")
            print("R2 counted total: " + str(rec["r2_total"]))
            print("same: " + str(rec["same"]))
            print("cross: " + str(rec["cross"]))
            project_items = [
                x for x in rec["items"]
                if x["kind"] not in ("external",)
            ]
            baseline_external = [
                x for x in rec["items"]
                if x["kind"] == "external" and x.get("baseline")
            ]
            if not project_items and not baseline_external:
                print("not-counted items: NONE")
            else:
                print("not-counted items:")
                for item in project_items:
                    local = "same-file" if item["local"] else "cross-module"
                    print(
                        "  - [%s] %s -> %s:%s | %s | RHS: %s | used by %s"
                        % (
                            item["kind"],
                            item["ref"],
                            item["target_path"],
                            item["target_name"],
                            local,
                            item["rhs"] or "(none)",
                            item["used_by"],
                        )
                    )
                    if item.get("attrs"):
                        print("      attrs: " + ", ".join(item["attrs"]))
                for item in baseline_external:
                    print(
                        "  - [external] %s -> %s | cross-module | RHS: (external import)"
                        % (item["ref"], item["target_name"])
                    )
            print("")
    print("TOTAL BUGS: " + str(total))


if __name__ == "__main__":
    main()
