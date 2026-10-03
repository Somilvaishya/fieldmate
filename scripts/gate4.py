"""Gate 4 — verify all six criteria on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate4.py [site] [--skip-parity]

Written late, like Gate 2, and for the same reason: Phase 4 shipped with a parity suite and a
large unit suite, and both were treated as though they were the gate. They are not. A green
suite runs against fixtures; a gate runs against a real site, with the real permission rules,
the real hierarchy and whatever else is installed on that bench.

**Three of the six criteria as written are stale, and are restated here rather than quietly
dropped.** They were written before ADR-023, when a retailer order was expected to become an
ERPNext Sales Order. It never does now. So:

  criterion 2   was "exactly one FieldMate Order and one Sales Order"
                now  exactly one FieldMate Order, one distributor queue, and NO accounting
                     document at all
  criterion 3   was "Sales Order only after approval"
                now  a breach is blocked and routed to an approver, and approval releases the
                     order to the queue - still with no accounting document
  criterion 6   was "cancelling the order cancels its Sales Order, no orphan"
                now  cancelling reverses the scheme ledger and returns the budget, and there is
                     no orphan of any kind

Criterion 5 - a 40-line cart re-pricing in under 150 ms on a mid-range Android - cannot be
answered from a server. It is timed here on this machine so the arithmetic itself is known not
to be the bottleneck, and reported as **not run** rather than passed, because a laptop is not
the phone the criterion is about.
"""

import subprocess
import sys
import time
from pathlib import Path

import frappe
from frappe.utils import add_days, flt, today

from _guard import require_test_site

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
    if not arg.startswith("--"):
        SITE = arg

SKIP_PARITY = "--skip-parity" in sys.argv

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from clean_gate_fixtures import purge

APP = Path(__file__).resolve().parent.parent

results = []


def check(number, name, passed, detail=""):
    results.append((number, name, bool(passed), detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {number}. {name}")
    if detail:
        print(f"         {detail}")


def skip(number, name, detail):
    results.append((number, name, None, detail))
    print(f"  [SKIP] {number}. {name}")
    print(f"         {detail}")


def uid(prefix):
    return f"{prefix}-{frappe.generate_hash(length=8)}"


# --------------------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------------------


def make_user(name, role):
    was = frappe.flags.in_import
    frappe.flags.in_import = True
    try:
        return frappe.get_doc({
            "doctype": "User", "email": f"{uid(name)}@fieldmate.test",
            "first_name": name.title(), "enabled": 1, "user_type": "System User",
            "send_welcome_email": 0, "roles": [{"role": role}],
        }).insert(ignore_permissions=True).name
    finally:
        frappe.flags.in_import = was


def make_item(rate=100, case_size=None):
    code = uid("G4-ITEM")
    data = {
        "doctype": "Item", "item_code": code, "item_name": code,
        "item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
        "stock_uom": "Nos" if frappe.db.exists("UOM", "Nos")
                     else frappe.db.get_value("UOM", {}, "name"),
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
    doc = frappe.get_doc(data)
    doc.insert(ignore_permissions=True)

    price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
    frappe.get_doc({"doctype": "Item Price", "item_code": code, "price_list": price_list,
                    "selling": 1, "price_list_rate": rate}).insert(ignore_permissions=True)
    return code


def build_fixtures():
    company = frappe.db.get_single_value("FieldMate Settings", "default_company") \
        or frappe.db.get_value("Company", {}, "name")

    territory = frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("G4-TERR"),
        "parent_territory": "All Territories", "is_group": 0,
    }).insert(ignore_permissions=True).name

    # The credit limit goes on the DISTRIBUTOR's Customer, not on the shop.
    #
    # The shop is not a party to the sale at all - it buys from its distributor (ADR-023), and
    # the limit that binds is the distributor's with us. Setting it on the outlet, which is what
    # this gate did first, produced an order that sailed through "Within Limit" and a criterion
    # that tested nothing.
    customer = frappe.get_doc({
        "doctype": "Customer", "customer_name": uid("G4-DIST"), "customer_type": "Company",
        "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
        "territory": territory,
        "credit_limits": [{"company": company, "credit_limit": 500}],
        # A distributor is a Customer with a channel tier. There is no FieldMate Distributor
        # Profile beside it any more, and `distributor` below is the same document.
        "fm_tier": "Distributor", "fm_buys_from": "Company",
    }).insert(ignore_permissions=True)
    distributor = customer

    rep_user = make_user("g4rep", "FieldMate Field Rep")
    manager_user = make_user("g4mgr", "FieldMate Area Manager")

    # The manager is a field user too, and the rep reports to them. Holding the Area Manager role
    # is not enough on its own any more: an order may be decided by the rep's **own** manager,
    # their depot or an administrator, and a manager three territories away is none of those.
    # Before this the gate made a manager who was a stranger to the rep and proved nothing about
    # who may approve - it would have passed with no rule at all.
    manager = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": manager_user, "full_name": "Gate Four Manager",
        "designation": "Area Manager", "territory": territory, "status": "Active",
        "company": company,
    }).insert(ignore_permissions=True)

    rep = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": rep_user, "full_name": "Gate Four",
        "designation": "Field Rep", "territory": territory, "status": "Active",
        "company": company, "reports_to": manager.name,
    }).insert(ignore_permissions=True)

    outlet = frappe.get_doc({
        "doctype": "FieldMate Outlet", "outlet_name": uid("G4-SHOP"),
        "mobile_no": "9800000000", "distributor": customer.name,
        "territory": territory, "approval_status": "Approved",
    }).insert(ignore_permissions=True)

    sku = make_item(rate=100)
    frappe.get_doc({
        "doctype": "FieldMate Product Catalogue", "catalogue_name": uid("G4-CAT"),
        "is_active": 1, "territory": territory, "items": [{"item_code": sku}],
    }).insert(ignore_permissions=True)

    frappe.db.commit()
    return frappe._dict(company=company, territory=territory, customer=customer.name,
                        distributor=distributor.name, rep=rep, manager=manager_user,
                        outlet=outlet, sku=sku)


def make_scheme(fx, budget=None, on_exhaust="Block", pct=5, from_qty=10):
    doc = frappe.get_doc({
        "doctype": "FieldMate Scheme", "scheme_name": uid("G4-SCH"),
        "scheme_type": "Volume Slab", "priority": 10, "is_active": 1,
        "basis": "Qty", "basis_uom": "Unit", "measured_over": "Item Set",
        "stacking": "Stackable", "valid_from": add_days(today(), -7),
        "on_exhaust": on_exhaust, "company": fx.company,
        "budget_amount": budget or 0,
        "items": [{"item_code": fx.sku}],
        "slabs": [{"slab_idx": 1, "from_value": from_qty, "is_open_ended": 1,
                   "benefit_kind": "Percent Discount", "per": "Slab", "discount_pct": pct}],
    })
    doc.insert(ignore_permissions=True)
    doc.submit()
    return doc


def as_rep(fx, fn, *args, **kwargs):
    frappe.set_user(fx.rep.user)
    try:
        return fn(*args, **kwargs)
    finally:
        frappe.set_user("Administrator")


def book(fx, qty=20, **extra):
    """An order the way the phone sends one: a client uuid, and nothing else invented."""
    from fieldmate.services import order as order_service

    payload = {"outlet": fx.outlet.name, "client_uuid": uid("ORD"),
               "lines": [{"item_code": fx.sku, "qty": qty}]}
    payload.update(extra)
    created = as_rep(fx, order_service.create, payload, fx.rep.name)
    return created


# --------------------------------------------------------------------------------------
# criterion 1 — the parity suite
# --------------------------------------------------------------------------------------


def criterion_1():
    """One corpus, two engines, three diffs. Run as a subprocess, exactly as CI runs it."""
    if SKIP_PARITY:
        skip(1, "The parity corpus: two engines and a hand-built corpus agree to the rupee",
             "--skip-parity was passed")
        return

    script = APP / "scripts" / "parity.sh"
    if not script.exists():
        check(1, "The parity corpus: two engines and a hand-built corpus agree to the rupee",
              False, "scripts/parity.sh is missing")
        return

    started = time.time()
    try:
        run = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                             timeout=900, cwd=str(APP))
    except subprocess.TimeoutExpired:
        check(1, "The parity corpus: two engines and a hand-built corpus agree to the rupee",
              False, "parity.sh did not finish inside 15 minutes")
        return
    seconds = time.time() - started

    tail = [line for line in run.stdout.splitlines() if line.strip()][-1:] or ["no output"]
    cases = ""
    for line in run.stdout.splitlines():
        if "cases" in line and ("OK" in line or "agree" in line):
            cases = line.strip()
            break

    check(1, "The parity corpus: two engines and a hand-built corpus agree to the rupee",
          run.returncode == 0,
          f"{cases or tail[0]} · {seconds:.1f}s"
          + ("" if run.returncode == 0 else f" · exit {run.returncode}"))


# --------------------------------------------------------------------------------------
# criterion 2 — one order, one queue, nothing posted
# --------------------------------------------------------------------------------------


def criterion_2(fx):
    """ADR-023, as a measurement rather than as a claim."""
    from fieldmate.services import order as order_service

    before = {
        "Sales Order": frappe.db.count("Sales Order"),
        "Sales Invoice": frappe.db.count("Sales Invoice"),
        "Delivery Note": frappe.db.count("Delivery Note"),
        "Stock Ledger Entry": frappe.db.count("Stock Ledger Entry"),
        "GL Entry": frappe.db.count("GL Entry"),
    }

    created = book(fx, qty=20)
    result = as_rep(fx, order_service.submit_order, created["name"])

    # The same push again, the way a phone with no signal retries.
    replay = as_rep(fx, order_service.create, {
        "outlet": fx.outlet.name, "client_uuid": created["client_uuid"],
        "lines": [{"item_code": fx.sku, "qty": 20}],
    }, fx.rep.name)

    after = {dt: frappe.db.count(dt) for dt in before}
    posted = {dt: after[dt] - before[dt] for dt in before if after[dt] != before[dt]}

    orders = frappe.db.count("FieldMate Order", {"client_uuid": created["client_uuid"],
                                                 "docstatus": ["<", 2]})
    queued = frappe.db.get_value("FieldMate Order", created["name"], "distributor")

    check(2, "One order, into one distributor queue, and no accounting document anywhere",
          orders == 1
          and replay["name"] == created["name"]
          and result["order_status"] == "Sent To Distributor"
          and queued == fx.distributor
          and result["sales_order"] is None
          and not posted,
          f"{orders} FieldMate Order for that uuid (a replay returned the same one) · "
          f"status {result['order_status']}, queued to {queued} · sales_order "
          f"{result['sales_order']} · nothing posted"
          + ("" if not posted else f" · POSTED {posted}"))
    return created


# --------------------------------------------------------------------------------------
# criterion 3 — a breach is held, and the right person releases it
# --------------------------------------------------------------------------------------


def criterion_3(fx):
    from fieldmate.services import order as order_service

    rule = frappe.get_doc({
        "doctype": "FieldMate Order Approval Rule", "rule_name": uid("G4-RULE"),
        "is_active": 1, "priority": 10, "territory": fx.territory,
        "on_credit_breach": 1, "approver_role": "FieldMate Area Manager",
        "approver_user": fx.manager,
    }).insert(ignore_permissions=True)

    settings = frappe.get_single("FieldMate Settings")
    was = settings.block_order_on_credit_breach
    settings.block_order_on_credit_breach = 1
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)
    frappe.cache().delete_value("fieldmate_settings")

    before_posted = frappe.db.count("GL Entry")

    # A cart far past the shop's 500 limit.
    created = book(fx, qty=200)
    submitted = as_rep(fx, order_service.submit_order, created["name"])

    held = submitted["order_status"] == "Pending Approval"
    breached = submitted["credit_status"] == "Breach"
    posted_while_held = frappe.db.count("GL Entry") != before_posted

    # The rep may not sign their own.
    self_approved = False
    try:
        as_rep(fx, order_service.approve, created["name"], "Approved")
        self_approved = True
    except Exception:
        pass

    # Nor may a manager who is not this rep's. Without this the criterion only ever proved that
    # *somebody* could approve, and would go on passing with the rule deleted outright - the same
    # vacuum criterion 6 was in before it was sharpened.
    stranger_user = make_user("g4alien", "FieldMate Area Manager")
    stranger = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": stranger_user,
        "full_name": "Gate Four Stranger", "designation": "Area Manager",
        "territory": fx.territory, "status": "Active", "company": fx.company,
    }).insert(ignore_permissions=True)
    frappe.db.commit()

    stranger_approved = False
    frappe.set_user(stranger_user)
    try:
        order_service.approve(created["name"], "Approved")
        stranger_approved = True
    except Exception:
        pass
    finally:
        frappe.set_user("Administrator")
    _ = stranger

    # The rep's own manager may.
    frappe.set_user(fx.manager)
    try:
        decided = order_service.approve(created["name"], "Approved", remarks="checked by hand")
    finally:
        frappe.set_user("Administrator")

    released = frappe.db.get_value("FieldMate Order", created["name"],
                                   ["order_status", "sales_order", "approved_by"], as_dict=True)
    posted_after = frappe.db.count("GL Entry") != before_posted

    settings = frappe.get_single("FieldMate Settings")
    settings.block_order_on_credit_breach = was
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)
    frappe.cache().delete_value("fieldmate_settings")
    # The rule is left standing. The order it held LINKS to it, so deleting it here is refused -
    # and correctly: a rule that vanished from under an order nobody could then explain. It is
    # matched by the G4- prefix and goes with everything else in the purge.
    _ = rule

    check(3, "A credit breach is held, and only the right person can release it",
          held and breached and not posted_while_held
          and not self_approved and not stranger_approved
          and decided["approval_status"] == "Approved"
          and released.approved_by == fx.manager
          and released.sales_order is None and not posted_after,
          f"order was {submitted['order_status']} with credit {submitted['credit_status']} · "
          f"the rep could approve their own: {self_approved} · "
          f"a manager who is not theirs could: {stranger_approved} · "
          f"{fx.manager.split('@')[0]}, who they report to, released it to "
          f"{released.order_status} · sales_order {released.sales_order} · "
          f"GL Entries unchanged throughout: {not posted_while_held and not posted_after}")


# --------------------------------------------------------------------------------------
# criterion 4 — budget exhaustion, and a ledger that reconciles
# --------------------------------------------------------------------------------------


def criterion_4(fx):
    from fieldmate.services import order as order_service

    # Lift the credit limit first. Criterion 3 put a 500 limit on the distributor to make a
    # breach, and now that a breaching order is actually HELD - which is what criterion 3 just
    # fixed - every order here would sit at Pending Approval and accrue nothing. Two criteria
    # sharing one fixture is how a gate ends up testing the collision between them.
    for row in frappe.get_all("Customer Credit Limit",
                              filters={"parent": fx.customer}, pluck="name"):
        frappe.db.set_value("Customer Credit Limit", row, "credit_limit", 0)
    frappe.db.commit()

    # A budget big enough for one order's benefit and not for two.
    scheme = make_scheme(fx, budget=150, on_exhaust="Block")

    first = book(fx, qty=20)
    as_rep(fx, order_service.submit_order, first["name"])
    consumed_after_one = flt(frappe.db.get_value("FieldMate Scheme", scheme.name,
                                                 "consumed_amount"))

    second = book(fx, qty=20)
    as_rep(fx, order_service.submit_order, second["name"])
    consumed_after_two = flt(frappe.db.get_value("FieldMate Scheme", scheme.name,
                                                 "consumed_amount"))

    # The ledger must equal what was consumed, to the paisa - that is the whole reconciliation.
    ledger = frappe.get_all("FieldMate Scheme Ledger",
                            filters={"scheme": scheme.name, "docstatus": 1},
                            fields=["benefit_amount"], limit_page_length=0)
    ledger_total = sum(flt(r.benefit_amount) for r in ledger)

    blocked = consumed_after_two <= flt(scheme.budget_amount) + 0.005
    reconciles = abs(ledger_total - consumed_after_two) < 0.005

    check(4, "Budget exhaustion holds the line, and the ledger reconciles to what was consumed",
          reconciles and blocked and consumed_after_one > 0,
          f"budget {flt(scheme.budget_amount):g} · consumed {consumed_after_one:g} after one "
          f"order, {consumed_after_two:g} after two · ledger holds {ledger_total:g} across "
          f"{len(ledger)} row(s) · never over budget: {blocked}")
    return scheme


# --------------------------------------------------------------------------------------
# criterion 5 — the phone, which this is not
# --------------------------------------------------------------------------------------


def criterion_5(fx):
    """Time a 40-line cart here, and refuse to call it the criterion.

    The criterion is about a mid-range Android. A laptop tells you whether the ARITHMETIC could
    ever be the problem; it cannot tell you whether the phone is fast enough, and reporting it
    as a pass would be the gate lying about the one thing it was asked.
    """
    from fieldmate.services import order as order_service

    skus = [fx.sku] + [make_item(rate=50 + i) for i in range(39)]
    catalogue = frappe.get_doc({
        "doctype": "FieldMate Product Catalogue", "catalogue_name": uid("G4-CAT"),
        "is_active": 1, "territory": fx.territory,
        "items": [{"item_code": s} for s in skus],
    })
    catalogue.insert(ignore_permissions=True)
    make_scheme(fx, pct=3, from_qty=5)

    lines = [{"item_code": s, "qty": 6} for s in skus]

    # Warm once: the first call pays for loading the compiled spec, which the phone does at
    # sync time rather than on the keystroke the criterion is about.
    as_rep(fx, order_service.estimate, fx.outlet.name, lines, fx.rep.name)

    runs = []
    for _ in range(5):
        started = time.perf_counter()
        as_rep(fx, order_service.estimate, fx.outlet.name, lines, fx.rep.name)
        runs.append((time.perf_counter() - started) * 1000)

    best, median = min(runs), sorted(runs)[len(runs) // 2]
    skip(5, "A 40-line cart re-prices in under 150 ms on a mid-range Android",
         f"not answerable from a server. On this machine the same 40-line cart priced in "
         f"{median:.0f} ms (best {best:.0f} ms) INCLUDING the database round trips the phone "
         f"does not make - so the arithmetic is not the bottleneck. The criterion still needs "
         f"a real handset.")


# --------------------------------------------------------------------------------------
# criterion 6 — cancelling leaves nothing behind
# --------------------------------------------------------------------------------------


def criterion_6(fx, scheme):
    from fieldmate.services import order as order_service

    # Give the scheme room again before booking.
    #
    # Criterion 4 leaves it deliberately exhausted, and this criterion used to run straight into
    # that: the order it books accrued NOTHING, so "the budget came back" was asked of an order
    # that had never taken any. It passed on 0 -> 0 and would have gone on passing with the
    # refund deleted outright - which is exactly the bug it exists to catch, and exactly what
    # criterion 4's own comment warns about two criteria sharing one fixture.
    frappe.db.set_value("FieldMate Scheme", scheme.name, "consumed_amount", 0,
                        update_modified=False)
    frappe.db.set_value("FieldMate Scheme", scheme.name, "budget_amount", 100000,
                        update_modified=False)
    frappe.db.commit()

    created = book(fx, qty=30)
    as_rep(fx, order_service.submit_order, created["name"])

    consumed_before = flt(frappe.db.get_value("FieldMate Scheme", scheme.name,
                                              "consumed_amount"))
    rows = frappe.get_all("FieldMate Scheme Ledger",
                          filters={"order": created["name"], "docstatus": 1},
                          fields=["benefit_amount"], limit_page_length=0)
    accrued = len(rows)
    benefit = sum(flt(r.benefit_amount) for r in rows)

    as_rep(fx, order_service.cancel, created["name"], "gate 4")

    consumed_after = flt(frappe.db.get_value("FieldMate Scheme", scheme.name,
                                             "consumed_amount"))
    left_standing = frappe.db.count("FieldMate Scheme Ledger",
                                    {"order": created["name"], "docstatus": 1})
    reversed_rows = frappe.db.count("FieldMate Scheme Ledger",
                                    {"order": created["name"], "status": "Reversed"})
    state = frappe.db.get_value("FieldMate Order", created["name"],
                                ["docstatus", "order_status", "sales_order"], as_dict=True)

    check(6, "Cancelling an order returns the budget and leaves no orphan of any kind",
          # An accrual that never happened cannot be returned, so the criterion refuses to
          # answer at all unless there was one.
          accrued > 0
          and state.docstatus == 2 and left_standing == 0 and state.sales_order is None
          # The exact amount back, not merely "no higher than before".
          and abs(consumed_after - (consumed_before - benefit)) < 0.005
          # And the row says what it is. A cancelled row still labelled Accrued is what a
          # claim would later pay out against.
          and reversed_rows == accrued,
          f"{accrued} ledger row(s) accrued worth {benefit:g}, {left_standing} still standing, "
          f"{reversed_rows} marked Reversed · consumed {consumed_before:g} -> "
          f"{consumed_after:g} (expected {consumed_before - benefit:g}) · order is docstatus "
          f"{state.docstatus} ({state.order_status}) · sales_order {state.sales_order}")


# --------------------------------------------------------------------------------------


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    print(f"\nGate 4 on {SITE}\n" + "-" * 72)
    try:
        criterion_1()
        fx = build_fixtures()
        criterion_2(fx)
        criterion_3(fx)
        scheme = criterion_4(fx)
        criterion_6(fx, scheme)
        criterion_5(fx)
    finally:
        frappe.db.rollback()
        try:
            purge("G4")
        except Exception as e:
            print(f"  !! could not clean up: {e} - run scripts/clean_gate_fixtures.py")
        frappe.destroy()

    print("-" * 72)
    passed = sum(1 for *_, ok, _d in results if ok)
    skipped = sum(1 for *_, ok, _d in results if ok is None)
    total = len(results) - skipped
    print(f"Gate 4: {passed}/{total} criteria passed"
          + (f", {skipped} not answerable on this bench" if skipped else "") + "\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
