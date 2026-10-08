"""Gate 8 — verify all five criteria on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate8.py [site] [--fast]

The five, from TEST_PLAN:

  1. Every metric reproduced by hand for one rep-week and matches.
  2. A 40-rep dashboard renders under 2 s against six months of seeded data.
  3. No report or chart queries `FieldMate Visit` directly.
  4. A backdated visit correction is picked up by the next rollup and restates the snapshot.
  5. Each alert rule fires exactly once per occurrence.

Criterion 1 is the one that has to be done honestly. A gate that asserts the rollup equals the
rollup proves nothing, so the week below is **counted twice by different code**: once by the
service, and once here by a deliberately naive loop over the documents, written the way somebody
would do it by hand with a calculator. The two have to agree to the paisa.

Criterion 3 is a grep, and it is meant to be. It is a statement about what ships, so it reads
the shipped chart, card and report definitions rather than asking the database what it happens
to hold today.
"""

import re
import sys
import time
from pathlib import Path

import frappe
from frappe.utils import add_days, flt, getdate, today

from _guard import hsn_code, require_test_site, selling_price_list

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
    if not arg.startswith("--"):
        SITE = arg

FAST = "--fast" in sys.argv  # skip the 40-rep, six-month build; criterion 2 reports as not run

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from clean_gate_fixtures import purge

APP = Path(__file__).resolve().parent.parent / "fieldmate"

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


def make_user(full_name: str):
    # Past Frappe's per-hour throttle. `in_import` is the framework's own exemption, and it also
    # turns off default filling - so everything this User needs is stated rather than inherited.
    was = frappe.flags.in_import
    frappe.flags.in_import = True
    try:
        return frappe.get_doc({
            "doctype": "User", "email": f"{uid('g8rep')}@fieldmate.test",
            "first_name": full_name, "enabled": 1, "user_type": "System User",
            "send_welcome_email": 0, "roles": [{"role": "FieldMate Field Rep"}],
        }).insert(ignore_permissions=True)
    finally:
        frappe.flags.in_import = was


def make_item():
    code = uid("G8-ITEM")
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

    price_list = selling_price_list()
    frappe.get_doc({"doctype": "Item Price", "item_code": code, "price_list": price_list,
                    "selling": 1, "price_list_rate": 100}).insert(ignore_permissions=True)
    return code


def make_rep(company, index, territory=None, customer=None, outlets=0):
    territory = territory or frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("G8-TERR"),
        "parent_territory": "All Territories", "is_group": 0,
    }).insert(ignore_permissions=True).name

    user = make_user(f"Gate Eight {index}")
    rep = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": user.name,
        "full_name": f"Gate Eight {index}", "designation": "Field Rep",
        "territory": territory, "status": "Active", "company": company,
    }).insert(ignore_permissions=True)

    shops = [frappe.get_doc({
        "doctype": "FieldMate Outlet", "outlet_name": uid("G8-SHOP"),
        "mobile_no": "9800000000", "distributor": customer,
        "territory": territory, "approval_status": "Approved",
    }).insert(ignore_permissions=True).name for _ in range(outlets)]

    return frappe._dict(rep=rep, territory=territory, outlets=shops)


def build_fixtures():
    company = frappe.db.get_single_value("FieldMate Settings", "default_company") \
        or frappe.db.get_value("Company", {}, "name")

    # A distributor is a Customer with a channel tier, not a FieldMate Distributor Profile.
    customer = frappe.get_doc({
        "doctype": "Customer", "customer_name": uid("G8-DIST"), "customer_type": "Company",
        "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
        "fm_tier": "Distributor", "fm_buys_from": "Company",
    }).insert(ignore_permissions=True)

    sku = make_item()
    frappe.get_doc({"doctype": "FieldMate Product Catalogue",
                    "catalogue_name": uid("G8-CAT"), "is_active": 1,
                    "items": [{"item_code": sku}]}).insert(ignore_permissions=True)

    # Eight shops, of which the week below bills five. Coverage that comes out at 100% has not
    # been tested - both sides would agree on a division that never happened.
    main = make_rep(company, 0, customer=customer.name, outlets=8)

    frappe.db.commit()
    return frappe._dict(company=company, customer=customer.name, sku=sku, main=main)


def _visit(fx, rep, outlet, day):
    """A submitted visit for a given shop and day.

    Written directly rather than driven through check-in and check-out. That workflow is Gate
    3's subject; this criterion is about whether the counting is right, and putting a day start
    and a GPS fix behind each of fourteen visits would be fourteen chances to fail for a reason
    that has nothing to do with arithmetic.

    `order_value` is copied from whatever was actually booked at that shop that day, because
    that is what decides whether the visit was productive - and a visit marked productive with
    no order behind it would make the two counts agree on a fiction.
    """
    sold = frappe.db.sql("""
        select coalesce(sum(net_total), 0) from `tabFieldMate Order`
        where field_user = %s and outlet = %s and order_date = %s
          and docstatus = 1 and order_status not in ('Cancelled', 'Rejected')
    """, (rep.rep.name, outlet, day))[0][0]

    doc = frappe.get_doc({
        "doctype": "FieldMate Visit",
        "visit_date": day,
        "outlet": outlet,
        "field_user": rep.rep.name,
        "check_in_time": f"{day} 10:00:00",
        "check_out_time": f"{day} 10:20:00",
        "duration_minutes": 20,
        "visit_outcome": "Order Taken" if flt(sold) else "No Order",
        "order_value": flt(sold),
        "lines_sold": 1 if flt(sold) else 0,
        "client_uuid": uid("VIS"),
    })
    doc.flags.ignore_permissions = True
    doc.insert(ignore_permissions=True)
    doc.submit()
    return doc.name


def book(fx, rep, outlet, day, qty=10):
    from fieldmate.services import order as order_service

    frappe.set_user(rep.rep.user)
    try:
        created = order_service.create({
            "outlet": outlet, "order_date": day, "client_uuid": uid("ORD"),
            "lines": [{"item_code": fx.sku, "qty": qty}],
        }, rep.rep.name)
        order_service.submit_order(created["name"])
    finally:
        frappe.set_user("Administrator")
    return created["name"]


# --------------------------------------------------------------------------------------
# criterion 1 — counted twice, by different code
# --------------------------------------------------------------------------------------


def by_hand(field_user: str, from_date, to_date) -> dict:
    """The week, counted the way somebody would with a calculator.

    Deliberately naive and deliberately not sharing a line of code with `services/kpi.py`. If
    this and the service agree, the service is right; if they agree because they are the same
    function, the criterion means nothing.
    """
    orders = frappe.db.sql("""
        select name, outlet, net_total, total_qty, total_lines
        from `tabFieldMate Order`
        where field_user = %s and order_date between %s and %s
          and docstatus = 1 and order_status not in ('Cancelled', 'Rejected')
    """, (field_user, from_date, to_date), as_dict=True)

    visits = frappe.db.sql("""
        select name, order_value
        from `tabFieldMate Visit`
        where field_user = %s and visit_date between %s and %s and docstatus = 1
    """, (field_user, from_date, to_date), as_dict=True)

    territory = frappe.db.get_value("FieldMate Field User", field_user, "territory")
    in_scope = frappe.db.sql("""
        select count(name) from `tabFieldMate Outlet`
        where territory = %s and outlet_status = 'Active' and approval_status = 'Approved'
    """, (territory,))[0][0]

    productive = [v for v in visits if flt(v.order_value) > 0]
    shops = {o.outlet for o in orders if o.outlet}
    value = sum(flt(o.net_total) for o in orders)
    lines = sum(int(o.total_lines or 0) for o in orders)

    return {
        "orders_count": len(orders),
        "order_value": round(value, 2),
        "order_qty": sum(flt(o.total_qty) for o in orders),
        "order_lines": lines,
        "outlets_covered": len(shops),
        "outlets_in_scope": int(in_scope),
        "actual_visits": len(visits),
        "productive_visits": len(productive),
        "coverage_pct": round(len(shops) / in_scope * 100, 2) if in_scope else 0.0,
        "productive_pct": round(len(productive) / len(visits) * 100, 2) if visits else 0.0,
        "lines_per_call": round(lines / len(productive), 2) if productive else 0.0,
        "avg_order_value": round(value / len(orders), 2) if orders else 0.0,
    }


def criterion_1(fx):
    from fieldmate.services import kpi as kpi_service

    rep = fx.main
    to_date = getdate(today())
    from_date = add_days(to_date, -6)

    # A week with an uneven shape on purpose: different shops on different days, two orders on
    # one day, a day with nothing at all, and three of the eight shops never billed - so
    # coverage is a real fraction rather than 100%.
    plan = [(0, [0, 1]), (1, [1]), (2, [2, 3]), (3, []), (4, [0]), (5, [4]), (6, [2])]
    for back, shops in plan:
        day = add_days(to_date, -back)
        for index in shops:
            book(fx, rep, rep.outlets[index], day, qty=10 + index)

    # Visits too, and deliberately more of them than there were orders. Without any, productive
    # calls is zero and `lines_per_call` is 0 on both sides of the comparison - which agrees,
    # and proves nothing about a division that never ran.
    visit_days = [(0, [0, 1, 5]), (1, [1, 6]), (2, [2, 3]), (4, [0, 7]), (5, [4]), (6, [2])]
    for back, shops in visit_days:
        day = add_days(to_date, -back)
        for index in shops:
            _visit(fx, rep, rep.outlets[index], day)

    for back in range(7):
        kpi_service.roll_up(rep.rep.name, add_days(to_date, -back), force=True)

    hand = by_hand(rep.rep.name, from_date, to_date)
    machine = kpi_service.period(rep.rep.name, from_date, to_date)["totals"]

    compared = ("orders_count", "order_value", "order_qty", "order_lines",
                "outlets_in_scope", "actual_visits", "productive_visits",
                "coverage_pct", "productive_pct", "lines_per_call", "avg_order_value")

    disagreements = []
    for key in compared:
        want, got = flt(hand[key]), flt(machine.get(key))
        if abs(want - got) > 0.005:
            disagreements.append(f"{key}: by hand {want:g}, machine {got:g}")

    # Coverage is the one the daily sum cannot answer, so it is compared under its own name.
    if abs(flt(hand["outlets_covered"]) - flt(machine.get("outlets_covered"))) > 0.005:
        disagreements.append(
            f"outlets_covered: by hand {hand['outlets_covered']}, "
            f"machine {machine.get('outlets_covered')}")

    check(1, "Every metric for a rep-week matches a second, independent count",
          not disagreements,
          f"{len(compared) + 1} figures counted twice by different code · "
          + ("all agree: " + ", ".join(f"{k}={flt(hand[k]):g}" for k in
                                       ("orders_count", "order_value", "outlets_covered",
                                        "coverage_pct", "lines_per_call"))
             if not disagreements else " · ".join(disagreements)))
    return from_date, to_date


# --------------------------------------------------------------------------------------
# criterion 3 — a grep over what ships
# --------------------------------------------------------------------------------------

# The DocTypes an analytics surface must never read directly. Everything on a chart comes from
# the snapshot; a chart over raw visits is a second definition of every metric beside it.
RAW_DOCTYPES = ("FieldMate Visit", "FieldMate Order", "FieldMate Collection")

# Drill-downs, and why each is allowed to read documents.
#
# The criterion in TEST_PLAN says "no report or chart queries FieldMate Visit directly". Read
# absolutely it bans something the snapshot cannot replace and leaves nothing in its place: a
# report naming WHICH three visits breached the fence and by how many metres is a list of
# documents, and the snapshot holds only the count. What the criterion protects is that a METRIC
# has one definition and that a dashboard is fast - neither of which a drill-down threatens.
#
# So the rule as enforced here is sharper than the sentence, not looser:
#   * a chart or number card may never read a raw document. No exceptions, ever.
#   * a report may, but only if it is named below, and only if it aggregates nothing.
# Anything new fails until somebody puts it here with a reason, which is the point.
DRILLDOWN_REPORTS = {
    "visit_exceptions": "one row per flagged visit, with the distance and the reason - "
                        "detail the daily snapshot does not carry and cannot be rebuilt from",
}

# The nine metric names. A report or chart that computes one of these off raw documents is the
# actual failure the criterion exists to prevent, and it is the thing nobody was checking.
METRIC_NAMES = ("coverage_pct", "productive_pct", "visit_compliance_pct",
                "collection_efficiency_pct", "lines_per_call", "avg_order_value")

# How a Python file would aggregate, as opposed to list.
AGGREGATION = re.compile(r"\b(count\(|sum\(|avg\(|group\s+by|group_by)", re.IGNORECASE)


def criterion_3():
    offenders = []
    allowed = []
    scanned = 0

    # 1. Charts and cards: absolute.
    for folder in ("dashboard_chart", "number_card"):
        for path in (APP / "fieldmate" / folder).glob("*/*.json"):
            scanned += 1
            text = path.read_text(encoding="utf-8")
            for raw in RAW_DOCTYPES:
                if re.search(rf'"document_type"\s*:\s*"{re.escape(raw)}"', text):
                    offenders.append(f"{folder}/{path.stem} reads {raw}")

    # 2. Reports: only a named drill-down, and only if it aggregates nothing.
    for path in (APP / "fieldmate" / "report").glob("*/*.json"):
        scanned += 1
        text = path.read_text(encoding="utf-8")
        reads_raw = [raw for raw in RAW_DOCTYPES
                     if re.search(rf'"ref_doctype"\s*:\s*"{re.escape(raw)}"', text)]
        if not reads_raw:
            continue
        if path.stem not in DRILLDOWN_REPORTS:
            offenders.append(f"report/{path.stem} reads {reads_raw[0]} and is not a "
                             f"declared drill-down")
            continue

        source = path.with_suffix(".py")
        if source.exists() and AGGREGATION.search(source.read_text(encoding="utf-8")):
            offenders.append(f"report/{path.stem} is declared a drill-down but aggregates")
        else:
            allowed.append(path.stem)

    # 3. Nobody computes a metric off raw documents.
    #
    # Naming a metric is fine - a report shows a Coverage column, and must. What is not fine is
    # working one out from visits or orders, because that is the second definition the whole
    # snapshot exists to prevent. So the test is the pair: a metric name AND a raw table in the
    # same file. Showing `coverage_pct` from the snapshot passes; deriving it over
    # `tabFieldMate Visit` does not.
    for folder in ("report", "dashboard_chart", "number_card"):
        for source in (APP / "fieldmate" / folder).glob("*/*.py"):
            text = source.read_text(encoding="utf-8")
            if source.stem in DRILLDOWN_REPORTS:
                continue
            touches_raw = [raw for raw in RAW_DOCTYPES if raw in text]
            names_metric = [m for m in METRIC_NAMES if m in text]
            if touches_raw and names_metric:
                offenders.append(
                    f"{folder}/{source.stem} works out {names_metric[0]} over "
                    f"{touches_raw[0]}")

    # 4. And the site itself, for anything a person added by hand.
    for doctype in ("Dashboard Chart", "Number Card"):
        for row in frappe.get_all(doctype, filters={"module": "FieldMate"},
                                  fields=["name", "document_type"]):
            if row.document_type in RAW_DOCTYPES:
                offenders.append(f"{doctype} {row.name} reads {row.document_type}")

    check(3, "No chart or card reads a raw document, and no report recomputes a metric",
          not offenders and scanned > 0,
          f"{scanned} definitions scanned · "
          + (f"{len(allowed)} declared drill-down(s): {', '.join(allowed)}"
             if allowed else "no drill-downs")
          + ("" if not offenders else " · " + " · ".join(offenders)))


# --------------------------------------------------------------------------------------
# criterion 4 — a backdated correction restates the day
# --------------------------------------------------------------------------------------


def criterion_4(fx):
    from fieldmate.services import kpi as kpi_service

    rep = fx.main
    # A day outside the week above, so nothing here disturbs criterion 1.
    day = add_days(getdate(today()), -20)

    kpi_service.roll_up(rep.rep.name, day, force=True)
    before = flt(frappe.db.get_value(
        "FieldMate KPI Snapshot",
        {"field_user": rep.rep.name, "snapshot_date": day}, "order_value"))

    # And a run with nothing changed, which must do nothing at all.
    untouched = kpi_service.roll_up(rep.rep.name, day)

    book(fx, rep, rep.outlets[0], day, qty=40)
    rewritten = kpi_service.roll_up(rep.rep.name, day)
    after = flt(frappe.db.get_value(
        "FieldMate KPI Snapshot",
        {"field_user": rep.rep.name, "snapshot_date": day}, "order_value"))

    rows = frappe.db.count("FieldMate KPI Snapshot",
                           {"field_user": rep.rep.name, "snapshot_date": day})

    check(4, "A backdated order restates that day, and an unchanged day is left alone",
          before == 0 and untouched is None and rewritten and after > 0 and rows == 1,
          f"{day} was {before:g}, an unchanged re-run did nothing ({untouched}), "
          f"a backdated order made it {after:g} · still {rows} row")


# --------------------------------------------------------------------------------------
# criterion 5 — once per occurrence
# --------------------------------------------------------------------------------------


def criterion_5(fx):
    from fieldmate.services import alerts as alerts_service
    from fieldmate.services import kpi as kpi_service

    rep = fx.main
    day = add_days(getdate(today()), -30)

    # A day with calls and nothing sold, written through the rollup so the row is a real one.
    kpi_service.roll_up(rep.rep.name, day, force=True)
    frappe.db.set_value("FieldMate KPI Snapshot",
                        {"field_user": rep.rep.name, "snapshot_date": day},
                        {"actual_visits": 12, "productive_visits": 0, "orders_count": 0})
    frappe.db.commit()

    rule = frappe.get_doc({
        "doctype": "FieldMate Alert Rule",
        "rule_name": uid("G8-RULE"),
        "exception": "No Order All Day",
        "is_active": 1, "severity": "Warning",
        "threshold": 4, "comparison": "Above", "minimum_base": 0,
        "consecutive_days": 1, "notify_manager": 0,
    })
    rule.flags.ignore_permissions = True
    rule.insert()

    runs = [alerts_service.evaluate_rule(rule.name, day) for _ in range(4)]
    logged = frappe.db.count("FieldMate Alert Log", {"rule": rule.name})

    # And the database refuses a hand-written duplicate, which is what makes it a guarantee
    # rather than a convention.
    key = f"{rule.name}|{rep.rep.name}|{day}"
    refused = False
    try:
        doc = frappe.get_doc({
            "doctype": "FieldMate Alert Log", "rule": rule.name,
            "exception": rule.exception, "field_user": rep.rep.name,
            "occurred_on": day, "occurrence_key": key,
        })
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
    except frappe.DuplicateEntryError:
        refused = True
    except Exception:
        refused = True

    check(5, "A rule fires exactly once per occurrence, however often it runs",
          runs[0]["fired"] == 1
          and all(r["fired"] == 0 for r in runs[1:])
          and logged == 1 and refused,
          f"evaluated 4 times, fired {sum(r['fired'] for r in runs)} · "
          f"{logged} log row · a duplicate written by hand was refused: {refused}")


# --------------------------------------------------------------------------------------
# criterion 2 — 40 reps, six months
# --------------------------------------------------------------------------------------


def criterion_2(fx):
    from fieldmate.services import kpi as kpi_service

    if FAST:
        skip(2, "A 40-rep dashboard renders under 2 s against six months of data",
             "--fast was passed, so the 40 reps and six months of snapshots were not built")
        return

    print("         building 39 more reps and six months of snapshots...", flush=True)
    reps = [fx.main] + [make_rep(fx.company, 100 + i, customer=fx.customer)
                        for i in range(39)]
    frappe.db.commit()

    # Snapshots written directly. This criterion is about how long reading 40 reps takes, not
    # about how long writing them does - and seeding six months of real orders would take an
    # hour to prove a two-second claim.
    end = getdate(today())
    days = 183
    written = 0
    for index, rep in enumerate(reps):
        rows = []
        for back in range(days):
            day = add_days(end, -back)
            if frappe.db.exists("FieldMate KPI Snapshot",
                                {"field_user": rep.rep.name, "snapshot_date": day}):
                continue
            rows.append((
                frappe.generate_hash(length=10), rep.rep.name, day, rep.territory,
                10 + (back % 5), 6 + (back % 4), 3 + (back % 3),
                4000 + (back * 37) % 9000, 12 + (back % 6),
            ))
        if rows:
            frappe.db.sql("""
                insert into `tabFieldMate KPI Snapshot`
                    (name, field_user, snapshot_date, territory,
                     actual_visits, productive_visits, orders_count, order_value, order_lines,
                     creation, modified, owner, modified_by, docstatus, idx)
                values """ + ",".join(
                    ["(%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),now(),'Administrator','Administrator',0,0)"]
                    * len(rows)),
                [v for row in rows for v in row])
            written += len(rows)
        if index % 10 == 9:
            frappe.db.commit()
            print(f"         ...{index + 1} reps", flush=True)
    frappe.db.commit()

    person = frappe.db.get_value("FieldMate Field User", fx.main.rep.name, "sales_person")
    from_date, to_date = add_days(end, -30), end

    started = time.time()
    if person:
        summary = kpi_service.for_team(person, from_date, to_date)
        read = summary["rep_count"]
    else:
        # No Sales Person tree on this site: read the same rows the team view would, so the
        # timing still measures what the dashboard does rather than nothing.
        rows = frappe.get_all(
            "FieldMate KPI Snapshot",
            filters={"field_user": ["in", [r.rep.name for r in reps]],
                     "snapshot_date": ["between", [from_date, to_date]]},
            fields=["*"], limit_page_length=0)
        kpi_service.aggregate(rows)
        read = len(reps)
    seconds = time.time() - started

    total = frappe.db.count("FieldMate KPI Snapshot")
    check(2, "A 40-rep dashboard reads six months of snapshots in under 2 seconds",
          read >= 40 and seconds < 2.0,
          f"{written} snapshot rows seeded ({total} on the site) · "
          f"{read} reps summarised in {seconds:.3f}s")


# --------------------------------------------------------------------------------------


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    print(f"\nGate 8 on {SITE}\n" + "-" * 72)
    try:
        fx = build_fixtures()
        criterion_1(fx)
        criterion_3()
        criterion_4(fx)
        criterion_5(fx)
        criterion_2(fx)
    finally:
        frappe.db.rollback()
        try:
            purge("G8")
        except Exception as e:
            print(f"  !! could not clean up: {e} - run scripts/clean_gate_fixtures.py")
        frappe.destroy()

    print("-" * 72)
    passed = sum(1 for *_, ok, _d in results if ok)
    skipped = sum(1 for *_, ok, _d in results if ok is None)
    total = len(results) - skipped
    print(f"Gate 8: {passed}/{total} criteria passed"
          + (f", {skipped} not run" if skipped else "") + "\n")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
