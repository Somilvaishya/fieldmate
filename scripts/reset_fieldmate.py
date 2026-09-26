"""Wipe FieldMate back to an empty app, so testing can start from zero.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/reset_fieldmate.py            # report only
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/reset_fieldmate.py --yes      # do it
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/reset_fieldmate.py --yes --keep-masters

**Read this before running it with --yes.** It deletes documents permanently and there is no
undo. Without `--yes` it only counts, which is how you should look at it first.

WHAT IT TOUCHES

  Everything in the FieldMate module. All 74 DocTypes, in dependency order, deepest first.

  Plus the handful of ERPNext and HRMS documents FieldMate itself posted. Those are found by
  `fm_source_key` - the idempotency stamp this app writes on everything it creates - so a Sales
  Invoice somebody raised by hand is never caught, however similar it looks.

WHAT IT WILL NOT TOUCH, EVER

  Company, Accounts, Cost Centers, Warehouses, Fiscal Years, UOMs, Item Groups.
  Customers, Items and Item Prices that FieldMate did not create.
  Every other app on the bench - excom, crm, trako, help_pilot and the rest. This script knows
  only FieldMate's own DocTypes and its own stamp.
  Users. A login may be shared with another app; `--keep-masters` leaves Field Users alone too.

`--keep-masters` keeps the setup and wipes only the work: outlets, beats, field users,
catalogues, schemes and settings stay; visits, orders, collections, claims, snapshots and alerts
go. Use it when you want to re-run a day's flow without rebuilding the shop list again.
"""

import sys

import frappe

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
    if not arg.startswith("--"):
        SITE = arg

GO = "--yes" in sys.argv
KEEP_MASTERS = "--keep-masters" in sys.argv

# The work a rep and a depot produce. Child tables go with their parents, so only parents are
# named. Order matters: anything holding a link to something below it comes first, or Frappe
# refuses at the first back-link it meets.
TRANSACTIONAL = [
    # Phase 8 - nothing links to these
    "FieldMate Alert Log",
    "FieldMate KPI Snapshot",
    # Phase 7 - a payout names an achievement, which names a plan, which names its parent plan
    "FieldMate Incentive Payout",
    "FieldMate Expense Claim",
    "FieldMate Achievement",
    "FieldMate Target Plan",
    # Phase 9 - a claim holds ledger rows, which hold orders
    "FieldMate Order Ingest Log",
    "FieldMate Claim",
    # Phase 4-6
    "FieldMate Scheme Ledger",
    "FieldMate Van Settlement",
    "FieldMate Van Load",
    "FieldMate Retailer Stock",
    "FieldMate Distributor Stock",
    "FieldMate Secondary Sales",
    "FieldMate Collection Deposit",
    "FieldMate Collection",
    "FieldMate Outstanding Snapshot",
    "FieldMate Order",
    # Phase 3 - a visit holds its audit and its exception
    "FieldMate Merchandising Audit",
    "FieldMate Competitor Capture",
    "FieldMate Visit",
    "FieldMate Geo Fence Exception",
    # Phase 2
    "FieldMate Attendance Summary",
    "FieldMate Location Trail",
    "FieldMate Day End",
    "FieldMate Day Start",
    "FieldMate Journey Plan",
    # Phase 0 - the sync spine
    "FieldMate Sync Conflict",
    "FieldMate Sync Batch",
    "FieldMate Device Registry",
]

# The setup: what somebody configures once. Kept by `--keep-masters`.
MASTERS = [
    "FieldMate Portal User",
    "FieldMate Alert Rule",
    "FieldMate Incentive Scheme",
    "FieldMate Scheme",
    "FieldMate Order Approval Rule",
    "FieldMate Must Sell List",
    "FieldMate Product Catalogue",
    "FieldMate Checklist Template",
    "FieldMate Beat",
    "FieldMate Outlet",
    "FieldMate Distributor Profile",
    "FieldMate Field User",
    "FieldMate No Order Reason",
    "FieldMate Deviation Reason",
    "FieldMate Outlet Channel",
    "FieldMate Outlet Class",
]

# What FieldMate posted into somebody else's books. Found by our own stamp and never by shape:
# a Sales Invoice raised by hand looks identical and must survive.
POSTED = [
    ("Sales Invoice", "a scheme claim credit note"),
    ("Payment Entry", "a confirmed deposit"),
    ("Sales Order", "a directly-billed outlet or a van sale"),
    ("Expense Claim", "a settled travel claim"),
]


def counts() -> list[tuple[str, int, str]]:
    rows = []
    for doctype in TRANSACTIONAL:
        if frappe.db.exists("DocType", doctype):
            rows.append((doctype, frappe.db.count(doctype), "work"))
    if not KEEP_MASTERS:
        for doctype in MASTERS:
            if frappe.db.exists("DocType", doctype):
                rows.append((doctype, frappe.db.count(doctype), "setup"))
    for doctype, why in POSTED:
        if not frappe.db.exists("DocType", doctype):
            continue
        if not _has_stamp(doctype):
            continue
        n = frappe.db.count(doctype, {"fm_source_key": ["is", "set"]})
        if n:
            rows.append((doctype, n, why))
    return rows


def _has_stamp(doctype: str) -> bool:
    """Does this DocType carry our idempotency field on this site?

    Checked rather than assumed: without it there is no way to tell a document FieldMate posted
    from one somebody raised by hand, and this script must never guess.
    """
    return bool(frappe.db.exists("Custom Field",
                                 {"dt": doctype, "fieldname": "fm_source_key"}))


def _wipe(doctype: str, filters=None) -> tuple[int, int]:
    removed = failed = 0
    names = frappe.get_all(doctype, filters=filters or {}, pluck="name")
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
    return removed, failed


def run() -> None:
    print("\nRemoving FieldMate data")
    print("-" * 72)

    total = left = 0

    # Passes, because two of these are trees - a cascaded Target Plan points at the plan above
    # it, and a parent whose children still stand refuses to be cancelled whatever order this
    # list is in. Stops as soon as a pass removes nothing.
    for attempt in range(4):
        moved = 0
        for doctype in TRANSACTIONAL + ([] if KEEP_MASTERS else MASTERS):
            if not frappe.db.exists("DocType", doctype):
                continue
            removed, failed = _wipe(doctype)
            if removed:
                print(f"  removed {removed:6}  {doctype}")
            moved += removed
            left = failed
        total += moved
        if not moved:
            break
        if attempt:
            print(f"  --- pass {attempt + 1} cleared another {moved} ---")

    for doctype, why in POSTED:
        if not frappe.db.exists("DocType", doctype) or not _has_stamp(doctype):
            continue
        removed, failed = _wipe(doctype, {"fm_source_key": ["is", "set"]})
        if removed:
            print(f"  removed {removed:6}  {doctype}   ({why})")
        total += removed

    if not KEEP_MASTERS:
        _clear_settings()

    print("-" * 72)
    print(f"removed {total} documents"
          + (f", {left} could not be removed" if left else ""))


def _clear_settings() -> None:
    """Put the Single back to its defaults, so setup starts from a blank form too.

    Left pointing at an Item that has just been deleted, every later save of FieldMate Settings
    fails on a dead Link - and the message names a field rather than this script.
    """
    settings = frappe.get_single("FieldMate Settings")
    for field in ("default_company", "default_price_list", "support_contact",
                  "claim_settlement_item", "claim_expense_account", "claim_cost_center",
                  "travel_rate_per_km", "daily_food_allowance", "daily_stay_allowance"):
        settings.set(field, None)
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)
    frappe.cache().delete_value("fieldmate_settings")
    frappe.db.commit()
    print("  cleared   FieldMate Settings (company, price list, claim and expense config)")


def main() -> None:
    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user("Administrator")

    mode = "work only, setup kept" if KEEP_MASTERS else "everything"
    print(f"\nFieldMate data on {SITE}   ({mode})")
    if not GO:
        print("DRY RUN - nothing will be deleted")
    print("-" * 72)

    rows = counts()
    if not rows:
        print("  nothing to remove - FieldMate is already empty")
    for doctype, n, why in rows:
        print(f"  {n:6}  {doctype:34} {why}")

    grand = sum(n for _d, n, _w in rows)
    print("-" * 72)
    print(f"  {grand} documents in scope")

    print("\n  NOT touched: Company, Accounts, Cost Centers, Warehouses, Users,")
    print("               Customers/Items FieldMate did not create, and every other app.")

    if not GO:
        print("\nRe-run with --yes to remove them.\n")
    else:
        run()
        print()

    frappe.destroy()


if __name__ == "__main__":
    main()
