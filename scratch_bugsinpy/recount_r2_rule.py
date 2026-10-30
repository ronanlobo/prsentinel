#!/usr/bin/env python3
"""Recompute R2 helper counts under the 2026-10-26 data-name clarification.

This is read-only with respect to results/ and notes/. It applies the prior
cumulative R2 layers (current helpers, module namespaces, project attributes,
data initialisers, namedtuples) with the clarification that a data name itself
never counts: the project function/class that initialises it counts once, and
that initialiser's function closure is followed. Classes remain single helpers;
methods and class-hierarchy dependencies are not counted separately, matching
the frozen R2 text.
"""

import ast
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_r2 as a
import audit_task_a_report as report
from audit_task_a_raw import Auditor, USABLE

OUT = Path(__file__).resolve().parent / "r2_new_counts.json"
PY3 = report.PY3_STDLIB_ATTRS


def key(path, name):
    return (str(path), str(name))


def namedtuple_rhs(path, name, aud):
    """True if module binding path:name is a project namedtuple definition."""
    mod = aud.module(path)
    if mod is None:
        return False
    items = mod.get("assigns", {}).get(name) or []
    for item in items:
        value = item["value"]
        if not isinstance(value, ast.Call):
            continue
        func = value.func
        if isinstance(func, ast.Name):
            fname = func.id
        elif isinstance(func, ast.Attribute):
            fname = func.attr
        else:
            continue
        if fname == "namedtuple":
            return True
    return False


def kind_of(aud, path, name):
    mod = aud.module(path)
    if mod is None:
        return None
    if name in mod["funcs"]:
        return "function"
    if name in mod["classes"]:
        return "class"
    if name in mod["assigns"] or name in mod.get("global_assigns", {}):
        return "assign"
    return None


def resolve_target(aud, path, name):
    """Resolve a name in a module to (kind, path, name, payload) or None."""
    return aud.lookup(path, name)


def add_function_closure(repo, sha, path, name, aud, state, source):
    """Add a project function's transitive helpers, namedtuples and data callees.

    Classes stay single helpers. Function closure is the existing frozen R2
    traversal (same/cross helpers), then each newly reached function is checked
    for namedtuple definitions and initialiser callees.
    """
    if key(path, name) in state["functions"]:
        return
    state["functions"].add(key(path, name))
    src = a.show_file(repo, sha, path)
    if src is None:
        return
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return
    _, _, _ = a.collect_helpers(repo, sha, path, tree, name)
    same, cross, _ = a.collect_helpers(repo, sha, path, tree, name)
    for helper in same:
        state["functions"].add(key(path, helper))
    for item in cross:
        local, target = item.split(" <- ", 1)
        tp, tn = target.rsplit(":", 1)
        k = kind_of(aud, tp, tn)
        if k == "class":
            state["classes"].add(key(tp, tn))
        elif k == "function":
            add_function_closure(repo, sha, tp, tn, aud, state, source)
        elif k == "assign":
            follow_assign(repo, sha, tp, tn, aud, state, source)
    # Namedtuple and initialiser references made directly by this function.
    funcs = None
    mod = aud.module(path)
    if mod:
        node = mod["funcs"].get(name)
        if node is not None:
            for ref in sorted(a.referenced_names(node)):
                res = aud.lookup(path, ref)
                if not res:
                    continue
                k, tp, tn, payload = res
                if k == "assign":
                    if namedtuple_rhs(tp, tn, aud):
                        state["namedtuples"].add(key(tp, tn))
                    else:
                        follow_assign(repo, sha, tp, tn, aud, state, source)
                elif k == "module":
                    state["namespaces"].add(str(tp))
                elif k == "class":
                    state["classes"].add(key(tp, tn))
                elif k == "function":
                    add_function_closure(repo, sha, tp, tn, aud, state, source)


def follow_assign(repo, sha, path, name, aud, state, source, seen=None):
    """Follow a project data assignment without counting the data name."""
    if seen is None:
        seen = set()
    k = key(path, name)
    if k in seen:
        return
    seen.add(k)
    if namedtuple_rhs(path, name, aud):
        state["namedtuples"].add(k)
        return
    mod = aud.module(path)
    if mod is None:
        return
    payloads = []
    if name in mod.get("assigns", {}):
        payloads.extend(mod["assigns"][name])
    if name in mod.get("global_assigns", {}):
        payloads.extend(mod["global_assigns"][name])
    for item in payloads:
        value = item["value"]
        for sub in ast.walk(value):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                res = aud.lookup(path, sub.id)
                if not res:
                    continue
                kk, tp, tn, _ = res
                if kk == "assign":
                    if namedtuple_rhs(tp, tn, aud):
                        state["namedtuples"].add(key(tp, tn))
                    else:
                        follow_assign(repo, sha, tp, tn, aud, state, source, seen)
                elif kk == "module":
                    state["namespaces"].add(str(tp))
                elif kk == "class":
                    state["classes"].add(key(tp, tn))
                elif kk == "function":
                    add_function_closure(repo, sha, tp, tn, aud, state, source)



def add_class_closure(repo, sha, path, name, aud, state, source):
    """Follow a data-initialiser class's project references.

    The class itself is one helper. Its methods are not separate helpers, but a
    project function/class they call must also be copied, so those references
    are followed. This is only used for a class that initialises a data name;
    module-attribute classes and existing class helpers remain single units.
    """
    k = key(path, name)
    if k in state["class_closures"]:
        return
    state["class_closures"].add(k)
    state["classes"].add(k)
    mod = aud.module(path)
    if mod is None:
        return
    node = mod["classes"].get(name)
    if node is None:
        return
    for ref in sorted(a.referenced_names(node)):
        res = aud.lookup(path, ref)
        if not res:
            continue
        kk, tp, tn, _payload = res
        if kk == "class":
            state["classes"].add(key(tp, tn))
            add_class_closure(repo, sha, tp, tn, aud, state, source)
        elif kk == "function":
            add_function_closure(repo, sha, tp, tn, aud, state, source)
        elif kk == "assign":
            if namedtuple_rhs(tp, tn, aud):
                state["namedtuples"].add(key(tp, tn))
            else:
                follow_assign(repo, sha, tp, tn, aud, state, source)
        elif kk == "module":
            state["namespaces"].add(str(tp))

def compute(project, bug):
    meta = a.BUGSINPY_META / "projects" / project / "bugs" / bug
    info = a.bug_info(a.read_text_any(meta / "bug.info"))
    sha = info["fixed_commit_id"]
    patch = a.read_text_any(meta / "bug_patch.txt")
    path = a.patch_changed_path(patch)
    repo = a.PROJECT_REPOS / project
    fixed_src = a.show_file(repo, sha, path)
    fixed_tree = ast.parse(fixed_src)
    _ok, changed, _ = a.r1_check(
        a.show_file(repo, info["buggy_commit_id"], path), fixed_src
    )
    start = changed[0]
    same, cross, not_counted = a.collect_helpers(repo, sha, path, fixed_tree, start)
    aud = Auditor(repo, sha)
    state = {
        "functions": set(),
        "classes": set(),
        "namespaces": set(),
        "namedtuples": set(),
        "initializers": set(),
        "class_closures": set(),
    }
    for n in same:
        state["functions"].add(key(path, n))
    for item in cross:
        _local, target = item.split(" <- ", 1)
        tp, tn = target.rsplit(":", 1)
        k = kind_of(aud, tp, tn)
        if k == "class":
            state["classes"].add(key(tp, tn))
        elif k == "function":
            state["functions"].add(key(tp, tn))
        elif k == "assign":
            follow_assign(repo, sha, tp, tn, aud, state, fixed_src)

    rec = report.collect(project, bug)
    for it in rec["items"]:
        if it["kind"] == "module-alias":
            state["namespaces"].add(str(it["target_path"]))
        elif it["kind"] in ("attribute-class", "attribute-function"):
            k = key(it["target_path"], it["target_name"])
            if k in PY3:
                continue
            kk = kind_of(aud, *k)
            if kk == "class":
                state["classes"].add(k)
            elif kk == "function":
                add_function_closure(repo, sha, k[0], k[1], aud, state, fixed_src)
            elif kk == "assign":
                follow_assign(repo, sha, k[0], k[1], aud, state, fixed_src)
        elif it["direct_b"] or it["transitive_b"]:
            if it["kind"] == "assignment" and namedtuple_rhs(
                it["target_path"], it["target_name"], aud
            ):
                state["namedtuples"].add(key(it["target_path"], it["target_name"]))
                continue
            for callee in it["callees"]:
                tp, tn = callee.rsplit(":", 1)
                kk = kind_of(aud, tp, tn)
                if kk == "class":
                    state["initializers"].add(key(tp, tn))
                    add_class_closure(repo, sha, tp, tn, aud, state, fixed_src)
                elif kk == "function":
                    state["initializers"].add(key(tp, tn))
                    add_function_closure(repo, sha, tp, tn, aud, state, fixed_src)
                elif kk == "assign":
                    follow_assign(repo, sha, tp, tn, aud, state, fixed_src)

    # A namedtuple item can be reported as a plain assignment with status A.
    for it in rec["items"]:
        if it["kind"] == "assignment" and namedtuple_rhs(
            it["target_path"], it["target_name"], aud
        ):
            state["namedtuples"].add(key(it["target_path"], it["target_name"]))

    helpers = set(state["functions"]) | set(state["classes"]) | set(state["initializers"]) | set(state["namedtuples"])
    total = len(helpers) + len(state["namespaces"])
    return {
        "project": project,
        "bug": bug,
        "function": start,
        "path": path,
        "current": len(same) + len(cross),
        "same": same,
        "cross": cross,
        "functions": sorted(":".join(k) for k in state["functions"]),
        "classes": sorted(":".join(k) for k in state["classes"]),
        "initializers": sorted(":".join(k) for k in state["initializers"]),
        "namedtuples": sorted(":".join(k) for k in state["namedtuples"]),
        "namespaces": sorted(state["namespaces"]),
        "not_counted": not_counted,
        "total": total,
        "verdict": "pass" if total <= 3 else "excluded",
    }


def main():
    rows = []
    for project, bugs in USABLE.items():
        for bug in bugs:
            rec = compute(project, bug)
            rows.append(rec)
            print(
                "%s|%s|%s|current=%d|funcs=%d|classes=%d|init=%d|nt=%d|ns=%d|TOTAL=%d|%s"
                % (
                    project,
                    bug,
                    rec["function"],
                    rec["current"],
                    len(rec["functions"]),
                    len(rec["classes"]),
                    len(rec["initializers"]),
                    len(rec["namedtuples"]),
                    len(rec["namespaces"]),
                    rec["total"],
                    rec["verdict"],
                )
            )
            if rec["total"] > 3:
                print("   init:", ", ".join(rec["initializers"]) or "-")
                print("   nt:", ", ".join(rec["namedtuples"]) or "-")
                print("   ns:", ", ".join(rec["namespaces"]) or "-")
    OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("WROTE", OUT)
    print("USABLE", sum(1 for r in rows if r["total"] <= 3), "OF", len(rows))
    print("EXCLUDED", [r["project"] + " " + r["bug"] for r in rows if r["total"] > 3])


if __name__ == "__main__":
    main()


