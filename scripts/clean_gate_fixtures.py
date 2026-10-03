"""Remove what the gate scripts left behind.

The gates say they roll back. They do not: `build_fixtures` calls `frappe.db.commit()`, which
makes the `frappe.db.rollback()` in `main()` a no-op for everything created before it. Six runs
of gate2 left 240 outlets, 120 users and 120 beats on testerp2, and tripped Frappe's
user-creation throttle so the test suite could not run either.

The gates themselves now clean up after themselves. This script clears what the older runs left.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/clean_gate_fixtures.py [site] [--yes]

Without `--yes` it only reports. Everything it targets is matched by the `uid()` prefixes the
gates generate — `G2-` through `G9-`, and `@fieldmate.test` — so real data cannot be caught by it.
"""

import sys

import frappe

from _guard import require_test_site

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
    if not arg.startswith("--"):
        SITE = arg

GO = "--yes" in sys.argv

def targets(prefix: str = "G_"):
    """What to remove, newest dependency first: a beat holds outlets, a field user holds a login.

    `prefix` is the gate's own `uid()` stem - "G2", "G5", "G6" - or "G_" for all of them, which
    is a single-character SQL wildcard rather than a regex.
    """
    return [
        # Phase 8 first: nothing links to these, and Gate 8 writes thousands of them.
        ("FieldMate Alert Log", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Alert Rule", {"rule_name": ["like", f"{prefix}-RULE-%"]}),
        ("FieldMate KPI Snapshot", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),

        # Phase 7 next: a payout links to an achievement, which links to a plan, which
        # links to the plan above it. Children before parents, or the cascade refuses to come
        # apart - and Gate 7 builds 250 of them.
        ("FieldMate Incentive Payout", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Expense Claim", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Achievement", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        # Leaves carry a field_user; the nodes above them do not, so they are matched on the
        # plan name the gates generate instead.
        ("FieldMate Target Plan", {"plan_name": ["like", f"{prefix}-PLAN-%"]}),
        ("FieldMate Incentive Scheme", {"scheme_name": ["like", f"{prefix}-INC-%"]}),

        # Phase 9 next. A credit note links to a claim, a claim links to ledger rows, and the
        # ledger rows link to the orders further down this list - so the whole chain has to come
        # apart from the top or Frappe refuses at the first back-link it meets.
        ("Sales Invoice", {"fm_source_key": ["like", "CLAIM:%"],
                           "customer": ["like", f"{prefix}-DIST-%"]}),
        ("FieldMate Order Ingest Log", {"acted_by": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Claim", {"customer": ["like", f"{prefix}-DIST-%"]}),
        ("FieldMate Portal User", {"name": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Scheme Ledger", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Scheme", {"scheme_name": ["like", f"{prefix}-SCH-%"]}),
        ("FieldMate Order Approval Rule", {"rule_name": ["like", f"{prefix}-RULE-%"]}),

        ("FieldMate Van Settlement", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Van Load", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Retailer Stock", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Collection Deposit", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Collection", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Order", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Visit", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Location Trail", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Day End", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Day Start", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Journey Plan", {"field_user": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("FieldMate Beat", {"beat_name": ["like", f"{prefix}-BEAT-%"]}),
        ("FieldMate Outlet", {"outlet_name": ["like", f"{prefix}-SHOP-%"]}),
        ("FieldMate Field User", {"name": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        ("User", {"name": ["like", f"{prefix.lower()}%@fieldmate.test"]}),
        # A tree, so a parent whose children are still standing refuses to go. The retry pass in
        # `purge` is what gets the upper nodes on the second time round.
        ("Sales Person", {"sales_person_name": ["like", f"{prefix}-%"]}),
        ("Holiday List", {"name": ["like", f"{prefix}-HOL-%"]}),
        # No FieldMate Distributor Profile above this any more - the Customer IS the distributor.
        ("Customer", {"customer_name": ["like", f"{prefix}-DIST-%"]}),
        ("Item Price", {"item_code": ["like", f"{prefix}-ITEM-%"]}),
        ("FieldMate Product Catalogue", {"catalogue_name": ["like", f"{prefix}-CAT-%"]}),
        ("Item", {"item_code": ["like", f"{prefix}-ITEM-%"]}),
        ("Territory", {"name": ["like", f"{prefix}-TERR-%"]}),
    ]


def purge(prefix: str = "G_", quiet: bool = False, passes: int = 3) -> int:
    """Delete one gate's fixtures. Called by the gates themselves, in a finally block.

    The gates commit their fixtures - some services they exercise commit internally anyway, so a
    transaction that survives to the end was never on offer - which is why `frappe.db.rollback()`
    alone left 868 records on testerp2 across six runs. This is the part that actually cleans up.

    It runs more than once. Two of the things the gates build are trees - Sales Person, and a
    cascaded Target Plan pointing at the plan above it - and a parent whose children are still
    standing refuses to be cancelled, whatever order this list is in. Sorting the list by depth
    would be a third place that has to know the shape of the data; retrying while progress is
    being made does not, and stops as soon as a pass removes nothing.
    """
    removed = failed = 0
    for _attempt in range(passes):
        moved = 0
        failed = 0
        for doctype, filters in targets(prefix):
            try:
                names = frappe.get_all(doctype, filters=filters, pluck="name")
            except Exception:
                continue
            for name in names:
                try:
                    doc = frappe.get_doc(doctype, name)
                    if doc.meta.is_submittable and doc.docstatus == 1:
                        doc.flags.ignore_permissions = True
                        doc.cancel()
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
                                      delete_permanently=True)
                    moved += 1
                except Exception:
                    failed += 1
            frappe.db.commit()

        removed += moved
        if not moved or not failed:
            break

    if not quiet:
        print(f"  cleaned up {removed} fixtures"
              + (f", {failed} left behind" if failed else ""))
    return removed


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")

    print(f"\nGate fixtures on {SITE}{'' if GO else '   (dry run — nothing will be deleted)'}")
    print("-" * 70)

    total = removed = failed = 0
    for doctype, filters in targets():
        try:
            names = frappe.get_all(doctype, filters=filters, pluck="name")
        except Exception as e:
            print(f"  {doctype:34} skipped: {str(e)[:40]}")
            continue
        if not names:
            continue
        total += len(names)
        print(f"  {doctype:34} {len(names)}")

        if not GO:
            continue

        for name in names:
            try:
                doc = frappe.get_doc(doctype, name)
                if doc.meta.is_submittable and doc.docstatus == 1:
                    doc.flags.ignore_permissions = True
                    doc.cancel()
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
                                  delete_permanently=True)
                removed += 1
            except Exception:
                failed += 1
        frappe.db.commit()

    print("-" * 70)
    if GO:
        print(f"removed {removed}, could not remove {failed}\n")
    else:
        print(f"{total} records would be removed. Re-run with --yes to do it.\n")

    frappe.destroy()


if __name__ == "__main__":
    main()
