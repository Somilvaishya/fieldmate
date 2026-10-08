"""Phase 1 gate — the channel redesign, verified on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate_phase1.py [site]

Eight criteria, one per thing this phase built, each written as something that either happens or
does not. Four of them are **negatives** - a switched-off mode refuses, a price over the MRP
refuses, a retailer order posts no ledger entry, a retailer scheme does not reach a primary order
- because those are the actual requirements. A gate that only checked the happy path would pass
on an app that had quietly stopped refusing anything.

What is not here: the phone. Step 9's party picker and the four order screens have no automated
cover at all - this repo has no frontend harness - so they are in MANUAL_TESTS_PHASE1.md and
named there as untested rather than implied to be done.

Everything it creates carries the `P1-` prefix and is purged at the end. A rollback is not enough
on its own: the services this exercises commit internally, which is how six runs of an earlier
gate left 868 records on testerp2.
"""

import sys

import frappe
from frappe.utils import add_days, flt, today

from _guard import hsn_code, require_test_site

SITE = sys.argv[1] if len(sys.argv) > 1 else "testerp2.web.gargsystems.com"

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from clean_gate_fixtures import purge

PREFIX = "P1"
results = []


def with_hsn(data: dict) -> dict:
    """An HSN code on the gate's own item, where the site wants one.

    One answer, in `_guard`, shared with every other script here - this used to be a second copy
    of the same logic, and two copies of a rule is how the gates came to disagree about which
    price list to use.
    """
    if not data.get("gst_hsn_code"):
        code = hsn_code()
        if code:
            data["gst_hsn_code"] = code
    return data


def check(number, name, passed, detail=""):
    results.append((number, name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {number}. {name}")
    if detail:
        print(f"         {detail}")


def uid(prefix):
    return f"{PREFIX}-{prefix}-{frappe.generate_hash(length=8)}"


def refusal(fn, *args, **kwargs):
    """Run something that must be refused, and hand back the message it refused with.

    Returns None where it was *not* refused, which every caller treats as a failure. Catching
    broadly on purpose: what matters to a gate is that the order did not go through and that the
    rep was told why, not which exception class carried the message.
    """
    try:
        fn(*args, **kwargs)
        return None
    except Exception as e:
        return frappe.utils.strip_html(str(e))


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------


def build():
    from fieldmate.services import settings as settings_service

    company = settings_service.value("default_company") or frappe.db.get_value("Company", {}, "name")
    currency = frappe.db.get_value("Company", company, "default_currency")
    group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
    root = frappe.db.get_value("Territory", {"is_group": 1, "parent_territory": ("in", ("", None))}, "name")

    territory = frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("TERR"),
        "parent_territory": root, "is_group": 0,
    }).insert(ignore_permissions=True)

    price_list = frappe.get_doc({
        "doctype": "Price List", "price_list_name": uid("PL"),
        "selling": 1, "enabled": 1, "currency": currency,
    }).insert(ignore_permissions=True)

    # The distributor: a Customer with a channel tier, and a PTR list its shops buy on.
    distributor = frappe.get_doc({
        "doctype": "Customer", "customer_name": f"{PREFIX}-DIST-{frappe.generate_hash(length=8)}",
        "customer_type": "Company", "customer_group": group, "territory": territory.name,
        "fm_tier": "Distributor", "fm_buys_from": "Company",
        "fm_ptr_price_list": price_list.name,
        "credit_limits": [{"company": company, "credit_limit": 1_000_000}],
    }).insert(ignore_permissions=True)

    item = frappe.get_doc(with_hsn({
        "doctype": "Item", "item_code": uid("ITEM"), "item_name": "Gate soap",
        "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
        "stock_uom": "Nos", "is_stock_item": 1, "is_sales_item": 1,
    })).insert(ignore_permissions=True)
    # 100 a piece on the PTR list, and an MRP of 120 so criterion 3 has something to breach.
    frappe.get_doc({
        "doctype": "Item Price", "item_code": item.name,
        "price_list": price_list.name, "price_list_rate": 100,
    }).insert(ignore_permissions=True)
    if frappe.db.has_column("Item", "fm_mrp"):
        frappe.db.set_value("Item", item.name, "fm_mrp", 120, update_modified=False)

    frappe.get_doc({
        "doctype": "FieldMate Product Catalogue", "catalogue_name": uid("CAT"),
        "is_active": 1, "items": [{"item_code": item.name}],
    }).insert(ignore_permissions=True)

    user = frappe.get_doc({
        "doctype": "User", "email": f"{PREFIX.lower()}rep{frappe.generate_hash(length=6)}@fieldmate.test",
        "first_name": "Gate Rep", "send_welcome_email": 0,
        "roles": [{"role": "FieldMate Field Rep"}],
    }).insert(ignore_permissions=True)
    rep = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": user.name, "full_name": "Gate Rep",
        "designation": "Field Rep", "territory": territory.name, "company": company,
        "status": "Active", "can_create_outlet": 1, "can_collect_payment": 1,
    }).insert(ignore_permissions=True)

    outlet = frappe.get_doc({
        "doctype": "FieldMate Outlet", "outlet_name": uid("SHOP"), "mobile_no": "9800000000",
        "distributor": distributor.name, "territory": territory.name,
        "approval_status": "Approved", "credit_limit": 5_000,
    }).insert(ignore_permissions=True)

    frappe.db.commit()
    return frappe._dict(company=company, territory=territory.name, price_list=price_list.name,
                        distributor=distributor.name, item=item.name, rep=rep.name,
                        user=user.name, outlet=outlet.name)


def as_rep(fx, fn, *args, **kwargs):
    """Run something in the rep's own session.

    Not a nicety: `submit_order` refuses an order that belongs to another rep, and to the server
    "another rep" includes Administrator. Every gate before this one exercised the rep's path as
    the rep for the same reason - running as Administrator passes checks that the field never
    passes.
    """
    frappe.set_user(fx.user)
    try:
        return fn(*args, **kwargs)
    finally:
        frappe.set_user("Administrator")


def book(fx, qty=10, **extra):
    from fieldmate.services import order as order_service

    payload = {"outlet": fx.outlet, "lines": [{"item": fx.item, "qty": qty}],
               "client_uuid": uid("ORD")}
    payload.update(extra)
    return as_rep(fx, order_service.create, payload, fx.rep)


# --------------------------------------------------------------------------------------
# the criteria
# --------------------------------------------------------------------------------------


def criterion_1(fx, settings):
    """A site that does not make a kind of sale refuses it, and says which switch."""
    frappe.db.set_single_value("FieldMate Settings",
                               {"enable_secondary_sales": 0, "enable_primary_sales": 1})
    frappe.cache().delete_value("fieldmate_settings")

    message = refusal(book, fx)
    frappe.db.set_single_value("FieldMate Settings",
                               {"enable_secondary_sales": 1, "enable_primary_sales": 1})
    frappe.cache().delete_value("fieldmate_settings")

    ok = bool(message) and "switched off" in message
    check(1, "A switched-off mode refuses the order and names the switch",
          ok, message or "the order went through with secondary sales switched off")


def criterion_2(fx):
    """A shop with no list of its own is quoted from its distributor's PTR list."""
    from fieldmate.services import pricing

    doc = frappe.get_doc("FieldMate Outlet", fx.outlet)
    answer = pricing.price_list_for(doc, fx.rep)
    check(2, "A shop with no list of its own buys on its distributor's PTR list",
          answer == fx.price_list, f"resolved {answer!r}, expected {fx.price_list!r}")


def criterion_3(fx):
    """A line priced over the MRP is refused by name."""
    if not frappe.db.has_column("Item", "fm_mrp"):
        check(3, "An order priced above the MRP is refused", False,
              "this site has no MRP column on Item, so nothing could be checked")
        return

    frappe.db.set_value("Item Price", {"item_code": fx.item, "price_list": fx.price_list},
                        "price_list_rate", 150, update_modified=False)
    message = refusal(book, fx)
    frappe.db.set_value("Item Price", {"item_code": fx.item, "price_list": fx.price_list},
                        "price_list_rate", 100, update_modified=False)

    ok = bool(message) and fx.item in message and "MRP" in message
    check(3, "An order priced above the MRP is refused and names the SKU",
          ok, message or "a line at 150 against an MRP of 120 was booked")


def criterion_4(fx):
    """A retailer order carries the distributor's GST and posts nothing."""
    from fieldmate.services import order as order_service

    before = frappe.db.count("GL Entry"), frappe.db.count("Sales Order")
    created = book(fx, qty=10)
    as_rep(fx, order_service.submit_order, created["name"])
    doc = frappe.get_doc("FieldMate Order", created["name"])
    after = frappe.db.count("GL Entry"), frappe.db.count("Sales Order")

    posted_nothing = after == before
    totals = f"net {doc.net_total}, tax {doc.tax_total}, grand {doc.grand_total}"
    # Tax may legitimately be zero where this site has no tax template; what must hold is that
    # the grand total is the net plus whatever tax was computed, and that nothing was posted.
    adds_up = flt(doc.grand_total, 2) == flt(flt(doc.net_total) + flt(doc.tax_total), 2)
    check(4, "A retailer order totals to net plus tax and posts no accounting document",
          posted_nothing and adds_up,
          f"{totals}; posted {after[0] - before[0]} GL entries and "
          f"{after[1] - before[1]} sales orders")
    return doc


def criterion_5(fx):
    """A primary order on a Customer posts exactly one Sales Order, to that party."""
    from fieldmate.services import order as order_service

    before = frappe.db.count("Sales Order")
    created = as_rep(fx, order_service.create, {
        "party_type": "Customer", "customer": fx.distributor,
        "lines": [{"item": fx.item, "qty": 10}], "client_uuid": uid("PORD"),
    }, fx.rep)
    as_rep(fx, order_service.submit_order, created["name"])
    doc = frappe.get_doc("FieldMate Order", created["name"])

    one = frappe.db.count("Sales Order") == before + 1
    billed = doc.sales_order and frappe.db.get_value(
        "Sales Order", doc.sales_order, "customer") == fx.distributor
    check(5, "A primary order posts one Sales Order, billed to the party we sold to",
          bool(one and billed),
          f"sales order {doc.sales_order!r}, status {doc.order_status!r}")


def criterion_6(fx):
    """Credit is measured on both sides, and the shop's own limit can breach on its own."""
    from fieldmate.services import credit as credit_service

    # The distributor has a million of headroom with us; the shop has a 5,000 limit and has just
    # been booked well past it by the orders above.
    answer = credit_service.check(fx.outlet, fx.rep, 10_000)
    shop = answer.get("shop") or {}

    # The point of the criterion: the distributor has a million of headroom with us and the shop
    # is still over with them, so the verdict has to be a breach. Reading `party_status` rather
    # than `status` is the whole reason that key exists - `status` is the worse of the two by
    # then, so printing it beside the word "distributor" says something untrue.
    both_measured = bool(shop) and bool(answer.get("limit"))
    distributor_clear = answer.get("party_status") != credit_service.BREACH
    shop_breaches = shop.get("status") == credit_service.BREACH

    check(6, "Credit is measured on both sides, and the shop's own limit can breach alone",
          bool(both_measured and distributor_clear and shop_breaches
               and answer["status"] == credit_service.BREACH),
          f"distributor {answer.get('party_status')!r} on a limit of {answer.get('limit')}, "
          f"shop {shop.get('status')!r} on a limit of {shop.get('limit')}, "
          f"verdict {answer.get('status')!r}")


def criterion_7(fx):
    """A distributor's file replaces the orders it covers rather than adding to them."""
    from fieldmate.services import collection as collection_service

    on = today()
    before = flt(collection_service.outstanding_for(fx.outlet, fx.rep)["outstanding"])

    doc = frappe.get_doc({
        "doctype": "FieldMate Secondary Sales", "distributor": fx.distributor,
        "from_date": add_days(on, -1), "to_date": add_days(on, 1),
        "items": [{"sale_date": on, "item_code": fx.item, "qty": 10, "amount": 777.0,
                   "outlet": fx.outlet, "invoice_no": uid("INV")}],
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()

    after = collection_service.outstanding_for(fx.outlet, fx.rep)
    # The invoiced figure stands in place of the orders, so the total is the file's - not the
    # file's plus the orders', which is what counting both would give.
    replaced = flt(after["outstanding"]) == 777.0
    check(7, "A distributor's file replaces the orders it covers rather than adding to them",
          replaced, f"owed {before} from our orders, {after['outstanding']} after a file of 777")


def criterion_8(fx):
    """A scheme written for one kind of sale does not reach the other."""
    from fieldmate.services import scheme_compile

    retailer = frappe.get_doc({
        "doctype": "FieldMate Scheme", "scheme_name": uid("SCH-SEC"),
        "scheme_type": "Volume Slab", "priority": 10, "is_active": 1,
        "basis": "Qty", "basis_uom": "Unit", "measured_over": "Item Set",
        "stacking": "Stackable", "valid_from": add_days(today(), -7), "on_exhaust": "Block",
        "applies_to": "Secondary",
        "items": [{"item_code": fx.item}],
        "slabs": [{"slab_idx": 1, "from_value": 1, "is_open_ended": 1,
                   "benefit_kind": "Percent Discount", "per": "Slab", "discount_pct": 5}],
    }).insert(ignore_permissions=True)
    retailer.submit()

    primary = frappe.get_doc({
        "doctype": "FieldMate Scheme", "scheme_name": uid("SCH-PRI"),
        "scheme_type": "Volume Slab", "priority": 10, "is_active": 1,
        "basis": "Qty", "basis_uom": "Unit", "measured_over": "Item Set",
        "stacking": "Stackable", "valid_from": add_days(today(), -7), "on_exhaust": "Block",
        "applies_to": "Primary",
        "items": [{"item_code": fx.item}],
        "slabs": [{"slab_idx": 1, "from_value": 1, "is_open_ended": 1,
                   "benefit_kind": "Percent Discount", "per": "Slab", "discount_pct": 7}],
    }).insert(ignore_permissions=True)
    primary.submit()
    frappe.db.commit()

    at_shop = [s["scheme"] for s in scheme_compile.for_outlet(
        fx.outlet, fx.rep, kind="Secondary")["specs"]]
    at_party = [s["scheme"] for s in scheme_compile.for_outlet(
        fx.distributor, fx.rep, party_type="Customer", kind="Primary")["specs"]]

    ok = (retailer.name in at_shop and primary.name not in at_shop
          and primary.name in at_party and retailer.name not in at_party)
    check(8, "A scheme written for one kind of sale does not reach the other", ok,
          f"at the shop {at_shop}, at the party {at_party}")


# --------------------------------------------------------------------------------------


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    from fieldmate.services import settings as settings_service

    print(f"\nPhase 1 gate on {SITE}\n" + "-" * 72)

    # Recorded before anything runs and put back whatever happens. Criterion 1 flips both
    # switches, and leaving a site's sales mode switched off would stop every order on it.
    live = settings_service.get()
    was = {k: live.get(k) for k in ("enable_secondary_sales", "enable_primary_sales")}

    try:
        fx = build()
        criterion_1(fx, was)
        criterion_2(fx)
        criterion_3(fx)
        criterion_4(fx)
        criterion_5(fx)
        criterion_6(fx)
        criterion_7(fx)
        criterion_8(fx)
    finally:
        try:
            frappe.db.set_single_value("FieldMate Settings", was)
            frappe.cache().delete_value("fieldmate_settings")
            frappe.db.commit()
        except Exception as e:
            print(f"  !! could not restore the sales-mode settings: {e}")
        frappe.db.rollback()
        try:
            purge(PREFIX)
        except Exception as e:
            print(f"  !! could not clean up: {e} - run scripts/clean_gate_fixtures.py")
        frappe.destroy()

    print("-" * 72)
    passed = sum(1 for *_, ok, _d in results if ok)
    print(f"Phase 1: {passed}/{len(results)} criteria passed")
    print("The phone is not covered here - see docs/MANUAL_TESTS_PHASE1.md\n")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
