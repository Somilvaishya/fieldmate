"""Gate 9 — verify all four criteria on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate9.py [site]

The four, from TEST_PLAN:

  1. A distributor sees only its own orders and claims, verified by attempting another's
     document - refused, not merely absent from a list.
  2. A month's claim reconciles exactly to the benefits applied on those orders.
  3. Claim approval raises a Credit Note on the right account and cost centre.
  4. A fulfilment status the distributor set appears in the rep's PWA order list after sync.

Criterion 1 is the one worth being careful with. A list that comes back empty proves nothing on
a site where the fixture happened to create nothing - so this builds a *second* distributor with
a real order of its own, and then goes after it by name.
"""

import sys

import frappe
from frappe.utils import add_days, flt, today

from _guard import hsn_code, require_test_site, selling_price_list

SITE = sys.argv[1] if len(sys.argv) > 1 else "testerp2.web.gargsystems.com"

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from clean_gate_fixtures import purge

results = []


def check(number, name, passed, detail=""):
    # bool(), for the reason Gate 2 found the hard way: `a and b.get(c)` yields None rather than
    # False, and a None here printed FAIL and was counted as a pass.
    results.append((number, name, bool(passed), detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {number}. {name}")
    if detail:
        print(f"         {detail}")


def uid(prefix):
    return f"{prefix}-{frappe.generate_hash(length=8)}"


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------


def make_distributor(territory):
    # A distributor is a Customer with a channel tier - there is no FieldMate Distributor Profile
    # beside it any more. Both halves of the pair are returned as the same document, so that the
    # call sites below can go on naming the depot and its billing account separately.
    customer = frappe.get_doc({
        "doctype": "Customer", "customer_name": uid("G9-DIST"), "customer_type": "Company",
        "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
        "territory": territory,
        "fm_tier": "Distributor", "fm_buys_from": "Company",
    }).insert(ignore_permissions=True)
    return customer, customer


def make_portal_user(distributor, prefix="g9depot"):
    user = frappe.get_doc({
        "doctype": "User", "email": f"{uid(prefix)}@fieldmate.test",
        "first_name": "Depot Desk", "send_welcome_email": 0,
    }).insert(ignore_permissions=True)
    row = frappe.get_doc({
        "doctype": "FieldMate Portal User", "user": user.name, "distributor": distributor,
    }).insert(ignore_permissions=True)
    return row


def build_fixtures():
    """Two distributors, a rep who sells to both, a priced SKU and a scheme that grants on it."""
    territory = frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("G9-TERR"),
        "parent_territory": "All Territories", "is_group": 0,
    }).insert(ignore_permissions=True)

    mine_customer, mine = make_distributor(territory.name)
    other_customer, other = make_distributor(territory.name)

    company = frappe.db.get_single_value("FieldMate Settings", "default_company") \
        or frappe.db.get_value("Company", {}, "name")

    rep_user = frappe.get_doc({
        "doctype": "User", "email": f"{uid('g9rep')}@fieldmate.test",
        "first_name": "Gate Nine", "send_welcome_email": 0,
        "roles": [{"role": "FieldMate Field Rep"}],
    }).insert(ignore_permissions=True)

    rep = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": rep_user.name, "full_name": "Gate Nine",
        "designation": "Field Rep", "territory": territory.name, "status": "Active",
        "company": company,
    }).insert(ignore_permissions=True)

    def shop(customer):
        return frappe.get_doc({
            "doctype": "FieldMate Outlet", "outlet_name": uid("G9-SHOP"),
            "mobile_no": "9800000000", "distributor": customer.name,
            "territory": territory.name, "approval_status": "Approved",
        }).insert(ignore_permissions=True)

    sku = make_item()
    price_list = selling_price_list()
    frappe.get_doc({
        "doctype": "Item Price", "item_code": sku, "price_list": price_list,
        "selling": 1, "price_list_rate": 100,
    }).insert(ignore_permissions=True)

    frappe.get_doc({
        "doctype": "FieldMate Product Catalogue", "catalogue_name": uid("G9-CAT"),
        "is_active": 1, "territory": territory.name, "items": [{"item_code": sku}],
    }).insert(ignore_permissions=True)

    scheme = frappe.get_doc({
        "doctype": "FieldMate Scheme", "scheme_name": uid("G9-SCH"),
        "scheme_type": "Volume Slab", "priority": 10, "is_active": 1,
        "basis": "Qty", "basis_uom": "Unit", "measured_over": "Item Set",
        "stacking": "Stackable", "valid_from": add_days(today(), -30), "on_exhaust": "Block",
        "items": [{"item_code": sku}],
        "slabs": [{"slab_idx": 1, "from_value": 10, "is_open_ended": 1,
                   "benefit_kind": "Percent Discount", "per": "Slab", "discount_pct": 5}],
    }).insert(ignore_permissions=True)
    scheme.submit()

    settlement_item = make_item()
    expense = frappe.db.get_value(
        "Account", {"company": company, "root_type": "Income", "is_group": 0}, "name")
    cost_center = frappe.db.get_value("Company", company, "cost_center")
    apply_claim_settings(settlement_item, expense, cost_center)

    frappe.db.commit()
    return frappe._dict(
        territory=territory.name, company=company, rep=rep, sku=sku, scheme=scheme.name,
        mine=mine, mine_customer=mine_customer, mine_shop=shop(mine_customer),
        other=other, other_customer=other_customer, other_shop=shop(other_customer),
        depot=make_portal_user(mine.name),
        settlement_item=settlement_item, expense=expense, cost_center=cost_center,
    )


# FieldMate Settings is a Single. It survives this script's rollback and its purge, and both of
# the things it is pointed at here are fixtures that do not - so whatever was in these three
# before has to go back, or the next thing on this bench to save the Single dies on a dead Link.
# The first run of this gate left `claim_settlement_item` pointing at a purged G9 item and broke
# twenty unrelated tests with `Could not find Settlement Item`, which named nothing that would
# lead anybody here.
CLAIM_SETTINGS = ("claim_settlement_item", "claim_expense_account", "claim_cost_center")
_settings_before: dict = {}


def apply_claim_settings(item, expense, cost_center):
    settings = frappe.get_single("FieldMate Settings")
    _settings_before.update({key: settings.get(key) for key in CLAIM_SETTINGS})

    settings.claim_settlement_item = item
    settings.claim_expense_account = expense
    settings.claim_cost_center = cost_center
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)
    frappe.cache().delete_value("fieldmate_settings")


def restore_claim_settings():
    if not _settings_before:
        return
    settings = frappe.get_single("FieldMate Settings")
    for key, value in _settings_before.items():
        settings.set(key, value)
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)
    frappe.cache().delete_value("fieldmate_settings")
    frappe.db.commit()


def make_item():
    code = uid("G9-ITEM")
    data = {
        "doctype": "Item", "item_code": code, "item_name": code,
        "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
        "stock_uom": "Nos" if frappe.db.exists("UOM", "Nos")
                     else frappe.db.get_value("UOM", {}, "name"),
        "is_stock_item": 1,
    }
    if frappe.get_meta("Item").has_field("gst_hsn_code"):
        data["gst_hsn_code"] = hsn_code()
    for field in frappe.get_all("Custom Field",
                                filters={"dt": "Item", "reqd": 1, "fieldtype": "Select"},
                                fields=["fieldname", "options"]):
        choices = [c for c in (field.options or "").split("\n") if c]
        if choices:
            data.setdefault(field.fieldname, choices[0])
    frappe.get_doc(data).insert(ignore_permissions=True)
    return code


def book(fx, outlet, qty=40, days_ago=0):
    from fieldmate.services import order as order_service

    frappe.set_user(fx.rep.user)
    try:
        created = order_service.create({
            "outlet": outlet.name, "client_uuid": uid("ORD"),
            "order_date": add_days(today(), -days_ago),
            "lines": [{"item_code": fx.sku, "qty": qty}],
        }, fx.rep.name)
        order_service.submit_order(created["name"])
    finally:
        frappe.set_user("Administrator")
    return created["name"]


def as_depot(fx, fn, *args, **kwargs):
    frappe.set_user(fx.depot.user)
    try:
        return fn(*args, **kwargs)
    finally:
        frappe.set_user("Administrator")


# --------------------------------------------------------------------------------------
# criteria
# --------------------------------------------------------------------------------------


def criterion_1(fx, mine_order, other_order):
    """Own documents visible; another depot's refused by name."""
    from fieldmate.services import portal as portal_service

    listed = [r.name for r in as_depot(fx, portal_service.orders)]

    refused_detail = None
    try:
        as_depot(fx, portal_service.order_detail, other_order)
        refused_detail = False
    except frappe.PermissionError:
        refused_detail = True

    refused_move = None
    try:
        as_depot(fx, portal_service.act, other_order, "Accepted")
        refused_move = False
    except frappe.PermissionError:
        refused_move = True

    # And the framework layer, which is what catches the route nobody went through the service for.
    frappe.set_user(fx.depot.user)
    try:
        queried = [r.name for r in frappe.get_list(
            "FieldMate Order", fields=["name"], limit_page_length=0,
            user=fx.depot.user, ignore_permissions=False)]
    finally:
        frappe.set_user("Administrator")

    check(1, "A distributor sees only its own orders, and another's is refused by name",
          mine_order in listed and other_order not in listed
          and refused_detail and refused_move
          and mine_order in queried and other_order not in queried,
          f"queue holds {len(listed)} of its own · reading another depot's order refused: "
          f"{refused_detail} · moving it refused: {refused_move} · "
          f"plain get_list returned {len(queried)} rows, none of them the other depot's")


def criterion_2(fx, mine_order):
    """A month's claim reconciles exactly to the benefits accrued on those orders."""
    from fieldmate.services import claim as claim_service

    accrued = frappe.get_all(
        "FieldMate Scheme Ledger",
        filters={"distributor": fx.mine.name, "docstatus": 1,
                 "benefit_kind": ["in", ("Free Goods", "Percent Discount", "Value Discount",
                                         "Rate Off")]},
        fields=["name", "benefit_amount", "order"],
    )
    expected = sum(flt(r.benefit_amount) for r in accrued)

    name = claim_service.build(fx.mine.name, add_days(today(), -30), today())
    claim_service.submit_claim(name)
    doc = frappe.get_doc("FieldMate Claim", name)

    # And every line traces back to an order that is actually in this depot's queue.
    orders = {r.order for r in accrued}
    traced = all(
        frappe.db.get_value("FieldMate Order", o, "distributor") == fx.mine.name for o in orders)

    check(2, "The month's claim reconciles to the paise against the benefits granted",
          doc.line_count == len(accrued)
          and abs(flt(doc.claimed_amount) - expected) < 0.005
          and abs(flt(doc.variance_amount)) < 0.005
          and doc.reconciles and traced,
          f"{len(accrued)} accruals worth {expected:.2f} · claim carries {doc.line_count} "
          f"worth {flt(doc.claimed_amount):.2f} · variance {flt(doc.variance_amount):.2f} · "
          f"every line traces to an order in this queue: {traced}")
    return name


def criterion_3(fx, claim_name):
    """Approval raises a Credit Note on the configured account and cost centre."""
    from fieldmate.services import claim as claim_service

    before_invoices = frappe.db.count("Sales Invoice")
    before_stock = frappe.db.count("Stock Ledger Entry")

    result = claim_service.approve(claim_name, "Approved")
    note = result.get("credit_note")
    invoice = frappe.get_doc("Sales Invoice", note) if note else None

    # Called a second time, the key has to return the same note rather than credit again.
    claim_service.settle_claim(claim_name)
    after_invoices = frappe.db.count("Sales Invoice")

    line = invoice.items[0] if invoice and invoice.items else None
    check(3, "Claim approval raises one Credit Note on the right account and cost centre",
          invoice is not None
          and invoice.is_return == 1
          and invoice.customer == fx.mine_customer.name
          and invoice.docstatus == 1
          and line is not None
          and line.income_account == fx.expense
          and line.cost_center == fx.cost_center
          # A return invoice totals negative, and it has to: a positive one would be money
          # billed to the distributor rather than credited to him.
          and abs(flt(invoice.grand_total) + flt(result["approved_amount"])) < 0.005
          and after_invoices == before_invoices + 1
          and frappe.db.count("Stock Ledger Entry") == before_stock,
          f"{note} · return={getattr(invoice, 'is_return', None)} "
          f"account={getattr(line, 'income_account', None)} "
          f"cost centre={getattr(line, 'cost_center', None)} "
          f"total={flt(getattr(invoice, 'grand_total', 0)):.2f} · "
          f"settling twice left {after_invoices - before_invoices} invoice · "
          f"stock ledger untouched: {frappe.db.count('Stock Ledger Entry') == before_stock}")


def criterion_4(fx, mine_order):
    """What the depot set reaches the rep's own order list after a sync."""
    from fieldmate.services import order as order_service
    from fieldmate.services import portal as portal_service
    from fieldmate.services import sync as sync_service

    before = sync_service.pull(fx.rep.user, doctypes=["FieldMate Order"])
    was = {r["name"]: r["order_status"] for r in before["changes"]["FieldMate Order"]}

    as_depot(fx, portal_service.act, mine_order, "Accepted")
    as_depot(fx, portal_service.act, mine_order, "Invoiced", reference="G9/DEP/0001")

    after = sync_service.pull(fx.rep.user, since=before["watermark"],
                              doctypes=["FieldMate Order"])
    rows = {r["name"]: r for r in after["changes"]["FieldMate Order"]}

    # And the rep's own list - what the PWA actually renders - agrees with the pull.
    frappe.set_user(fx.rep.user)
    try:
        mine = {r["name"]: r["order_status"] for r in order_service.mine(fx.rep.name)}
    finally:
        frappe.set_user("Administrator")

    logged = frappe.db.count("FieldMate Order Ingest Log", {"order": mine_order})

    check(4, "A fulfilment status the depot set reaches the rep's order list after sync",
          was.get(mine_order) == "Sent To Distributor"
          and mine_order in rows
          and rows[mine_order]["order_status"] == "Invoiced"
          and rows[mine_order]["distributor_reference"] == "G9/DEP/0001"
          and mine.get(mine_order) == "Invoiced"
          and logged == 2,
          f"was {was.get(mine_order)} · depot accepted then invoiced · delta pull returned "
          f"{rows.get(mine_order, {}).get('order_status')} with reference "
          f"{rows.get(mine_order, {}).get('distributor_reference')} · rep's own list says "
          f"{mine.get(mine_order)} · {logged} moves logged")


# --------------------------------------------------------------------------------------


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    print(f"\nGate 9 on {SITE}\n" + "-" * 72)
    try:
        fx = build_fixtures()
        mine_order = book(fx, fx.mine_shop)
        other_order = book(fx, fx.other_shop)

        criterion_1(fx, mine_order, other_order)
        claim_name = criterion_2(fx, mine_order)
        criterion_3(fx, claim_name)
        criterion_4(fx, mine_order)
    finally:
        frappe.db.rollback()
        # Let go of the fixtures before purging them. A Single still pointing at a purged Item
        # is not this script's problem - it is the next twenty tests' problem.
        try:
            restore_claim_settings()
        except Exception as e:
            print(f"  !! could not restore FieldMate Settings: {e}")
        try:
            purge("G9")
        except Exception as e:
            print(f"  !! could not clean up: {e} - run scripts/clean_gate_fixtures.py")
        frappe.destroy()

    print("-" * 72)
    passed = sum(1 for *_, ok, _d in results if ok)
    print(f"Gate 9: {passed}/{len(results)} criteria passed\n")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
