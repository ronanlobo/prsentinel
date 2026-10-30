"""Task A: classify every project-level name skipped by R2.

Read-only.  Produces raw lists and direct/transitive dependency totals.
No verdict in results/ or notes/ is changed.
"""

import ast
import builtins
import sys

import analyze_r2 as a
from audit_task_a_raw import Auditor, USABLE, attrs_on, dotted, rhs_text

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BUILTINS = set(dir(builtins)) | {"unicode", "unichr", "long", "basestring", "xrange"}


def bound_names(expr):
    bound = set()
    for sub in ast.walk(expr):
        if isinstance(sub, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in sub.generators:
                for n in ast.walk(gen.target):
                    if isinstance(n, ast.Name):
                        bound.add(n.id)
        elif isinstance(sub, ast.Lambda):
            for arg in list(sub.args.args) + list(sub.args.kwonlyargs):
                bound.add(arg.arg)
            if sub.args.vararg:
                bound.add(sub.args.vararg.arg)
            if sub.args.kwarg:
                bound.add(sub.args.kwarg.arg)
    return bound


class Classifier:
    def __init__(self, aud):
        self.aud = aud

    def resolve_attr(self, path, node):
        d = dotted(node)
        if not d:
            return None
        root, _, rest = d.partition(".")
        res = self.aud.lookup(path, root)
        if res is None:
            return None
        kind, target_path, target_name, payload = res
        if kind == "module" and rest:
            cur = target_path
            for attr in rest.split("."):
                nxt = self.aud.lookup(cur, attr)
                if nxt is None:
                    return ("unresolved-attr", cur, attr, None)
                k, p, n, pl = nxt
                if k == "module":
                    cur = p
                    continue
                return nxt
            return ("module", cur, root, None)
        return res

    def resolve_callee(self, path, node):
        if isinstance(node, ast.Name):
            return self.aud.lookup(path, node.id)
        if isinstance(node, ast.Attribute):
            return self.resolve_attr(path, node)
        return None

    def record(self, state, status, reason, callee=None, direct=True):
        order = {"A": 0, "U": 1, "B": 2}
        if order[status] > order[state["status"]]:
            state["status"] = status
        if status == "B":
            if direct:
                state["direct_b"] = True
            else:
                state["transitive_b"] = True
            state["b_reasons"].append(reason)
        elif status == "U":
            state["u_reasons"].append(reason)
        if callee:
            state["callees"].append(callee)

    def payload(self, path, name, payload, state, seen):
        key = (path, name)
        if key in seen:
            return
        seen = seen | {key}
        child = {
            "status": "A",
            "direct_b": False,
            "transitive_b": False,
            "b_reasons": [],
            "u_reasons": [],
            "callees": [],
            "bound": set(),
        }
        for item in payload:
            child["bound"] = bound_names(item["value"])
            self.expr(path, item["value"], child, seen, item.get("ctx", ""))
        if child["status"] == "B":
            self.record(state, "B", "transitive-project-dependency:" + path + ":" + name, direct=False)
        elif child["status"] == "U":
            self.record(state, "U", "transitive-project-reference:" + path + ":" + name)
        for callee in child["callees"]:
            state["callees"].append(callee)

    def expr(self, path, node, state, seen, ctx=""):
        if node is None:
            return
        if isinstance(node, ast.Constant):
            self.record(state, "A", "literal")
            return
        if isinstance(node, ast.Name):
            if node.id in state["bound"]:
                return
            res = self.aud.lookup(path, node.id)
            if res is None:
                if node.id in BUILTINS:
                    self.record(state, "A", "builtin:" + node.id)
                elif node.id in MODULE_BUILTINS:
                    self.record(state, "A", "module-builtin:" + node.id)
                else:
                    self.record(state, "U", "unresolved-name:" + node.id)
                return
            kind, target_path, target_name, payload = res
            if kind == "external":
                self.record(state, "A", "external:" + str(target_name))
            elif kind == "other":
                self.record(state, "A", "other-module:" + str(target_path) + ":" + str(target_name))
            elif kind == "function":
                self.record(state, "U", "project-function-ref:" + target_path + ":" + target_name,
                            callee=target_path + ":" + target_name)
            elif kind == "class":
                self.record(state, "U", "project-class-ref:" + target_path + ":" + target_name,
                            callee=target_path + ":" + target_name)
            elif kind == "module":
                self.record(state, "U", "project-module-alias:" + target_path)
            elif kind in ("assign", "global_assign"):
                self.payload(target_path, target_name, payload, state, seen)
            else:
                self.record(state, "U", "unresolved:" + kind)
            return
        if isinstance(node, ast.Attribute):
            res = self.resolve_attr(path, node)
            if res is None:
                self.record(state, "U", "unresolved-attribute:" + str(dotted(node)))
                return
            kind, target_path, target_name, payload = res
            if kind == "external":
                self.record(state, "A", "external-attribute:" + str(target_name))
            elif kind in ("function", "class"):
                self.record(state, "U", "project-" + kind + "-ref:" + target_path + ":" + target_name,
                            callee=target_path + ":" + target_name)
            elif kind == "module":
                self.record(state, "U", "project-module-alias:" + target_path)
            elif kind in ("assign", "global_assign"):
                self.payload(target_path, target_name, payload, state, seen)
            elif kind == "unresolved-attr":
                self.record(state, "U", "unresolved-attribute:" + str(target_name))
            else:
                self.record(state, "U", "unresolved-attribute-kind:" + kind)
            return
        if isinstance(node, ast.Call):
            callee = self.resolve_callee(path, node.func)
            if callee is not None:
                kind, target_path, target_name, payload = callee
                if kind in ("function", "class"):
                    self.record(state, "B", "project-" + ("class-instantiation" if kind == "class" else "function-call") + ":" + target_path + ":" + target_name,
                                callee=target_path + ":" + target_name)
                elif kind in ("assign", "global_assign"):
                    # A callable project object (class-like factory, method result, etc.).
                    self.record(state, "B", "project-callable:" + target_path + ":" + target_name,
                                callee=target_path + ":" + target_name)
                    self.payload(target_path, target_name, payload, state, seen)
                elif kind == "module":
                    self.record(state, "U", "call-project-module:" + target_path)
                elif kind == "external":
                    self.record(state, "A", "external-call:" + str(target_name))
                elif kind == "other":
                    self.record(state, "A", "other-call:" + str(target_name))
                else:
                    self.record(state, "U", "unresolved-call:" + kind)
            else:
                self.record(state, "A", "builtin-or-unresolved-call")
            for arg in list(node.args) + [k.value for k in node.keywords]:
                self.expr(path, arg, state, seen, ctx + " / call-arg")
            return
        if isinstance(node, ast.Lambda):
            self.record(state, "A", "lambda-deferred")
            return
        if isinstance(node, ast.GeneratorExp):
            # The first iterable is evaluated when the generator is created.
            # A generator passed to set/list/tuple is also consumed immediately,
            # but for this audit we only need the outer iterable; body calls are
            # deferred and are not module-initialisation dependencies.
            for gen in node.generators[:1]:
                self.expr(path, gen.iter, state, seen, ctx + " / generator-outer")
            self.record(state, "A", "generator-deferred")
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
            if isinstance(node, ast.DictComp):
                self.expr(path, node.key, state, seen, ctx + " / comp-key")
                self.expr(path, node.value, state, seen, ctx + " / comp-value")
            else:
                self.expr(path, node.elt, state, seen, ctx + " / comp-elt")
            for gen in node.generators:
                self.expr(path, gen.iter, state, seen, ctx + " / comp-iter")
                for cond in gen.ifs:
                    self.expr(path, cond, state, seen, ctx + " / comp-if")
            return
        if isinstance(node, ast.JoinedStr):
            for v in node.values:
                self.expr(path, v, state, seen, ctx + " / fstring")
            return
        if isinstance(node, ast.FormattedValue):
            self.expr(path, node.value, state, seen, ctx + " / formatted")
            if node.format_spec is not None:
                self.expr(path, node.format_spec, state, seen, ctx + " / format-spec")
            return
        children = []
        for field, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                children.append(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        children.append(item)
        for child in children:
            self.expr(path, child, state, seen, ctx + " / " + type(node).__name__)
        if not children:
            self.record(state, "A", "ast:" + type(node).__name__)


def collect(project, bug):
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
    raw_items = []
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
            if kind in ("assign", "global_assign"):
                for item in payload:
                    raw_items.append({
                        "kind": "assignment" if kind == "assign" else "global-assignment",
                        "ref": ref,
                        "target_path": target_path,
                        "target_name": target_name,
                        "value": item["value"],
                        "src": item["src"],
                        "ctx": item["ctx"] if kind == "assign" else "global in " + item["func"],
                        "used_by": cur_path + ":" + cur_name,
                        "local": target_path == path,
                        "attrs": [],
                        "baseline": ref in baseline_names,
                    })
                continue
            if kind == "module":
                attrs = attrs_on(node, ref)
                raw_items.append({
                    "kind": "module-alias",
                    "ref": ref,
                    "target_path": target_path,
                    "target_name": target_name,
                    "value": None,
                    "src": "",
                    "ctx": "module alias",
                    "used_by": cur_path + ":" + cur_name,
                    "local": target_path == path,
                    "attrs": attrs,
                    "baseline": ref in baseline_names,
                })
                for attr in attrs:
                    first = attr.split(".", 1)[1].split(".")[0] if "." in attr else attr
                    ares = aud.lookup(target_path, first)
                    if ares is None:
                        raw_items.append({
                            "kind": "attribute-unresolved",
                            "ref": attr,
                            "target_path": target_path,
                            "target_name": first,
                            "value": None,
                            "src": "",
                            "ctx": "via " + ref,
                            "used_by": cur_path + ":" + cur_name,
                            "local": False,
                            "attrs": [],
                            "baseline": False,
                        })
                        continue
                    akind, apath, aname, apayload = ares
                    if akind in ("assign", "global_assign"):
                        for item in apayload:
                            raw_items.append({
                                "kind": "attribute-assignment" if akind == "assign" else "attribute-global-assignment",
                                "ref": attr,
                                "target_path": apath,
                                "target_name": aname,
                                "value": item["value"],
                                "src": item["src"],
                                "ctx": "via " + ref + " (" + item.get("ctx", "") + ")",
                                "used_by": cur_path + ":" + cur_name,
                                "local": apath == path,
                                "attrs": [],
                                "baseline": False,
                            })
                    else:
                        raw_items.append({
                            "kind": "attribute-" + akind,
                            "ref": attr,
                            "target_path": apath,
                            "target_name": aname,
                            "value": None,
                            "src": "",
                            "ctx": "via " + ref,
                            "used_by": cur_path + ":" + cur_name,
                            "local": apath == path,
                            "attrs": [],
                            "baseline": False,
                        })
                continue
            if kind in ("other", "external"):
                raw_items.append({
                    "kind": kind,
                    "ref": ref,
                    "target_path": target_path,
                    "target_name": target_name,
                    "value": None,
                    "src": "",
                    "ctx": kind,
                    "used_by": cur_path + ":" + cur_name,
                    "local": target_path == path,
                    "attrs": [],
                    "baseline": ref in baseline_names,
                })
                continue

    # Expand assignment RHS references to other module-level assignments.
    expanded = []
    seen_item = set()
    work = list(raw_items)
    while work:
        item = work.pop(0)
        key = (item["kind"], item["ref"], item["target_path"], item["target_name"], rhs_text(item) if item["value"] is not None else "")
        if key in seen_item:
            continue
        seen_item.add(key)
        expanded.append(item)
        if item["value"] is None:
            continue
        # Only follow project-level names/attributes inside assignment RHS.
        for sub in ast.walk(item["value"]):
            refs = []
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                refs.append(sub.id)
            elif isinstance(sub, ast.Attribute):
                d = dotted(sub)
                if d:
                    refs.append(d)
            for ref in refs:
                if "." in ref:
                    # resolve first component only for expansion; attribute resolution handled by classifier
                    ref = ref.split(".", 1)[0]
                res = aud.lookup(item["target_path"], ref)
                if res is None:
                    continue
                kind, tp, tn, payload = res
                if kind in ("assign", "global_assign"):
                    for child in payload:
                        work.append({
                            "kind": "assignment" if kind == "assign" else "global-assignment",
                            "ref": ref,
                            "target_path": tp,
                            "target_name": tn,
                            "value": child["value"],
                            "src": child["src"],
                            "ctx": "transitive via " + item["ref"] + " (" + child.get("ctx", "") + ")",
                            "used_by": item["used_by"],
                            "local": tp == path,
                            "attrs": [],
                            "baseline": ref in baseline_names,
                            "parent": item["ref"],
                        })

    clf = Classifier(aud)
    for item in expanded:
        kind = item["kind"]
        state = {
            "status": "A",
            "direct_b": False,
            "transitive_b": False,
            "b_reasons": [],
            "u_reasons": [],
            "callees": [],
            "bound": set(),
        }
        if kind in ("assignment", "global-assignment", "attribute-assignment", "attribute-global-assignment"):
            state["bound"] = bound_names(item["value"])
            clf.expr(item["target_path"], item["value"], state, set(), "")
            item["status"] = state["status"]
            item["direct_b"] = state["direct_b"]
            item["transitive_b"] = state["transitive_b"] and not state["direct_b"]
            item["reasons"] = state["b_reasons"] + state["u_reasons"]
            item["callees"] = sorted(set(state["callees"]))
        elif kind == "module-alias":
            item["status"] = "U"
            item["direct_b"] = False
            item["transitive_b"] = False
            item["reasons"] = ["project-module-alias:" + item["target_path"]]
            item["callees"] = []
        elif kind.startswith("attribute-"):
            if (item["target_path"], item["target_name"]) in PY3_STDLIB_ATTRS:
                item["status"] = "A"
                item["reasons"] = ["python3.13-stdlib-alias:" + item["target_path"] + ":" + item["target_name"]]
                item["callees"] = []
                item["direct_b"] = False
                item["transitive_b"] = False
            elif kind in ("attribute-class", "attribute-function"):
                item["status"] = "U"
                item["reasons"] = ["project-" + kind.split("-", 1)[1] + "-ref:" + item["target_path"] + ":" + item["target_name"]]
                item["callees"] = [item["target_path"] + ":" + item["target_name"]]
                item["direct_b"] = False
                item["transitive_b"] = False
            else:
                item["status"] = "U"
                item["reasons"] = [kind + ":" + item["target_path"] + ":" + item["target_name"]]
                item["callees"] = []
                item["direct_b"] = False
                item["transitive_b"] = False
        elif kind in ("external", "other"):
            item["status"] = "A"
            item["direct_b"] = False
            item["transitive_b"] = False
            item["reasons"] = [kind + ":" + str(item["target_name"])]
            item["callees"] = []
        else:
            item["status"] = "U"
            item["direct_b"] = False
            item["transitive_b"] = False
            item["reasons"] = [kind]
            item["callees"] = []

    return {
        "project": project,
        "bug": bug,
        "function": start,
        "path": path,
        "same": sorted(same),
        "cross": sorted(cross.values()),
        "r2_total": len(same) + len(cross),
        "items": expanded,
    }


# On the R4 target (Python 3.13) these names are stdlib objects even though the
# project also contains a dead fallback definition in an else/try branch.
PY3_STDLIB_ATTRS = {
    ("pysnooper/pycompat.py", "PathLike"),
}

# Names the interpreter injects into every module. They are constants for this
# audit, not project dependencies.
MODULE_BUILTINS = {
    "__file__", "__name__", "__package__", "__doc__", "__spec__", "__loader__",
}


def verdict(total):
    return "PASS" if total <= 3 else "EXCLUDED"


def main():
    all_recs = []
    for project, bugs in USABLE.items():
        for bug in bugs:
            rec = collect(project, bug)
            all_recs.append(rec)
            print("=== " + project + " bug " + bug + " | " + rec["function"] + " | " + rec["path"] + " ===")
            print("R2 current: " + str(rec["r2_total"]) + " (" + verdict(rec["r2_total"]) + ")")
            print("same: " + str(rec["same"]))
            print("cross: " + str(rec["cross"]))
            project_items = [x for x in rec["items"] if x["kind"] not in ("external",)]
            external_baseline = [x for x in rec["items"] if x["kind"] == "external" and x.get("baseline")]
            if not project_items and not external_baseline:
                print("not counted: NONE")
            else:
                print("not counted:")
                for item in project_items:
                    local = "same-file" if item["local"] else "cross-module"
                    tag = "B" if item["direct_b"] else ("B*" if item["transitive_b"] else ("U" if item["status"] == "U" else "A"))
                    if item["kind"] == "module-alias":
                        print("  - [%s] %s -> %s (-module) | %s | attrs: %s" % (
                            tag, item["ref"], item["target_path"], local, ", ".join(item["attrs"]) or "(none)"))
                    elif item["value"] is not None:
                        print("  - [%s] %s -> %s:%s | %s | RHS: %s | %s" % (
                            tag, item["ref"], item["target_path"], item["target_name"], local,
                            rhs_text(item), "; ".join(item["reasons"][:3])))
                    else:
                        print("  - [%s] %s -> %s:%s | %s | %s" % (
                            tag, item["ref"], item["target_path"], item["target_name"], local,
                            "; ".join(item["reasons"][:3])))
                    if item.get("callees") and item["status"] != "A":
                        print("      callees: " + ", ".join(item["callees"]))
                    if item.get("parent"):
                        print("      parent: " + item["parent"])
                for item in external_baseline:
                    print("  - [A] %s -> %s | cross-module | external import" % (item["ref"], item["target_name"]))
            direct = sorted(set(x["target_name"] for x in rec["items"] if x["direct_b"]))
            trans = sorted(set(x["target_name"] for x in rec["items"] if x["transitive_b"] and not x["direct_b"]))
            u_countable = sorted(set(
                x["target_name"] for x in rec["items"]
                if x["kind"] in ("attribute-class", "attribute-function")
                and (x["target_path"], x["target_name"]) not in PY3_STDLIB_ATTRS
            ))
            print("direct B names: " + str(direct))
            print("transitive B names: " + str(trans))
            print("countable U attribute helpers: " + str(u_countable))
            print("new total direct-B: " + str(rec["r2_total"] + len(direct)) + " (" + verdict(rec["r2_total"] + len(direct)) + ")")
            print("new total direct+transitive-B: " + str(rec["r2_total"] + len(direct) + len(trans)) + " (" + verdict(rec["r2_total"] + len(direct) + len(trans)) + ")")
            print("new total +U-attribute: " + str(rec["r2_total"] + len(direct) + len(trans) + len(u_countable)) + " (" + verdict(rec["r2_total"] + len(direct) + len(trans) + len(u_countable)) + ")")
            print("")
    print("TOTAL BUGS: " + str(len(all_recs)))
    print("")
    for label, key in [
        ("DIRECT-B", "direct"),
        ("DIRECT+TRANSITIVE-B", "trans"),
        ("DIRECT+TRANSITIVE-B+U-ATTRIBUTE", "u"),
    ]:
        changed = []
        for rec in all_recs:
            direct = sorted(set(x["target_name"] for x in rec["items"] if x["direct_b"]))
            trans = sorted(set(x["target_name"] for x in rec["items"] if x["transitive_b"] and not x["direct_b"]))
            u_countable = sorted(set(
                x["target_name"] for x in rec["items"]
                if x["kind"] in ("attribute-class", "attribute-function")
                and (x["target_path"], x["target_name"]) not in PY3_STDLIB_ATTRS
            ))
            if key == "direct":
                new = rec["r2_total"] + len(direct)
            elif key == "trans":
                new = rec["r2_total"] + len(direct) + len(trans)
            else:
                new = rec["r2_total"] + len(direct) + len(trans) + len(u_countable)
            if new > 3:
                changed.append((rec["project"], rec["bug"], rec["r2_total"], new, direct, trans, u_countable))
        print("=== " + label + " VERDICT CHANGES: " + str(len(changed)) + " ===")
        for project, bug, old, new, direct, trans, u_countable in changed:
            print("  %s bug %s: %d -> %d | B=%s | B*=%s | U=%s" % (
                project, bug, old, new, direct, trans, u_countable))
        print("  usable under this lens: " + str(len(all_recs) - len(changed)) + " of " + str(len(all_recs)))
        print("")


if __name__ == "__main__":
    main()
