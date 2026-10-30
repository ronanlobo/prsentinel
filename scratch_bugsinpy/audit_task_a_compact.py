"""Compact Task A per-bug classification, generated from audit_task_a_report."""

import sys

import audit_task_a_report as r
from audit_task_a_raw import USABLE

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def names(rec, pred):
    out = []
    seen = set()
    for item in rec["items"]:
        if not pred(item):
            continue
        key = (item["kind"], item["ref"], item["target_path"], item["target_name"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item["ref"] + " <- " + str(item["target_path"]) + ":" + str(item["target_name"]))
    return out


def main():
    for project, bugs in USABLE.items():
        for bug in bugs:
            rec = r.collect(project, bug)
            a = names(rec, lambda x: x["status"] == "A" and x["kind"] != "external")
            b = names(rec, lambda x: x["direct_b"])
            bs = names(rec, lambda x: x["transitive_b"] and not x["direct_b"])
            u = names(rec, lambda x: x["status"] == "U" and x["kind"] != "module-alias")
            u_mod = names(rec, lambda x: x["kind"] == "module-alias")
            ext = names(rec, lambda x: x["kind"] == "external" and x.get("baseline"))
            direct_new = rec["r2_total"] + len(set(x["target_name"] for x in rec["items"] if x["direct_b"]))
            broad_u = set(
                x["target_name"] for x in rec["items"]
                if x["kind"] in ("attribute-class", "attribute-function")
                and (x["target_path"], x["target_name"]) not in r.PY3_STDLIB_ATTRS
            )
            broad = rec["r2_total"] + len(set(x["target_name"] for x in rec["items"] if x["direct_b"])) + len(set(x["target_name"] for x in rec["items"] if x["transitive_b"] and not x["direct_b"])) + len(broad_u)
            print("%s bug %s [%s] current=%d directB=%d broad=%d" % (
                project, bug, rec["function"], rec["r2_total"], direct_new, broad))
            print("  A: " + ("; ".join(a) if a else "-"))
            print("  B: " + ("; ".join(b) if b else "-"))
            print("  B*: " + ("; ".join(bs) if bs else "-"))
            print("  U: " + ("; ".join(u) if u else "-"))
            if u_mod:
                print("  U-namespace: " + "; ".join(u_mod))
            if ext:
                print("  A-external-baseline: " + "; ".join(ext))
            print()


if __name__ == "__main__":
    main()
