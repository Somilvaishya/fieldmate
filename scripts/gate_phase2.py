"""Phase 2 gate — the Holi season, verified on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate_phase2.py [site]

The plan's four "done when" lines, each written as something that either happens or does not:

  1. A booking with an advance and two post-dated cheques posts **one** Sales Order with the
     right payment schedule.
  2. An allocation run on short stock gives the expected split under **each** rule, and can be
     reverted.
  3. A released dispatch plan produces Delivery Notes and invoices with advances allocated.
  4. The cockpit totals match ERPNext for a test season.

The fourth is asked as two: the goods figure, which is ours to get right, and the tax figure,
which can only be compared on a site where ERPNext puts a tax head on a sales document at all.
Asking them together would have let a bench with no GST setup read as a broken cockpit.

Three of them are only worth anything on **short** stock and **unpaid** bookings, so the fixture
builds exactly that: two bookings against one season, one of them paid and one not, and less stock
in the warehouse than the two of them ask for together. A gate run against plentiful stock would
pass on an allocator that handed everybody everything.

Criterion 1 carries a negative inside it: before the advance arrives there must be **no** Sales
Order at all. That is the whole commercial point of a season - the company plans against the book,
and nothing is planned for a booking nobody has paid for.

What is not here: the phone. The screens from step 9 have a Vitest suite of their own
(`frontend/tests/`), and what a rep sees on the handset is in MANUAL_TESTS_PHASE2_SEASON.md and
named there as untested rather than implied to be done.

Everything it creates carries the `P2-` prefix and is purged at the end. A rollback is not enough
on its own: a submitted Sales Order, Delivery Note, Sales Invoice and Payment Entry each commit,
which is how six runs of an earlier gate left 868 records on testerp2.
"""

import sys

import frappe
from frappe.utils import add_days, flt, today

from _guard import hsn_code, require_test_site

SITE = sys.argv[1] if len(sys.argv) > 1 else "testerp2.web.gargsystems.com"

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from clean_gate_fixtures import purge

PREFIX = "P2"
results = []

# What the two bookings ask for, and what the warehouse will actually hold. Deliberately short:
# 30 asked for against 20 in stock, so every rule has a real decision to make and criterion 2 can
# tell three answers apart.
BIG, SMALL, STOCK = 20, 10, 20
RATE = 100


def check(number, name, passed, detail=""):
    results.append((number, name, passed, detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {number}. {name}")
    if detail:
        print(f"         {detail}")


def skip(number, name, why):
    results.append((number, name, None, why))
    print(f"  [SKIP] {number}. {name}")
    print(f"         {why}")


def uid(prefix):
    return f"{PREFIX}-{prefix}-{frappe.generate_hash(length=8)}"


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------


def with_required_selects(data: dict) -> dict:
    """Fill any mandatory Select another app put on Item.

    india_compliance and friends add their own, and a gate that hard-codes the fields it knows
    about stops working the day somebody installs one more.
    """
    for field in frappe.get_all("Custom Field",
                                filters={"dt": "Item", "reqd": 1, "fieldtype": "Select"},
                                fields=["fieldname", "options"]):
        choices = [c for c in (field.options or "").split("\n") if c]
        if choices:
            data.setdefault(field.fieldname, choices[0])
    return data


def build():
    from fieldmate.services import settings as settings_service

    company = (settings_service.value("default_company")
               or frappe.db.get_value("Company", {}, "name"))
    currency = frappe.db.get_value("Company", company, "default_currency")
    group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
    root = frappe.db.get_value(
        "Territory", {"is_group": 1, "parent_territory": ("in", ("", None))}, "name")
    warehouse = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")

    territory = frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("TERR"),
        "parent_territory": root, "is_group": 0,
    }).insert(ignore_permissions=True)

    # The season's own list. A booking is priced from the season's list and not the party's -
    # that is what a season price list is for - so the two are different documents here, which
    # is the only way a test of that rule is worth anything.
    season_list = frappe.get_doc({
        "doctype": "Price List", "price_list_name": uid("SEASON-PL"),
        "selling": 1, "enabled": 1, "currency": currency,
    }).insert(ignore_permissions=True)

    item_code = uid("ITEM")
    data = with_required_selects({
        "doctype": "Item", "item_code": item_code, "item_name": "Gate soap",
        "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
        "stock_uom": "Nos" if frappe.db.exists("UOM", "Nos")
                     else frappe.db.get_value("UOM", {}, "name"),
        "is_stock_item": 1, "is_sales_item": 1,
    })
    if frappe.get_meta("Item").has_field("gst_hsn_code"):
        data["gst_hsn_code"] = hsn_code()
    frappe.get_doc(data).insert(ignore_permissions=True)

    frappe.get_doc({
        "doctype": "Item Price", "item_code": item_code,
        "price_list": season_list.name, "selling": 1, "price_list_rate": RATE,
    }).insert(ignore_permissions=True)

    # The balance terms finance maintains. Named on the season, never copied onto the order: the
    # schedule on the Sales Order is ERPNext's own doing from this template.
    terms = frappe.get_doc({
        "doctype": "Payment Terms Template", "template_name": uid("PTT"),
        "terms": [
            {"payment_term_name": f"{PREFIX} half on 30",
             "due_date_based_on": "Day(s) after invoice date",
             "invoice_portion": 50, "credit_days": 30},
            {"payment_term_name": f"{PREFIX} half on 60",
             "due_date_based_on": "Day(s) after invoice date",
             "invoice_portion": 50, "credit_days": 60},
        ],
    }).insert(ignore_permissions=True)

    distributor = frappe.get_doc({
        "doctype": "Customer", "customer_name": uid("DIST"),
        "customer_type": "Company", "customer_group": group, "territory": territory.name,
        "fm_tier": "Distributor", "fm_buys_from": "Company",
        # The depot that serves this party, and therefore the warehouse its bookings reserve
        # from. Without it ERPNext defaults a warehouse per line off the Item master, and a gate
        # that stocks one warehouse while the Sales Order names another proves nothing.
        "fm_warehouse": warehouse,
        "credit_limits": [{"company": company, "credit_limit": 10_000_000}],
    }).insert(ignore_permissions=True)

    def make_user(role, prefix):
        return frappe.get_doc({
            "doctype": "User", "email": f"{uid(prefix)}@fieldmate.test".lower(),
            "first_name": prefix.title(), "send_welcome_email": 0,
            "roles": [{"role": role}],
        }).insert(ignore_permissions=True).name

    rep_user = make_user("FieldMate Field Rep", "rep")
    # Somebody other than the rep: a deposit cannot be confirmed by whoever declared it, which is
    # the control that keeps a field role away from the ledger (ADR-004).
    manager = make_user("FieldMate Area Manager", "mgr")

    rep = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": rep_user, "full_name": "Gate Two",
        "designation": "Field Rep", "territory": territory.name, "company": company,
        "status": "Active", "can_collect_payment": 1,
    }).insert(ignore_permissions=True)

    frappe.get_doc({
        "doctype": "FieldMate Product Catalogue", "catalogue_name": uid("CAT"),
        "is_active": 1, "items": [{"item_code": item_code}],
    }).insert(ignore_permissions=True)

    season = frappe.get_doc({
        "doctype": "FieldMate Season", "season_name": uid("SEASON"), "company": company,
        "is_active": 1,
        "festival_date": add_days(today(), 120),
        "booking_from": add_days(today(), -5),
        "booking_to": add_days(today(), 30),
        "change_cutoff": add_days(today(), 25),
        "delivery_from": add_days(today(), 60),
        "delivery_to": add_days(today(), 110),
        "price_list": season_list.name,
        "advance_pct": 25,
        "payment_terms_template": terms.name,
    }).insert(ignore_permissions=True)

    frappe.db.commit()
    return frappe._dict(
        company=company, currency=currency, territory=territory.name,
        season=season.name, season_list=season_list.name, terms=terms.name,
        item=item_code, distributor=distributor.name, warehouse=warehouse,
        rep=rep.name, user=rep_user, manager=manager)


def as_rep(fx, fn, *args, **kwargs):
    """Run something in the rep's own session.

    Not a nicety: `submit_order` refuses an order that belongs to another rep, and to the server
    "another rep" includes Administrator. Running the rep's path as Administrator passes checks
    the field never passes.
    """
    frappe.set_user(fx.user)
    try:
        return fn(*args, **kwargs)
    finally:
        frappe.set_user("Administrator")


def book(fx, qty, on=None):
    """Take a booking and submit it. Returns the FieldMate Order's name."""
    from fieldmate.services import order as order_service

    payload = {"party_type": "Customer", "customer": fx.distributor,
               "lines": [{"item": fx.item, "qty": qty}], "client_uuid": uid("BOOK")}
    if on:
        payload["order_date"] = on
    created = as_rep(fx, order_service.create, payload, fx.rep)
    as_rep(fx, order_service.submit_order, created["name"])
    return created["name"]


def collect(fx, order, amount, mode="Cash", dated=None):
    """Money against a booking, allocated to it.

    The allocation is the whole mechanism: `FieldMate Collection.on_submit` tries the advance
    gate again for each order a receipt names, and nothing else does.
    """
    from fieldmate.services import collection as collection_service

    payload = {
        "party_type": "Distributor", "distributor": fx.distributor,
        "amount": amount, "mode": mode, "client_uuid": uid("COL"),
        "allocations": [{"reference_type": "FieldMate Order", "reference_name": order,
                         "allocated_amount": amount}],
    }
    if mode in ("Cheque", "DD"):
        payload.update({"instrument_no": uid("CHQ")[:20], "instrument_date": dated,
                        "instrument_bank": "Gate Bank"})
    return as_rep(fx, collection_service.create, payload, fx.rep)["name"]


def bank_it(fx, collections):
    """Declare the deposit as the rep, confirm it as the manager, so a Payment Entry exists.

    No field role posts to the ledger (ADR-004). An advance that has not been confirmed is money
    the rep says they took; it is only an advance ERPNext can allocate once somebody at the office
    agrees it arrived.
    """
    from fieldmate.services import collection as collection_service

    deposit = as_rep(fx, collection_service.declare_deposit, {
        "collections": list(collections), "channel": "Bank Branch",
        "reference_no": uid("SLIP")[:20], "client_uuid": uid("DEP"),
    }, fx.rep)
    collection_service.confirm_deposit(deposit["name"], confirmed_by=fx.manager)
    return deposit["name"]


def stock(fx, qty):
    """Real stock in the party's own warehouse, so ERPNext has something to reserve."""
    entry = frappe.get_doc({
        "doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
        "company": fx.company,
        # Stamped so the cleanup can find it. A Stock Entry has no name field of its own, and a
        # receipt left behind on a test site is stock that moves every later allocation.
        "remarks": f"{PREFIX} gate stock",
        "items": [{"item_code": fx.item, "qty": qty, "t_warehouse": fx.warehouse,
                   "basic_rate": 50}],
    })
    entry.flags.ignore_permissions = True
    entry.insert(ignore_permissions=True)
    entry.submit()
    return entry.name


# --------------------------------------------------------------------------------------
# criterion 1 — the booking, its advance and its schedule
# --------------------------------------------------------------------------------------


def criterion_1(fx):
    """A booking with an advance and two PDCs posts one Sales Order with the right schedule."""
    from fieldmate.services import collection as collection_service
    from fieldmate.services import order as order_service

    before = frappe.db.count("Sales Order")
    order = book(fx, BIG)
    doc = frappe.get_doc("FieldMate Order", order)

    # The negative first, and it is the commercial point of the whole phase: nothing is planned
    # for a booking nobody has paid for.
    held = doc.order_status == "Awaiting Advance" and not doc.sales_order
    nothing_posted = frappe.db.count("Sales Order") == before

    required = order_service.advance_position(doc)["required"]

    # Two post-dated cheques, which are recorded and allocated and release nothing. If one of
    # these released the booking, stock would be set aside against a cheque that may yet bounce.
    collect(fx, order, required, mode="Cheque", dated=add_days(today(), 30))
    collect(fx, order, required, mode="Cheque", dated=add_days(today(), 60))
    pdcs = collection_service.pdcs_for(order)
    still_held = frappe.db.get_value("FieldMate Order", order, "order_status") == "Awaiting Advance"

    # Then the advance itself, in money that has arrived.
    advance = collect(fx, order, required)
    doc.reload()

    # And banked, because an advance ERPNext can allocate is one somebody at the office has
    # agreed arrived. Until the deposit is confirmed there is no Payment Entry at all - which is
    # ADR-004 working, and is why criterion 3 found nothing to allocate until this line existed.
    bank_it(fx, [advance])

    one_order = frappe.db.count("Sales Order") == before + 1
    schedule = frappe.get_all(
        "Payment Schedule", filters={"parent": doc.sales_order},
        fields=["invoice_portion", "credit_days"], order_by="idx")
    named = frappe.db.get_value("Sales Order", doc.sales_order, "payment_terms_template")

    right_schedule = (
        named == fx.terms
        and len(schedule) == 2
        and sorted(flt(row.invoice_portion) for row in schedule) == [50.0, 50.0]
        and sorted(row.credit_days for row in schedule) == [30, 60]
    )

    ok = bool(held and nothing_posted and len(pdcs) == 2 and still_held
              and doc.sales_order and one_order and right_schedule)
    check(1, "A booking with an advance and two PDCs posts one Sales Order with the season's "
             "payment schedule", ok,
          f"held before payment: {held}; posted nothing while held: {nothing_posted}; "
          f"PDCs held: {len(pdcs)}; still held after the PDCs: {still_held}; "
          f"sales order {doc.sales_order!r}; exactly one: {one_order}; "
          f"template {named!r}, schedule {[(r.invoice_portion, r.credit_days) for r in schedule]}")

    return frappe._dict(order=order, sales_order=doc.sales_order, advance=advance,
                        required=required)


# --------------------------------------------------------------------------------------
# criterion 2 — the split on short stock, three ways, and back again
# --------------------------------------------------------------------------------------


def criterion_2(fx, paid):
    """Each rule gives the split it promises, and revert gives the stock back."""
    from fieldmate import compat
    from fieldmate.services import allocation as allocation_service

    if not compat.stock_reservation_enabled():
        skip(2, "An allocation run on short stock splits by each rule and can be reverted",
             "stock reservation is switched off on this site - switch on Enable Stock "
             "Reservation in Stock Settings and run again")
        return None

    # A second booking, taken later and with nothing paid against it. Later, so First Booked has
    # an order to prefer; unpaid, so Advance First has one to pass over.
    unpaid = book(fx, SMALL, on=today())
    frappe.db.set_value("FieldMate Season", fx.season, "advance_pct", 0, update_modified=False)
    frappe.clear_document_cache("FieldMate Season", fx.season)
    from fieldmate.services import order as order_service
    order_service.release_if_paid(unpaid)
    unpaid_so = frappe.db.get_value("FieldMate Order", unpaid, "sales_order")

    stock(fx, STOCK)

    asked = BIG + SMALL
    splits = {}
    for rule in allocation_service.RULES:
        allocation_service.revert(fx.season)
        plan = allocation_service.apply(fx.season, rule)
        # Summed per order, not assigned: a booking of several items holds one
        # reservation per line, and keying straight off the order would keep only the last.
        held = {}
        for row in allocation_service.held_by(fx.season):
            held[row["sales_order"]] = held.get(row["sales_order"], 0.0) + flt(row["reserved"])
        splits[rule] = {
            "paid": held.get(paid.sales_order, 0.0),
            "unpaid": held.get(unpaid_so, 0.0),
            "total": sum(held.values()),
            "short": sum(flt(item["short"]) for item in plan["items"]),
        }

    allocation_service.revert(fx.season)
    after_revert = sum(flt(row["reserved"]) for row in allocation_service.held_by(fx.season))

    # What each rule promises, on 20 in stock against 30 asked for:
    #
    #   Advance First  the booking with money against it is filled first -> 20 / 0
    #   First Booked   the earlier booking is filled first, which here is the same one -> 20 / 0
    #   Pro Rata       the same proportion to everybody, in **whole units**
    #
    # Advance First and First Booked agreeing is not a weak test: they agree *because* the paid
    # booking is also the earlier one, and what is asserted is that neither invented a third
    # answer. Pro Rata is what tells them apart from a rule that just fills in order.
    #
    # Pro rata restated here rather than copied: 20 x 20/30 is 13.33 and nobody can reserve a
    # third of a bar of soap, so each share is floored and the stray unit goes to the largest
    # ask. That is what `allocation.split` documents, and the arithmetic is written out again so
    # this is a check and not a tautology.
    floor_big = int(STOCK * BIG / asked)
    floor_small = int(STOCK * SMALL / asked)
    stray = STOCK - floor_big - floor_small
    want = {
        allocation_service.ADVANCE_FIRST: (float(STOCK), 0.0),
        allocation_service.FIRST_BOOKED: (float(STOCK), 0.0),
        # BIG is the larger ask, so the stray unit lands on it.
        allocation_service.PRO_RATA: (float(floor_big + stray), float(floor_small)),
    }

    wrong = [
        f"{rule}: {splits[rule]['paid']}/{splits[rule]['unpaid']} "
        f"(expected {want[rule][0]}/{want[rule][1]})"
        for rule in allocation_service.RULES
        if (round(splits[rule]["paid"], 3), round(splits[rule]["unpaid"], 3)) != want[rule]
    ]
    never_over = all(round(s["total"], 3) <= STOCK for s in splits.values())
    short_said = all(round(s["short"], 3) == round(asked - STOCK, 3) for s in splits.values())

    ok = not wrong and never_over and short_said and round(after_revert, 3) == 0.0
    check(2, "An allocation run on short stock splits by each rule and can be reverted", ok,
          (f"splits {splits}; nothing over-reserved: {never_over}; shortfall reported: "
           f"{short_said}; held after revert: {after_revert}")
          + (f"; WRONG: {'; '.join(wrong)}" if wrong else ""))

    return frappe._dict(unpaid=unpaid, unpaid_so=unpaid_so)


# --------------------------------------------------------------------------------------
# criterion 3 — out of the warehouse, and billed with the advance against it
# --------------------------------------------------------------------------------------


def criterion_3(fx, paid):
    """A dispatch produces Delivery Notes and Sales Invoices with the advance allocated."""
    from fieldmate import compat
    from fieldmate.services import allocation as allocation_service
    from fieldmate.services import dispatch as dispatch_service

    if not compat.stock_reservation_enabled():
        skip(3, "A dispatch produces Delivery Notes and invoices with the advance allocated",
             "stock reservation is switched off on this site, so nothing could be reserved "
             "to dispatch")
        return

    # Reserve for the paid booking only, then ship exactly it. A dispatch of a booking nobody
    # allocated is a dispatch of stock somebody else is holding.
    allocation_service.revert(fx.season)
    allocation_service.apply(fx.season, allocation_service.ADVANCE_FIRST)

    shipped = dispatch_service.deliver(fx.season, orders=[paid.order])
    notes = [row["delivery_note"] for row in shipped.get("delivered", [])]
    billed = dispatch_service.invoice(fx.season, delivery_notes=notes)
    invoices = [row["sales_invoice"] for row in billed.get("invoiced", [])]

    # The advance, as ERPNext sees it: the Payment Entry our deposit confirmation posted, and
    # whether this invoice has it against it.
    entry = frappe.db.get_value("FieldMate Collection", paid.advance, "payment_entry")
    allocated = 0.0
    for invoice in invoices:
        allocated += sum(flt(row.allocated_amount) for row in frappe.get_all(
            "Sales Invoice Advance",
            filters={"parent": invoice, "reference_name": entry},
            fields=["allocated_amount"]))

    submitted = all(frappe.db.get_value("Sales Invoice", name, "docstatus") == 1
                    for name in invoices)

    ok = bool(notes and invoices and submitted and entry
              and round(allocated, 2) == round(flt(paid.required), 2))
    check(3, "A dispatch produces Delivery Notes and invoices with the advance allocated", ok,
          f"delivery notes {notes}; invoices {invoices}; all submitted: {submitted}; "
          f"payment entry {entry!r}; advance allocated {allocated} of {paid.required}; "
          f"skipped {shipped.get('skipped')} / {billed.get('skipped')}")


# --------------------------------------------------------------------------------------
# criterion 4 — the cockpit against ERPNext
# --------------------------------------------------------------------------------------


def criterion_4(fx):
    """Every figure the cockpit prints, reconciled against the documents behind it.

    Split in two on purpose. The **goods** figure is ours to get right and is asserted outright.
    The **tax** figure can only be compared on a site where ERPNext puts a tax head on a sales
    document at all, and that is a question about the site, not about the cockpit - so it is asked
    of ERPNext first and reported as not answerable where the answer is no.
    """
    from fieldmate.services import cockpit as cockpit_service

    view = cockpit_service.summary(fx.season)

    bookings = frappe.get_all(
        "FieldMate Order",
        filters={"season": fx.season, "docstatus": 1,
                 "order_status": ["not in", ["Cancelled", "Rejected"]]},
        fields=["name", "sales_order", "net_total", "tax_total", "grand_total"])

    # --- the cockpit's own arithmetic
    counted_all = view["bookings"] == len(bookings)
    value_adds_up = flt(view["value"], 2) == flt(
        sum(flt(b.grand_total) or flt(b.net_total) for b in bookings), 2)
    # The state breakdown has to account for every booking exactly once, or the page shows a
    # season with more or fewer bookings in its columns than it has.
    state_count = sum(row["bookings"] for row in view["by_state"])
    states_add_up = state_count == len(bookings)
    # Owing is value less what has arrived, never a figure of its own.
    owing_adds_up = flt(view["owing"], 2) == flt(
        max(0.0, flt(view["value"]) - flt(view["paid"])), 2)

    # --- and against ERPNext, for the bookings that have actually posted
    posted = [b for b in bookings if b.sales_order]
    orders = {b.name: frappe.db.get_value(
        "Sales Order", b.sales_order, ["net_total", "total_taxes_and_charges", "grand_total"],
        as_dict=True) for b in posted}

    net_mismatch = [
        f"{b.name}: ours {flt(b.net_total, 2)} vs {b.sales_order} "
        f"{flt(orders[b.name].net_total, 2)}"
        for b in posted if flt(b.net_total, 2) != flt(orders[b.name].net_total, 2)
    ]

    ok = bool(counted_all and value_adds_up and states_add_up and owing_adds_up
              and posted and not net_mismatch)
    check(4, "The cockpit's totals reconcile against the Sales Orders behind them", ok,
          f"{view['bookings']} bookings of {len(bookings)}, {len(posted)} posted; "
          f"value {view['value']}; paid {view['paid']}, owing {view['owing']}; "
          f"states {[(r['state'], r['bookings']) for r in view['by_state']]}"
          + (f"; NET DISAGREES: {'; '.join(net_mismatch)}" if net_mismatch else ""))

    criterion_5(fx, posted, orders)


def criterion_5(fx, posted, orders):
    """The tax on the order is the tax on the bill.

    **FieldMate computes its tax from Item Tax Templates** - the item, then its item group - which
    is the rule `services/tax.py` implements and `frontend/src/lib/tax.js` mirrors so a rep can
    quote offline. **ERPNext puts tax on a sales document from a Sales Taxes and Charges Template
    in its header**, and an Item Tax Template only overrides the rate of an account row that
    header already carries. Two mechanisms, and a site can have the first and not the second.

    When it does, the rep reads out a figure with GST on it and the invoice goes out with none.
    That is the whole of why this is asked separately rather than folded into the total above.

    ERPNext is asked first whether it would put a tax head on a document for this party at all. A
    no is not a cockpit failure and is not pretended to be one: on this bench the company has no
    GSTIN and no address, so india_compliance can determine no place of supply and selects no GST
    template - the same environment gap that stops an e-way bill being raised here. It is reported
    as not answerable, with the cause, so that running this on a pilot site asks the real question.
    """
    from erpnext.accounts.party import get_party_details

    name = "The tax on the booking is the tax on its Sales Order"

    if not posted:
        skip(5, name, "no booking posted a Sales Order, so there was nothing to compare")
        return

    details = get_party_details(party=fx.distributor, party_type="Customer",
                                company=fx.company, doctype="Sales Order")
    head = details.get("taxes_and_charges")

    if not head:
        gstin = (frappe.db.get_value("Company", fx.company, "gstin")
                 if frappe.get_meta("Company").has_field("gstin") else None)
        skip(5, name,
             f"ERPNext selects no tax template for this party on this site, so no sales document "
             f"here carries a tax head at all - company GSTIN {gstin!r}, customer tax category "
             f"{frappe.db.get_value('Customer', fx.distributor, 'tax_category')!r}, "
             f"{frappe.db.count('Tax Rule')} Tax Rule(s). FieldMate's own figure comes from the "
             f"Item Tax Template on the item group, so a booking here quotes tax the company "
             f"will not bill. Configure the company's GSTIN and address, or a Tax Rule, and run "
             f"this again")
        return

    mismatch = [
        f"{order}: ours {flt(row.tax_total, 2)} vs {row.sales_order} "
        f"{flt(orders[order].total_taxes_and_charges, 2)}"
        for order, row in ((b.name, b) for b in posted)
        if flt(row.tax_total, 2) != flt(orders[order].total_taxes_and_charges, 2)
    ]
    check(5, name, not mismatch,
          f"ERPNext selects {head!r} for this party"
          + (f"; DISAGREES: {'; '.join(mismatch)}" if mismatch
             else "; every booking's tax matches its Sales Order"))



# --------------------------------------------------------------------------------------


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    from fieldmate.services import settings as settings_service

    print(f"\nPhase 2 gate on {SITE}\n" + "-" * 72)

    # Primary sales have to be on for a booking to be one at all - a Booking *is* a primary sale,
    # governed by the same switch. Recorded and put back whatever happens: leaving a site's sales
    # mode switched off would stop every order on it.
    live = settings_service.get()
    was = {"enable_primary_sales": live.get("enable_primary_sales")}
    frappe.db.set_single_value("FieldMate Settings", {"enable_primary_sales": 1})
    frappe.cache().delete_value("fieldmate_settings")

    fx = None
    try:
        fx = build()
        paid = criterion_1(fx)
        criterion_2(fx, paid)
        criterion_3(fx, paid)
        criterion_4(fx)
    finally:
        # Reservations first: ERPNext will not let a Sales Order be cancelled while it is holding
        # stock, so a purge that ran before this one would stop on the first booking and leave
        # everything after it behind.
        if fx:
            try:
                from fieldmate.services import allocation as allocation_service
                allocation_service.revert(fx.season)
                frappe.db.commit()
            except Exception as e:
                print(f"  !! could not release this season's reservations: {e}")
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
    skipped = sum(1 for *_, ok, _d in results if ok is None)
    total = len(results) - skipped
    print(f"Phase 2: {passed}/{total} criteria passed"
          + (f", {skipped} not answerable on this bench" if skipped else ""))
    print("The phone is not covered here - see docs/MANUAL_TESTS_PHASE2_SEASON.md\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
