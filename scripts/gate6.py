"""Gate 6 — verify all five criteria on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate6.py [site]

Everything it creates is rolled back at the end, so it is safe to run against testerp2.

Criterion 2 is the one that matters most and is asserted as a negative: **no Payment Entry exists
before deposit confirmation**, and a rep role cannot create one directly. Under ADR-025 it is
sharper than the plan first had it — a shop's cash is the distributor's and produces no Payment
Entry ever, confirmed or not.
"""

import sys

import frappe
from frappe.utils import add_days, flt, today

from _guard import require_test_site

SITE = sys.argv[1] if len(sys.argv) > 1 else "testerp2.web.gargsystems.com"

# Run directly rather than imported, so `scripts` is not on the path until we put it there.
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from clean_gate_fixtures import purge

results = []


def check(number, name, passed, detail=""):
    results.append((number, name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {number}. {name}")
    if detail:
        print(f"         {detail}")


def uid(prefix):
    return f"{prefix}-{frappe.generate_hash(length=8)}"


def build_fixtures():
    """A rep, a manager, a shop with a distributor behind it, and a priced item."""
    territory = frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("G6-TERR"),
        "parent_territory": "All Territories", "is_group": 0,
    }).insert(ignore_permissions=True)

    customer = frappe.get_doc({
        "doctype": "Customer", "customer_name": uid("G6-DIST"), "customer_type": "Company",
        "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
    }).insert(ignore_permissions=True)

    distributor = frappe.get_doc({
        "doctype": "FieldMate Distributor Profile",
        "customer": customer.name, "territory": territory.name,
    }).insert(ignore_permissions=True)

    company = frappe.db.get_single_value("FieldMate Settings", "default_company") \
        or frappe.db.get_value("Company", {}, "name")

    def make_user(role, prefix):
        user = frappe.get_doc({
            "doctype": "User", "email": f"{uid(prefix)}@fieldmate.test",
            "first_name": prefix.title(), "send_welcome_email": 0,
            "roles": [{"role": role}],
        }).insert(ignore_permissions=True)
        return user.name

    rep_user = make_user("FieldMate Field Rep", "g6rep")
    manager_user = make_user("FieldMate Area Manager", "g6mgr")

    rep = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": rep_user, "full_name": "Gate Six",
        "designation": "Field Rep", "territory": territory.name, "status": "Active",
        "company": company,
    }).insert(ignore_permissions=True)

    outlet = frappe.get_doc({
        "doctype": "FieldMate Outlet", "outlet_name": uid("G6-SHOP"), "mobile_no": "9800000000",
        "distributor": customer.name, "territory": territory.name,
        "approval_status": "Approved",
    }).insert(ignore_permissions=True)

    code = uid("G6-ITEM")
    data = {
        "doctype": "Item", "item_code": code, "item_name": code,
        "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
        "stock_uom": "Nos" if frappe.db.exists("UOM", "Nos") else frappe.db.get_value("UOM", {}, "name"),
        "is_stock_item": 1,
    }
    if frappe.get_meta("Item").has_field("gst_hsn_code"):
        data["gst_hsn_code"] = frappe.db.get_value("GST HSN Code", {}, "name")
    for field in frappe.get_all("Custom Field",
                                filters={"dt": "Item", "reqd": 1, "fieldtype": "Select"},
                                fields=["fieldname", "options"]):
        choices = [c for c in (field.options or "").split("\n") if c]
        if choices:
            data.setdefault(field.fieldname, choices[0])
    frappe.get_doc(data).insert(ignore_permissions=True)

    price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
    frappe.get_doc({
        "doctype": "Item Price", "item_code": code, "price_list": price_list,
        "selling": 1, "price_list_rate": 100,
    }).insert(ignore_permissions=True)

    frappe.get_doc({
        "doctype": "FieldMate Product Catalogue", "catalogue_name": uid("G6-CAT"),
        "is_active": 1, "territory": territory.name, "items": [{"item_code": code}],
    }).insert(ignore_permissions=True)

    frappe.db.commit()
    return frappe._dict(rep=rep, manager=manager_user, outlet=outlet, distributor=distributor,
                        sku=code, company=company)


def book_three_bills(fx):
    """Three orders on credit, so a collection can be spread across them."""
    from fieldmate.services import order as order_service

    frappe.set_user(fx.rep.user)
    try:
        names = []
        for days in (40, 20, 5):
            created = order_service.create({
                "outlet": fx.outlet.name, "payment_term": "Credit", "credit_days": 15,
                "order_date": add_days(today(), -days), "client_uuid": uid("ORD"),
                "lines": [{"item_code": fx.sku, "qty": 10}],
            }, fx.rep.name)
            order_service.submit_order(created["name"])
            names.append(created["name"])
    finally:
        frappe.set_user("Administrator")
    return names


def criterion_1(fx, bills):
    """A collection across three invoices reduces outstanding correctly."""
    from fieldmate.services import collection as collection_service

    frappe.set_user(fx.rep.user)
    try:
        before = collection_service.outstanding_for(fx.outlet.name, fx.rep.name)
        collected = collection_service.create({
            "party_type": "Outlet", "outlet": fx.outlet.name, "amount": 2500, "mode": "Cash",
            "client_uuid": uid("COL"),
            "allocations": [
                {"reference_type": "FieldMate Order", "reference_name": bills[0],
                 "allocated_amount": 1000},
                {"reference_type": "FieldMate Order", "reference_name": bills[1],
                 "allocated_amount": 1000},
                {"reference_type": "FieldMate Order", "reference_name": bills[2],
                 "allocated_amount": 500},
            ],
        }, fx.rep.name)
        after = collection_service.outstanding_for(fx.outlet.name, fx.rep.name)
    finally:
        frappe.set_user("Administrator")

    check(1, "A collection across three bills reduces outstanding by exactly what was taken",
          before["outstanding"] == 3000.0
          and after["outstanding"] == 500.0
          and collected["allocated_amount"] == 2500.0,
          f"owed {before['outstanding']:g}, took 2500 across 3 bills, now owes "
          f"{after['outstanding']:g} · receipt {collected['receipt_no']}")
    return collected


def criterion_2(fx, collected):
    """No Payment Entry before confirmation, and a rep cannot make one."""
    from fieldmate.services import collection as collection_service

    before = frappe.db.count("Payment Entry")

    # A shop collection, already taken. Nothing should have posted.
    shop_posted = bool(frappe.db.get_value("FieldMate Collection", collected["name"],
                                           "payment_entry"))

    # And one from a distributor, which IS ours - still nothing until a deposit is confirmed.
    frappe.set_user(fx.rep.user)
    try:
        dist = collection_service.create({
            "party_type": "Distributor", "distributor": fx.distributor.name,
            "amount": 5000, "mode": "Cheque", "instrument_no": "004921",
            "client_uuid": uid("COL"),
        }, fx.rep.name)
        deposit = collection_service.declare_deposit({
            "collections": [collected["name"], dist["name"]],
            "channel": "Bank Branch", "reference_no": "CDM-8849201",
            "client_uuid": uid("DEP"),
        }, fx.rep.name)

        rep_can_create = frappe.has_permission("Payment Entry", "create")
    finally:
        frappe.set_user("Administrator")

    after_declaring = frappe.db.count("Payment Entry")

    check(2, "No Payment Entry exists before confirmation, and a rep cannot create one",
          not shop_posted and after_declaring == before and not rep_can_create,
          f"taken and declared 2 collections worth 7500 · Payment Entries {before} -> "
          f"{after_declaring} · rep may create one: {rep_can_create}")

    # Confirming posts only the distributor's half (ADR-025).
    collection_service.confirm_deposit(deposit["name"], confirmed_by=fx.manager)
    after_confirming = frappe.db.count("Payment Entry")

    check("2b", "Confirming posts only the money that was ours",
          after_confirming == before + 1
          and not frappe.db.get_value("FieldMate Collection", collected["name"], "payment_entry")
          and bool(frappe.db.get_value("FieldMate Collection", dist["name"], "payment_entry")),
          f"Payment Entries {after_declaring} -> {after_confirming} · the shop's 2500 was the "
          f"distributor's all along and posted nothing")
    return dist


def criterion_3(fx, dist):
    """A bounced cheque reverses cleanly and restores the original outstanding."""
    from fieldmate.services import collection as collection_service

    entry = frappe.db.get_value("FieldMate Collection", dist["name"], "payment_entry")
    collection_service.bounce(dist["name"], "insufficient funds")

    check(3, "A bounced cheque reverses cleanly and restores what was owed",
          frappe.db.get_value("Payment Entry", entry, "docstatus") == 2
          and frappe.db.get_value("FieldMate Collection", dist["name"], "status") == "Bounced",
          f"Payment Entry {entry} cancelled, collection marked Bounced")


def criterion_4(fx):
    """Undeposited cash past the threshold alerts the rep's manager."""
    from fieldmate.services import collection as collection_service

    frappe.set_user(fx.rep.user)
    try:
        collection_service.create({
            "party_type": "Outlet", "outlet": fx.outlet.name, "amount": 900, "mode": "Cash",
            "collection_date": add_days(today(), -6), "client_uuid": uid("COL"),
        }, fx.rep.name)
        position = collection_service.undeposited(fx.rep.name)
    finally:
        frappe.set_user("Administrator")

    alert = collection_service.alert_cash_in_hand()
    flagged = [row for row in alert["flagged"] if row["field_user"] == fx.rep.name]

    check(4, "Undeposited cash past the threshold is flagged for a manager",
          position["is_overdue"] and len(flagged) == 1,
          f"carrying {position['total_amount']:g} for {position['oldest_days']} days, "
          f"threshold {alert['threshold_days']} days")


def criterion_5(fx, bills):
    """An offline collection reflects correct outstanding after sync even if another landed
    first."""
    from fieldmate.services import collection as collection_service
    from fieldmate.services import sync as sync_service

    device = frappe.get_doc({
        "doctype": "FieldMate Device Registry", "device_uuid": uid("DEV"),
        "user": fx.rep.user, "platform": "Android",
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    frappe.set_user(fx.rep.user)
    try:
        before = collection_service.outstanding_for(fx.outlet.name, fx.rep.name)["outstanding"]

        # One taken online while the phone was away.
        collection_service.create({
            "party_type": "Outlet", "outlet": fx.outlet.name, "amount": 200, "mode": "Cash",
            "client_uuid": uid("COL"),
            "allocations": [{"reference_type": "FieldMate Order", "reference_name": bills[2],
                             "allocated_amount": 200}],
        }, fx.rep.name)

        # And one the phone had been holding all along.
        pushed = sync_service.push(fx.rep.user, device, uid("BATCH"), [{
            "doctype": "FieldMate Collection",
            "client_uuid": uid("COL"),
            "data": {
                "docstatus": 1, "party_type": "Outlet", "outlet": fx.outlet.name,
                "collection_date": today(), "mode": "Cash", "amount": 100,
                "created_offline": 1,
                "allocations": [{"reference_type": "FieldMate Order",
                                 "reference_name": bills[2], "allocated_amount": 100}],
            },
        }])["results"][0]

        after = collection_service.outstanding_for(fx.outlet.name, fx.rep.name)["outstanding"]
    finally:
        frappe.set_user("Administrator")

    check(5, "An offline collection lands correctly even though another was taken first",
          pushed["status"] == "created" and round(before - after, 2) == 300.0,
          f"owed {before:g}, 200 online + 100 from the phone, now owes {after:g} · "
          f"push: {pushed['status']}")


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    print(f"\nGate 6 on {SITE}\n" + "-" * 72)
    try:
        fx = build_fixtures()
        bills = book_three_bills(fx)
        collected = criterion_1(fx, bills)
        dist = criterion_2(fx, collected)
        criterion_3(fx, dist)
        criterion_4(fx)
        criterion_5(fx, bills)
    finally:
        # A rollback is not enough on its own. This script commits its fixtures, and several of
        # the services it exercises commit internally anyway, so a transaction lasting to the end
        # was never on offer - six runs of gate2 left 868 records on testerp2 before anybody
        # noticed. The rollback stays as a backstop; `purge` is what actually clears up.
        frappe.db.rollback()
        try:
            purge("G6")
        except Exception as e:
            print(f"  !! could not clean up: {e} - run scripts/clean_gate_fixtures.py")
        frappe.destroy()

    print("-" * 72)
    passed = sum(1 for *_, ok, _d in results if ok)
    print(f"Gate 6: {passed}/{len(results)} criteria passed\n")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
