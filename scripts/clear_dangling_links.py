"""Find and clear FieldMate links that point at documents which no longer exist.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/clear_dangling_links.py
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/clear_dangling_links.py --yes

Dry run without `--yes`.

WHY THIS EXISTS

A visit carries links to the work done during it - the stock count, the merchandising audit, the
geo-fence exception. Frappe validates every one of those when the document is saved, so a single
link whose target has been removed stops the rep checking out of the shop. The rep is standing at
a counter and the app will not let them leave.

Targets go missing on a test site for ordinary reasons: somebody deletes a document in Desk to
re-run a step, or a test suite clears its own tables. This puts the visit back into a state the
app can save, without touching anything that is still real.

WHAT IT DOES NOT DO

It clears the reference and nothing else. It does not invent a replacement, does not mark work
done that was not done, and does not touch a link whose target exists. A stock task whose count
has gone back to Pending is the truth - the count really is not there any more.
"""

import sys

import frappe

from _guard import require_test_site

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
    if not arg.startswith("--"):
        SITE = arg

GO = "--yes" in sys.argv

# Parent DocType -> the Link fields on it that can dangle, with the DocType each points at.
# Deliberately explicit rather than walked from the meta: this script writes to documents, and
# a loop over every Link field on every FieldMate DocType would eventually clear something that
# mattered.
SINGLE_LINKS = {
    "FieldMate Visit": [
        ("geo_fence_exception", "FieldMate Geo Fence Exception"),
        ("merchandising_audit", "FieldMate Merchandising Audit"),
        ("day_start", "FieldMate Day Start"),
        ("journey_plan", "FieldMate Journey Plan"),
        ("beat", "FieldMate Beat"),
        ("deviation_reason", "FieldMate Deviation Reason"),
        ("no_order_reason", "FieldMate No Order Reason"),
        ("device_id", "FieldMate Device Registry"),
    ],
    "FieldMate Order": [
        ("visit", "FieldMate Visit"),
    ],
    "FieldMate Collection": [
        ("visit", "FieldMate Visit"),
    ],
}

# Child tables carrying a Dynamic Link: (child doctype, doctype field, name field).
DYNAMIC_LINKS = [
    ("FieldMate Visit Task", "reference_doctype", "reference_name"),
]


def scan() -> list[dict]:
    found = []

    for parent, fields in SINGLE_LINKS.items():
        if not frappe.db.exists("DocType", parent):
            continue
        for field, target in fields:
            if not frappe.get_meta(parent).has_field(field):
                continue
            rows = frappe.get_all(parent, filters={field: ["is", "set"]},
                                  fields=["name", field], limit_page_length=0)
            for row in rows:
                value = row.get(field)
                if value and not frappe.db.exists(target, value):
                    found.append({"kind": "link", "parent": parent, "name": row.name,
                                  "field": field, "target": target, "value": value})

    for child, dt_field, name_field in DYNAMIC_LINKS:
        if not frappe.db.exists("DocType", child):
            continue
        rows = frappe.db.sql(f"""
            select name, parent, parenttype, idx, `{dt_field}` as dt, `{name_field}` as dn
            from `tab{child}`
            where `{name_field}` is not null and `{name_field}` != ''
        """, as_dict=True)
        for row in rows:
            if not row.dt:
                continue
            if not frappe.db.exists(row.dt, row.dn):
                found.append({"kind": "dynamic", "parent": child, "name": row.name,
                              "field": name_field, "target": row.dt, "value": row.dn,
                              "owner_doc": f"{row.parenttype} {row.parent} row #{row.idx}",
                              "dt_field": dt_field})

    return found


def clear(entry: dict) -> None:
    if entry["kind"] == "dynamic":
        frappe.db.set_value(entry["parent"], entry["name"],
                            {entry["dt_field"]: None, entry["field"]: None},
                            update_modified=False)
    else:
        frappe.db.set_value(entry["parent"], entry["name"], entry["field"], None,
                            update_modified=False)


def main() -> None:
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")

    print(f"\nDangling FieldMate links on {SITE}"
          + ("" if GO else "   (dry run - nothing will be changed)"))
    print("-" * 74)

    found = scan()
    if not found:
        print("  none - every FieldMate link points at a document that exists")
    for entry in found:
        where = entry.get("owner_doc") or f"{entry['parent']} {entry['name']}"
        print(f"  {where}")
        print(f"      {entry['field']} -> {entry['target']} / {entry['value']}   (missing)")

    print("-" * 74)
    print(f"  {len(found)} dangling link(s)")

    if found and not GO:
        print("\nRe-run with --yes to clear them.\n")
    elif found:
        for entry in found:
            clear(entry)
        frappe.db.commit()
        print(f"\n  cleared {len(found)} reference(s). Nothing else was changed.\n")

    frappe.destroy()


if __name__ == "__main__":
    main()
