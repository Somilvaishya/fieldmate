"""Gate 7 — verify all five criteria on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate7.py [site]

The five, from TEST_PLAN:

  1. A national target cascades to 20 reps; the leaves sum to the root for every target type.
  2. All six achievement types are correct against a seeded month.
  3. An incentive payout for 3 reps matches a hand-built spreadsheet to the rupee.
  4. Claim distance matches Location Trail; a rep cannot edit upward without approval.
  5. The nightly job for 250 reps finishes under 10 minutes.

Criterion 1 needs reading carefully, and the reading is recorded here rather than left implicit.
**Five of the six target types are quantities and are split; the sixth is a rate and is copied.**
A root asking for 4.5 lines per call means every rep is asked for 4.5, not for 4.5 between them -
a cascade that divided it would hand each of twenty reps a target of 0.225 lines. So the leaves
sum to the root for every ADDITIVE type, and equal the root for the ratio type, and the gate
checks both rather than pretending one rule covers six.

Criterion 5 builds 250 leaf plans for real. That is slow to set up and it is the point: a job
timed against three reps has been timed against nothing.
"""

import sys
import time

import frappe
from frappe.utils import add_days, flt, today

from _guard import require_test_site

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
    # A positional argument is the site; a flag is a flag. Reading argv[1] blindly made
    # `gate7.py --fast` try to open a site called "--fast".
    if not arg.startswith("--"):
        SITE = arg

FAST = "--fast" in sys.argv  # skip the 250-rep build; criterion 5 then reports as not run

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from clean_gate_fixtures import purge

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

# The same six the app measures, and the target each carries at national level. Chosen so that
# none of them divides evenly by 20 - a cascade that only works on round numbers works on nothing.
NATIONAL = [
    ("Value", 1_00_00_000),        # a crore, which is 5,00,000 each with nothing left over...
    ("Volume", 50_001),            # ...so the rest are deliberately awkward
    ("Outlet Coverage", 5_617),
    ("Productive Calls", 4_213),
    ("New Outlets", 207),
    ("Lines Per Call", 4.5),       # a rate. Copied, never divided.
]

ADDITIVE = [t for t, _ in NATIONAL if t != "Lines Per Call"]


def make_sales_person(label, parent=None, is_group=1):
    doc = frappe.get_doc({
        "doctype": "Sales Person",
        "sales_person_name": uid(f"G7-{label}"),
        "parent_sales_person": parent,
        "is_group": is_group,
        "enabled": 1,
    }).insert(ignore_permissions=True)
    return doc.name


def make_item():
    code = uid("G7-ITEM")
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
    frappe.get_doc(data).insert(ignore_permissions=True)

    price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
    frappe.get_doc({
        "doctype": "Item Price", "item_code": code, "price_list": price_list,
        "selling": 1, "price_list_rate": 100,
    }).insert(ignore_permissions=True)
    return code


def make_user(full_name: str):
    """One login, past Frappe's per-hour throttle.

    `User.before_insert` refuses more than ~60 new logins an hour, which is a sensible rule for a
    live site and an absolute wall for criterion 5, which needs 250. `frappe.flags.in_import` is
    the framework's own exemption and is exactly what it is for.

    It is set around this insert and nowhere else. The flag also turns off default-value filling
    for whatever it covers, so everything this User needs is stated here rather than inherited -
    a fixture quietly created with `enabled` unset would make criterion 5 measure 250 plans
    belonging to 250 disabled reps.
    """
    was = frappe.flags.in_import
    frappe.flags.in_import = True
    try:
        return frappe.get_doc({
            "doctype": "User",
            "email": f"{uid('g7rep')}@fieldmate.test",
            "first_name": full_name,
            "enabled": 1,
            "user_type": "System User",
            "send_welcome_email": 0,
            "roles": [{"role": "FieldMate Field Rep"}],
        }).insert(ignore_permissions=True)
    finally:
        frappe.flags.in_import = was


def make_rep(sales_person, company, index, outlets=0, customer=None, territory=None):
    territory = territory or frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("G7-TERR"),
        "parent_territory": "All Territories", "is_group": 0,
    }).insert(ignore_permissions=True).name

    user = make_user(f"Gate Seven {index}")

    rep = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": user.name,
        "full_name": f"Gate Seven {index}", "designation": "Field Rep",
        "territory": territory, "status": "Active", "company": company,
        "sales_person": sales_person,
    }).insert(ignore_permissions=True)

    shops = []
    for _ in range(outlets):
        shops.append(frappe.get_doc({
            "doctype": "FieldMate Outlet", "outlet_name": uid("G7-SHOP"),
            "mobile_no": "9800000000", "distributor": customer,
            "territory": territory, "approval_status": "Approved",
        }).insert(ignore_permissions=True).name)

    return frappe._dict(person=sales_person, rep=rep, territory=territory, outlets=shops)


def plan(sales_person, company, lines, basis="Outlet Count", days=29):
    doc = frappe.get_doc({
        "doctype": "FieldMate Target Plan",
        "plan_name": uid("G7-PLAN"),
        "company": company,
        "from_date": add_days(today(), -1),
        "to_date": add_days(today(), days),
        "sales_person": sales_person,
        "cascade_basis": basis,
        "lines": [{"target_type": t, "target_value": v} for t, v in lines],
    })
    doc.flags.ignore_permissions = True
    doc.insert()
    doc.submit()
    return doc


def build_fixtures():
    """A national node, four regions, twenty reps, a priced SKU and a distributor."""
    company = frappe.db.get_single_value("FieldMate Settings", "default_company") \
        or frappe.db.get_value("Company", {}, "name")

    # A distributor is a Customer with a channel tier, not a FieldMate Distributor Profile.
    customer = frappe.get_doc({
        "doctype": "Customer", "customer_name": uid("G7-DIST"), "customer_type": "Company",
        "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
        "fm_tier": "Distributor", "fm_buys_from": "Company",
    }).insert(ignore_permissions=True)

    national = make_sales_person("NAT")
    regions = [make_sales_person("REG", parent=national) for _ in range(4)]

    reps = []
    for index in range(20):
        region = regions[index % 4]
        person = make_sales_person("REP", parent=region, is_group=0)
        # Uneven shop counts on purpose: outlet count is the default weight, and a split that
        # only works on equal weights works on no real site. Two at minimum, so criterion 2 can
        # book at two shops and see a coverage figure that is not trivially 1.
        reps.append(make_rep(person, company, index, outlets=(index % 5) + 2,
                             customer=customer.name))

    sku = make_item()
    frappe.get_doc({
        "doctype": "FieldMate Product Catalogue", "catalogue_name": uid("G7-CAT"),
        "is_active": 1, "items": [{"item_code": sku}],
    }).insert(ignore_permissions=True)

    frappe.db.commit()
    return frappe._dict(company=company, national=national, regions=regions, reps=reps,
                        sku=sku, customer=customer.name)


# --------------------------------------------------------------------------------------
# criteria
# --------------------------------------------------------------------------------------


def criterion_1(fx):
    """A national target reaches 20 reps, and the leaves add back up to the root."""
    from fieldmate.services import target as target_service

    root = plan(fx.national, fx.company, NATIONAL)
    target_service.cascade(root.name)
    report = target_service.reconcile(root.name)

    additive_ok = all(report["types"][t]["matches"] for t in ADDITIVE)
    ratio = report["types"]["Lines Per Call"]
    # A rate is carried down unchanged, so every leaf holds the root's own number. Summing it
    # would be the bug, not the check.
    ratio_ok = ratio["matches"] and ratio["leaves"] == [4.5]

    detail = " · ".join(
        f"{t}: root {report['types'][t]['root']:g} = leaves {report['types'][t]['leaves']:g}"
        for t in ADDITIVE)

    check(1, "A national target cascades to 20 reps and the leaves sum to the root",
          report["leaf_count"] == 20 and additive_ok and ratio_ok,
          f"{report['leaf_count']} leaves · {detail} · "
          f"Lines Per Call copied to every leaf as {ratio['leaves']}")
    return root


def criterion_2(fx, root):
    """All six achievement types, against a month somebody can count by hand."""
    from fieldmate.services import order as order_service
    from fieldmate.services import target as target_service

    rep = fx.reps[0]
    leaf = frappe.db.get_value("FieldMate Target Plan",
                               {"field_user": rep.rep.name, "docstatus": 1}, "name")
    if not leaf:
        check(2, "All six achievement types are correct", False,
              "the cascade produced no plan for the first rep")
        return

    # Two orders at two different shops, so coverage is 2 and not 1.
    frappe.set_user(rep.rep.user)
    booked = []
    try:
        for shop in rep.outlets[:2]:
            created = order_service.create({
                "outlet": shop, "client_uuid": uid("ORD"),
                "lines": [{"item_code": fx.sku, "qty": 10}],
            }, rep.rep.name)
            order_service.submit_order(created["name"])
            booked.append(created["name"])
    finally:
        frappe.set_user("Administrator")

    # Counted by hand from the documents, the way a manager would.
    by_hand = {
        "Value": sum(flt(frappe.db.get_value("FieldMate Order", n, "net_total"))
                     for n in booked),
        "Volume": sum(flt(frappe.db.get_value("FieldMate Order", n, "total_qty"))
                      for n in booked),
        "Outlet Coverage": len({frappe.db.get_value("FieldMate Order", n, "outlet")
                                for n in booked}),
    }

    target_service.compute(leaf)
    doc = frappe.get_doc("FieldMate Achievement", {"target_plan": leaf})
    measured = {row.target_type: flt(row.actual_value) for row in doc.lines}

    agree = all(abs(measured.get(k, 0) - v) < 0.005 for k, v in by_hand.items())
    all_six = len(doc.lines) == 6

    check(2, "All six achievement types are measured, and the three countable ones agree",
          all_six and agree,
          f"{len(doc.lines)} types measured · by hand: "
          + ", ".join(f"{k} {v:g}" for k, v in by_hand.items())
          + " · measured: "
          + ", ".join(f"{k} {measured.get(k, 0):g}" for k in by_hand))
    return leaf


def criterion_3(fx, leaf):
    """Three reps against a table worked out on paper first.

        rep A   64% of target  -> below the 80% qualifying line   ->      0
        rep B   95% of target  -> Tier 1, flat                    ->  4,200
        rep C  131% of target  -> Tier 3, flat                    ->  9,000
    """
    from fieldmate.services import incentive as incentive_service

    scheme = frappe.get_doc({
        "doctype": "FieldMate Incentive Scheme",
        "scheme_name": uid("G7-INC"),
        "company": fx.company,
        "is_active": 1,
        "valid_from": add_days(today(), -30),
        "measured_on": "Value",
        "qualifying_pct": 80,
        "slabs": [
            {"slab_idx": 1, "from_pct": 80, "to_pct": 100, "payout_kind": "Fixed Amount",
             "payout_amount": 4200, "label": "Tier 1"},
            {"slab_idx": 2, "from_pct": 100, "to_pct": 120, "payout_kind": "Fixed Amount",
             "payout_amount": 6000, "label": "Tier 2"},
            {"slab_idx": 3, "from_pct": 120, "is_open_ended": 1, "payout_kind": "Fixed Amount",
             "payout_amount": 9000, "label": "Tier 3"},
        ],
    })
    scheme.flags.ignore_permissions = True
    scheme.insert()
    scheme.submit()

    spreadsheet = [(64, 6_40_000, 0), (95, 9_50_000, 4200), (131, 13_10_000, 9000)]
    mismatches = []
    for pct, actual, expected in spreadsheet:
        got = incentive_service.in_rupees(
            incentive_service.award(scheme, pct, actual)["payout_paise"])
        if got != expected:
            mismatches.append(f"{pct}%: expected {expected}, got {got}")

    # And one that actually writes a document, so the path the month-end run takes is exercised
    # rather than only the arithmetic underneath it.
    rep = fx.reps[0]
    payouts = incentive_service.compute_for(rep.rep.name, leaf) if leaf else []
    wrote = [p for p in payouts if p.get("payout")]

    check(3, "Incentive payouts for 3 reps match a hand-built table to the rupee",
          not mismatches and bool(wrote),
          ("all three match: " + ", ".join(f"{p}%={e}" for p, _a, e in spreadsheet)
           if not mismatches else " · ".join(mismatches))
          + f" · wrote {len(wrote)} payout document(s)")


def criterion_4(fx):
    """Distance matches the trail, and a rep cannot edit upward without approval."""
    from fieldmate.services import expense as expense_service
    from fieldmate.services import trail as trail_service

    settings = frappe.get_single("FieldMate Settings")
    before = {k: settings.get(k) for k in
              ("travel_rate_per_km", "expense_distance_tolerance_pct")}
    settings.travel_rate_per_km = 3.5
    settings.expense_distance_tolerance_pct = 10
    settings.flags.ignore_permissions = True
    settings.save(ignore_permissions=True)
    frappe.cache().delete_value("fieldmate_settings")

    rep = fx.reps[1]
    # Two pings about 100 km apart - a degree of latitude is roughly 111 km. The keys are the
    # short ones a device sends (`lat`, `lon`, `t`), and `trail_date` is passed because append
    # otherwise files the batch under today whatever the timestamps say.
    trail_service.append(rep.rep.name, [
        {"lat": 28.60, "lon": 77.20, "t": f"{today()} 09:00:00"},
        {"lat": 28.60 + 100 / 111.0, "lon": 77.20, "t": f"{today()} 18:00:00"},
    ], trail_date=today())
    recorded = flt(trail_service.distance_for(rep.rep.name, today()), 2)

    frappe.set_user(rep.rep.user)
    try:
        honest = expense_service.create({
            "claim_date": today(), "expense_type": "Travel", "client_uuid": uid("EXP"),
        }, rep.rep.name)
        expense_service.submit_claim(honest["name"], rep.rep.name)
    finally:
        frappe.set_user("Administrator")

    # The same rep, the day before, claiming half as much again as the trail holds.
    yesterday = add_days(today(), -1)
    trail_service.append(rep.rep.name, [
        {"lat": 28.60, "lon": 77.20, "t": f"{yesterday} 09:00:00"},
        {"lat": 28.60 + 100 / 111.0, "lon": 77.20, "t": f"{yesterday} 18:00:00"},
    ], trail_date=yesterday)
    frappe.set_user(rep.rep.user)
    try:
        inflated = expense_service.create({
            "claim_date": yesterday, "expense_type": "Travel",
            "claimed_distance_km": round(recorded * 1.5, 2), "client_uuid": uid("EXP"),
            # 150 km at 3.50 is over the receipt threshold, and this criterion is about the
            # distance rule rather than the receipt rule. A rep claiming that much does attach
            # a bill; raising the threshold instead would quietly stop testing it.
            "receipt": "/files/gate7-receipt.jpg",
        }, rep.rep.name)
        expense_service.submit_claim(inflated["name"], rep.rep.name)

        # And they cannot sign it off themselves.
        self_approved = False
        try:
            expense_service.approve(inflated["name"], "Approved")
            self_approved = True
        except frappe.PermissionError:
            pass
    finally:
        frappe.set_user("Administrator")

    matches_trail = abs(flt(honest["trail_distance_km"]) - recorded) < 0.02
    honest_status = frappe.db.get_value("FieldMate Expense Claim", honest["name"], "claim_status")
    inflated_status = frappe.db.get_value("FieldMate Expense Claim", inflated["name"],
                                          "claim_status")

    check(4, "Claim distance matches the trail, and a rep cannot edit it upward unchecked",
          matches_trail
          and honest_status == "Approved"
          and inflated_status == "Pending Approval"
          and not self_approved,
          f"trail recorded {recorded:g} km · an honest claim read {flt(honest['trail_distance_km']):g} km "
          f"and went straight to {honest_status} · a claim of "
          f"{flt(inflated['claimed_distance_km']):g} km is {inflated_status} · "
          f"rep could approve it themselves: {self_approved}")

    for key, value in before.items():
        frappe.db.set_single_value("FieldMate Settings", key, value)
    frappe.cache().delete_value("fieldmate_settings")


def criterion_5(fx):
    """250 reps, measured, timed."""
    from fieldmate.services import target as target_service

    if FAST:
        skip(5, "The nightly job for 250 reps finishes under 10 minutes",
             "--fast was passed, so the 230 extra reps were not built")
        return

    print("         building 230 more reps...", flush=True)
    region = fx.regions[0]
    extra = []
    for index in range(230):
        person = make_sales_person("BULK", parent=region, is_group=0)
        extra.append(make_rep(person, fx.company, 1000 + index, outlets=0,
                              customer=fx.customer))
        if index % 50 == 49:
            frappe.db.commit()
            print(f"         ...{index + 1}", flush=True)
    frappe.db.commit()

    # One leaf plan each, built directly rather than cascaded: this criterion is about how long
    # measuring 250 plans takes, not about the cascade, which criterion 1 already covered.
    print("         building 230 plans...", flush=True)
    for one in extra:
        plan(one.person, fx.company, [("Value", 100000), ("Productive Calls", 40)])
    frappe.db.commit()

    total = frappe.db.count("FieldMate Target Plan",
                            {"docstatus": 1, "field_user": ["is", "set"]})
    print(f"         measuring {total} leaf plans...", flush=True)

    started = time.time()
    outcome = target_service.compute_all()
    seconds = time.time() - started

    check(5, "The nightly job finishes 250 reps under 10 minutes",
          total >= 250 and seconds < 600 and not outcome["failed"],
          f"{outcome['computed']} of {outcome['plans']} plans measured in {seconds:.1f}s "
          f"({seconds / max(outcome['computed'], 1):.2f}s each)"
          + (f" · {len(outcome['failed'])} failed" if outcome["failed"] else ""))


# --------------------------------------------------------------------------------------


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    print(f"\nGate 7 on {SITE}\n" + "-" * 72)
    try:
        fx = build_fixtures()
        root = criterion_1(fx)
        leaf = criterion_2(fx, root)
        criterion_3(fx, leaf)
        criterion_4(fx)
        criterion_5(fx)
    finally:
        frappe.db.rollback()
        try:
            purge("G7")
        except Exception as e:
            print(f"  !! could not clean up: {e} - run scripts/clean_gate_fixtures.py")
        frappe.destroy()

    print("-" * 72)
    passed = sum(1 for *_, ok, _d in results if ok)
    skipped = sum(1 for *_, ok, _d in results if ok is None)
    total = len(results) - skipped
    print(f"Gate 7: {passed}/{total} criteria passed"
          + (f", {skipped} not run" if skipped else "") + "\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
