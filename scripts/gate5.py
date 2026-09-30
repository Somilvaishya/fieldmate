"""Gate 5 — verify all four criteria on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate5.py [site]

Everything it creates is rolled back at the end, so it is safe to run against testerp2. It
proves the criteria against the real database rather than against mocks, which is the whole point
of a gate.

Criterion 3 is read as ADR-024 rewrote it: a van day reconciles to what was loaded, and the Stock
Ledger is **not touched at all**. The stock in the vehicle is the distributor's — we sold it to
them at primary billing — so anything of ours moving would be recording a sale we did not make.
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
    """A rep, a shop, a distributor and two priced items, all made here.

    Nothing leans on what happens to be on the site: a gate that passes only where somebody
    already set up a case size proves nothing about the site it will really run on.
    """
    territory = frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("G5-TERR"),
        "parent_territory": "All Territories", "is_group": 0,
    }).insert(ignore_permissions=True)

    group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
    customer = frappe.get_doc({
        "doctype": "Customer", "customer_name": uid("G5-DIST"),
        "customer_type": "Company", "customer_group": group,
    }).insert(ignore_permissions=True)

    distributor = frappe.get_doc({
        "doctype": "FieldMate Distributor Profile",
        "customer": customer.name, "territory": territory.name,
    }).insert(ignore_permissions=True)

    user = frappe.get_doc({
        "doctype": "User", "email": f"{uid('g5')}@fieldmate.test",
        "first_name": "Gate Five", "send_welcome_email": 0,
        "roles": [{"role": "FieldMate Field Rep"}],
    }).insert(ignore_permissions=True)

    rep = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": user.name,
        "full_name": "Gate Five", "designation": "Field Rep",
        "territory": territory.name, "status": "Active",
    }).insert(ignore_permissions=True)

    outlet = frappe.get_doc({
        "doctype": "FieldMate Outlet", "outlet_name": uid("G5-SHOP"),
        "mobile_no": "9800000000", "distributor": customer.name,
        "territory": territory.name, "approval_status": "Approved",
    }).insert(ignore_permissions=True)

    price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
    skus = []
    for _ in range(2):
        code = uid("G5-ITEM")
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
        frappe.get_doc({
            "doctype": "Item Price", "item_code": code, "price_list": price_list,
            "selling": 1, "price_list_rate": 100,
        }).insert(ignore_permissions=True)
        skus.append(code)

    frappe.get_doc({
        "doctype": "FieldMate Product Catalogue", "catalogue_name": uid("G5-CAT"),
        "is_active": 1, "territory": territory.name,
        "items": [{"item_code": code} for code in skus],
    }).insert(ignore_permissions=True)

    frappe.db.commit()
    # Named `skus`, not `items`: frappe._dict is a dict, so `.items` is the dict method
    # and a key of that name is unreachable.
    return frappe._dict(rep=rep, outlet=outlet, distributor=distributor, skus=skus,
                        customer=customer.name)


# --------------------------------------------------------------------------------------


def criterion_1(fx):
    """A file with 3 bad rows imports the good rows and reports the 3 with row numbers."""
    from fieldmate.services import secondary_sales as importer

    good, ghost = fx.skus[0], "G5-NO-SUCH-ITEM"
    text = "\n".join([
        "Date,Item Code,Qty,Amount,Shop Name",
        f"{today()},{good},10,1000,{fx.outlet.outlet_name}",   # row 2  good
        f"{today()},{ghost},4,400,Verma Stores",                # row 3  unknown item
        f"{today()},{good},abc,100,Gupta Kirana",               # row 4  qty not a number
        f"{today()},{good},7,700,Singh Provisions",             # row 5  good
        f"not-a-date,{good},3,300,Rao Stores",                  # row 6  bad date
        f"{today()},{good},2,200,Iyer Mart",                    # row 7  good
    ])

    result = importer.import_file(fx.distributor.name, text,
                                  add_days(today(), -30), today(), file_name="gate5.csv")
    doc = frappe.get_doc("FieldMate Secondary Sales", result["name"])
    rows = [r["row"] for r in result["rejected"]]

    check(1, "A file with 3 bad rows imports the good rows and reports the 3",
          doc.total_lines == 3 and rows == [3, 4, 6] and doc.rows_rejected == 3,
          f"imported {doc.total_lines}, rejected rows {rows}, "
          f"reasons recorded: {'yes' if doc.rejections else 'no'}")

    check(4, "No secondary sales document produces a GL Entry",
          frappe.db.count("GL Entry", {"voucher_no": doc.name}) == 0
          and not frappe.db.exists("GL Entry", {"voucher_type": "FieldMate Secondary Sales"}),
          "nothing posted for the import")
    return doc


def criterion_2(fx):
    """Implied offtake matches a hand calculation across a month.

    Two periods, not one, because the chain matters as much as the formula:

        month 1:  100 opening + 200 primary -  60 closing = 240 sold on
        month 2:   60 opening + 500 primary -  90 closing = 470 sold on

    Month 2's opening is left blank on purpose. It has to be carried from month 1's closing, or
    a chain of months quietly stops adding up and nobody notices until a quarter is wrong.

    The distributor reported 500 for month 2 against an implied 470, so the gap is -30 - either
    sales nobody recorded or stock that has gone missing, and both are a phone call.
    """
    item = fx.skus[0]

    first = frappe.get_doc({
        "doctype": "FieldMate Distributor Stock",
        "distributor": fx.distributor.name,
        "from_date": add_days(today(), -60), "to_date": add_days(today(), -31),
        "items": [{"item_code": item, "opening_qty": 100, "primary_qty": 200, "closing_qty": 60}],
    })
    first.insert(ignore_permissions=True)
    first.submit()

    second = frappe.get_doc({
        "doctype": "FieldMate Distributor Stock",
        "distributor": fx.distributor.name,
        "from_date": add_days(today(), -30), "to_date": today(),
        # Opening left blank on purpose: it must be carried from the period before, or a chain
        # of months quietly stops adding up.
        "items": [{"item_code": item, "opening_qty": 0, "primary_qty": 500, "closing_qty": 90,
                   "reported_secondary_qty": 500}],
    })
    second.insert(ignore_permissions=True)

    row = second.items[0]
    check(2, "Implied offtake matches the hand calculation, and opening carries forward",
          first.items[0].secondary_qty == 240
          and row.opening_qty == 60
          and row.secondary_qty == 470
          and row.variance_qty == -30,
          f"month 1: 100+200-60 = {flt(first.items[0].secondary_qty):g} · "
          f"month 2 opening carried = {flt(row.opening_qty):g}, "
          f"60+500-90 = {flt(row.secondary_qty):g}, "
          f"against a reported 500 the gap is {flt(row.variance_qty):g}")


def criterion_3(fx):
    """Van load -> 3 cash sales -> settle-in returns the van to zero, and the Stock Ledger is
    never touched."""
    from fieldmate.services import order as order_service
    from fieldmate.services import stock as stock_service

    item = fx.skus[0]
    before_sle = frappe.db.count("Stock Ledger Entry")
    before_se = frappe.db.count("Stock Entry")
    before_gl = frappe.db.count("GL Entry")

    frappe.set_user(fx.rep.user)
    try:
        load = stock_service.save_load({
            "load_date": today(), "distributor": fx.distributor.name,
            "vehicle_no": "MH-12-AQ 4471", "client_uuid": uid("VLD"),
            "items": [{"item_code": item, "godown_qty": 120, "counted_qty": 120}],
        }, fx.rep.name)

        # Three cash sales off the van, 10 units each.
        for _ in range(3):
            created = order_service.create({
                "outlet": fx.outlet.name, "payment_term": "Cash on Delivery",
                "client_uuid": uid("ORD"),
                "lines": [{"item_code": item, "qty": 10}],
            }, fx.rep.name)
            order_service.submit_order(created["name"])

        settled = stock_service.save_settlement({
            "van_load": load["name"], "client_uuid": uid("VST"),
            "items": [{"item_code": item, "returned_good": 90}],
        }, fx.rep.name)
    finally:
        frappe.set_user("Administrator")

    check(3, "Van load, 3 cash sales, settle-in leaves nothing unaccounted and no stock moves",
          settled["loaded_qty"] == 120
          and settled["sold_qty"] == 30
          and settled["returned_qty"] == 90
          and settled["short_qty"] == 0
          and frappe.db.count("Stock Ledger Entry") == before_sle
          and frappe.db.count("Stock Entry") == before_se,
          f"120 loaded - 30 sold - 90 returned = {flt(settled['short_qty']):g} short · "
          f"cash to hand over {flt(settled['cash_to_hand_over']):g} · "
          f"Stock Ledger Entries {before_sle} -> {frappe.db.count('Stock Ledger Entry')}")

    check("4b", "A van day produces no GL Entry either",
          frappe.db.count("GL Entry") == before_gl,
          f"GL Entries {before_gl} -> {frappe.db.count('GL Entry')}")

    # The shortfall guard is the point of the screen, so prove it refuses rather than rounds.
    frappe.set_user(fx.rep.user)
    refused = False
    try:
        stock_service.save_settlement({
            "van_load": load["name"], "client_uuid": uid("VST"),
            "items": [{"item_code": item, "returned_good": 85}],
        }, fx.rep.name)
    except frappe.ValidationError:
        refused = True
    finally:
        frappe.set_user("Administrator")

    check("3b", "A shortfall cannot be settled without an explanation", refused,
          "5 units short was refused until somebody says what happened to them")


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    print(f"\nGate 5 on {SITE}\n" + "-" * 70)
    try:
        fx = build_fixtures()
        criterion_1(fx)
        criterion_2(fx)
        criterion_3(fx)
    finally:
        # A rollback is not enough on its own. This script commits its fixtures, and several of
        # the services it exercises commit internally anyway, so a transaction lasting to the end
        # was never on offer - six runs of gate2 left 868 records on testerp2 before anybody
        # noticed. The rollback stays as a backstop; `purge` is what actually clears up.
        frappe.db.rollback()
        try:
            purge("G5")
        except Exception as e:
            print(f"  !! could not clean up: {e} - run scripts/clean_gate_fixtures.py")
        frappe.destroy()

    print("-" * 70)
    passed = sum(1 for *_, ok, _d in results if ok)
    print(f"Gate 5: {passed}/{len(results)} criteria passed\n")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
