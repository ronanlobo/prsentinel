"""One-line Task A summary, generated from the same classifier as the report."""

import sys

import audit_task_a_report as r
from audit_task_a_raw import USABLE

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def uniq(rec, pred, field="ref"):
    seen = set()
    out = []
    for item in rec["items"]:
        if pred(item):
            value = item[field]
            if value not in seen:
                seen.add(value)
                out.append(value)
    return ",".join(out) if out else "-"


def main():
    for project, bugs in USABLE.items():
        for bug in bugs:
            rec = r.collect(project, bug)
            direct = uniq(rec, lambda x: x["direct_b"], "target_name")
            trans = uniq(rec, lambda x: x["transitive_b"] and not x["direct_b"], "target_name")
            u = uniq(
                rec,
                lambda x: x["kind"] in ("attribute-class", "attribute-function")
                and (x["target_path"], x["target_name"]) not in r.PY3_STDLIB_ATTRS,
                "target_name",
            )
            a = uniq(rec, lambda x: x["status"] == "A" and x["kind"] != "module-alias", "ref")
            direct_new = rec["r2_total"] + len([x for x in direct.split(",") if x != "-"])
            broad_new = direct_new + len([x for x in trans.split(",") if x != "-"]) + len([x for x in u.split(",") if x != "-"])
            print("|".join([
                project,
                str(bug),
                rec["function"],
                str(rec["r2_total"]),
                a,
                direct,
                trans,
                u,
                str(direct_new),
                str(broad_new),
            ]))


if __name__ == "__main__":
    main()
