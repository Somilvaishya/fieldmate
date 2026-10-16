"""Gate 2 — verify all five criteria on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate2.py [site]

Written late. Phases 3 through 6 each got their gate as they shipped and Phase 2 did not, so its
five criteria had never been checked against a real database — only through unit tests, which is
not the same thing and is exactly the gap a gate exists to close.

Everything it creates is rolled back at the end, so it is safe to run against testerp2.

Two criteria cannot be fully proved from here, and the script says so rather than passing quietly:

  * Criterion 2 asks for **v15 and v16**. This bench is v15. The v15 half is proved; the v16 half
    is a CI matrix question and is reported as untested rather than assumed.
  * Criterion 5 is about killing the app, which is a client behaviour. What is proved here is the
    half the server owes: the day survives, stays open, and reads back identically.
"""

import sys

import frappe
from frappe.utils import add_days, add_to_date, flt, getdate, now_datetime, today

from _guard import require_test_site

SITE = sys.argv[1] if len(sys.argv) > 1 else "testerp2.web.gargsystems.com"

DELHI = (28.6139, 77.2090)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

# Run directly rather than imported, so `scripts` is not on the path until we put it there.
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from clean_gate_fixtures import purge

results = []


def check(number, name, passed, detail=""):
    # bool(), because `a and b.get(c)` yields None rather than False and None is how this script
    # marks "not testable" - a real failure would have been printed as FAIL and then counted as
    # a skip, which is the one bug a gate must not have.
    results.append((number, name, bool(passed), detail))
    print(f"  [{'PASS' if passed else 'FAIL'}] {number}. {name}")
    if detail:
        print(f"         {detail}")


def note(number, name, detail):
    """Something this bench genuinely cannot answer. Neither a pass nor a silent omission."""
    results.append((number, name, None, detail))
    print(f"  [SKIP] {number}. {name}")
    print(f"         {detail}")


def uid(prefix):
    return f"{prefix}-{frappe.generate_hash(length=8)}"


def make_user(name: str):
    """A rep's login.

    Frappe throttles new Users per hour and twenty in one run trips it, so `in_import` is set for
    exactly this call and put back. Left on for the whole script it also skips field defaults,
    which turns every fixture afterwards into a hunt for a mandatory field nobody meant to set.
    """
    was = frappe.flags.in_import
    frappe.flags.in_import = True
    try:
        return frappe.get_doc({
            "doctype": "User", "email": f"{uid('g2')}@fieldmate.test",
            "first_name": name, "send_welcome_email": 0, "enabled": 1,
            "roles": [{"role": "FieldMate Field Rep"}],
        }).insert(ignore_permissions=True)
    finally:
        frappe.flags.in_import = was


def build_fixtures(rep_count=20):
    """Twenty reps, a beat each, a holiday list and one approved leave day."""
    territory = frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("G2-TERR"),
        "parent_territory": "All Territories", "is_group": 0,
    }).insert(ignore_permissions=True)

    # A holiday list with Sundays plus one working-day holiday, so criterion 1 can tell the two
    # apart rather than crediting the Sunday rule for both.
    start, end = getdate(today()).replace(day=1), None
    end = add_days(add_to_date(start, months=1), -1)

    holidays = []
    cursor = start
    while cursor <= end:
        if cursor.weekday() == 6:
            holidays.append({"holiday_date": cursor, "description": "Sunday"})
        cursor = add_days(cursor, 1)

    festival = next(add_days(start, i) for i in range(28)
                    if add_days(start, i).weekday() not in (5, 6))
    holidays.append({"holiday_date": festival, "description": "Festival"})

    holiday_list = frappe.get_doc({
        "doctype": "Holiday List", "holiday_list_name": uid("G2-HOL"),
        "from_date": start, "to_date": end, "holidays": holidays,
    }).insert(ignore_permissions=True)

    # Every outlet needs one, and twenty reps sharing one keeps the fixture honest without
    # making twenty Customers nobody looks at.
    customer = frappe.get_doc({
        "doctype": "Customer", "customer_name": uid("G2-DIST"), "customer_type": "Company",
        "customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
    }).insert(ignore_permissions=True)

    reps = []
    for i in range(rep_count):
        user = make_user(f"Rep {i}")

        rep = frappe.get_doc({
            "doctype": "FieldMate Field User", "user": user.name, "full_name": f"Rep {i}",
            "designation": "Field Rep", "territory": territory.name, "status": "Active",
        }).insert(ignore_permissions=True)

        # Two beats each, chosen so the plan has something to skip: a beat that never fell on a
        # Sunday would let criterion 1 pass without the Sunday rule doing anything. Each gets
        # its own shop, because a shop belongs to one route and the Beat says so.
        for visit_day in ("Sunday", WEEKDAYS[festival.weekday()]):
            outlet = frappe.get_doc({
                "doctype": "FieldMate Outlet", "outlet_name": uid("G2-SHOP"),
                "mobile_no": "9800000000", "territory": territory.name,
                "distributor": customer.name,
                "approval_status": "Approved", "latitude": DELHI[0], "longitude": DELHI[1],
            }).insert(ignore_permissions=True)

            frappe.get_doc({
                "doctype": "FieldMate Beat", "beat_name": uid("G2-BEAT"),
                "territory": territory.name, "assigned_to": rep.name,
                "frequency": "Weekly", "visit_day": visit_day, "is_active": 1,
                "outlets": [{"outlet": outlet.name, "sequence": 1}],
            }).insert(ignore_permissions=True)

        reps.append(rep)

    frappe.db.commit()
    return frappe._dict(reps=reps, territory=territory.name, holiday_list=holiday_list.name,
                        festival=festival, month_start=start, month_end=end)


def criterion_1(fx):
    """A month's plan for 20 reps skips Sundays, the holiday list and one approved leave day."""
    from fieldmate.services import journey as journey_service

    # One rep takes a day off, on a working day that is not the festival.
    on_leave = fx.reps[0]
    # Another occurrence of the beat's own weekday. A leave day on which nothing was planned
    # would be skipped by arithmetic rather than by the leave, and prove nothing at all.
    leave_day = next(
        d for d in every_day(fx)
        if d.weekday() == fx.festival.weekday() and d != fx.festival
    )
    leave_taken = grant_leave(on_leave, leave_day, fx.holiday_list)

    planned = {}
    for rep in fx.reps:
        name = journey_service.generate(rep.name, fx.month_start, fx.month_end,
                                        holiday_list=fx.holiday_list)
        rows = frappe.get_all("FieldMate Journey Plan Day",
                              filters={"parent": name, "parenttype": "FieldMate Journey Plan"},
                              fields=["plan_date", "beat"])
        planned[rep.name] = {getdate(r.plan_date) for r in rows if r.beat}

    sundays = {d for d in every_day(fx) if d.weekday() == 6}
    any_sunday = sundays & set().union(*planned.values())
    any_festival = {rep for rep, days in planned.items() if fx.festival in days}
    leave_planned = leave_taken and leave_day in planned[on_leave.name]

    # A plan with no days in it would satisfy every "skips X" assertion above. The working
    # weekday has to be planned, or this criterion is vacuous.
    working = {d for d in every_day(fx)
               if d.weekday() == fx.festival.weekday() and d != fx.festival}
    busiest = max((len(days) for days in planned.values()), default=0)
    plans_something = bool(working & set().union(*planned.values()))

    check(1, "A month's plan for 20 reps skips Sundays, holidays and approved leave",
          plans_something and not any_sunday and not any_festival and not leave_planned,
          f"{len(fx.reps)} reps, up to {busiest} days each · Sundays planned: {len(any_sunday)} · "
          f"festival planned by: {len(any_festival)} reps · leave day planned: {leave_planned}"
          + ("" if leave_taken
             else "  !! LEAVE NOT EXERCISED - this run proved only the Sunday and holiday rules"))


def every_day(fx):
    cursor, days = fx.month_start, []
    while cursor <= fx.month_end:
        days.append(cursor)
        cursor = add_days(cursor, 1)
    return days


def grant_leave(rep, on_date, holiday_list=None) -> bool:
    """An approved leave day, where this site has hrms. Returns whether one was actually made."""
    if not frappe.db.exists("DocType", "Leave Application"):
        return False
    # Made here rather than assumed. The first run reported "no Leave Application" when hrms was
    # installed all along - the rep simply had no Employee, and the criterion's leave third was
    # quietly passing on an empty test.
    employee = ensure_employee(rep, holiday_list)
    if not employee:
        return False
    try:
        leave_type = ("Leave Without Pay" if frappe.db.exists("Leave Type", "Leave Without Pay")
                      else frappe.db.get_value("Leave Type", {}, "name"))
        doc = frappe.get_doc({
            "doctype": "Leave Application", "employee": employee, "leave_type": leave_type,
            "from_date": on_date, "to_date": on_date, "status": "Approved",
            "leave_approver": "Administrator",
        })
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
        doc.submit()
        return True
    except Exception:
        return False


def criterion_2(fx):
    """Opening the day creates a matching Employee Checkin with correct lat/long."""
    from fieldmate import compat
    from fieldmate.services import day as day_service

    rep = fx.reps[1]
    if not compat.is_installed("hrms"):
        note(2, "Opening the day mirrors into Employee Checkin",
             "hrms is not installed on this site, so there is nothing to mirror into. "
             "The adapter skips quietly by design - hrms is optional (compat REQUIRED_APPS).")
        return None

    employee = ensure_employee(rep, fx.holiday_list)
    if not employee:
        note(2, "Opening the day mirrors into Employee Checkin",
             "no Employee could be created for the rep on this site.")
        return None

    frappe.set_user(rep.user)
    try:
        started = day_service.start(rep.name, {
            "latitude": DELHI[0], "longitude": DELHI[1], "accuracy_m": 8, "selfie": PIXEL,
        })
    finally:
        frappe.set_user("Administrator")

    checkin = frappe.db.get_value("FieldMate Day", started["day"], "employee_checkin")
    geo_ok = True
    detail = f"checkin {checkin}"
    if checkin and compat.capabilities()["checkin_has_geo"]:
        row = frappe.db.get_value("Employee Checkin", checkin, ["latitude", "longitude"],
                                  as_dict=True)
        geo_ok = abs(flt(row.latitude) - DELHI[0]) < 0.0001 \
            and abs(flt(row.longitude) - DELHI[1]) < 0.0001
        detail += f" at {flt(row.latitude):.4f}, {flt(row.longitude):.4f}"
    elif checkin:
        detail += " (this hrms build has no geo columns, so lat/long is not mirrored)"

    check(2, "Day Start creates a matching Employee Checkin with correct lat/long",
          bool(checkin) and geo_ok, detail)

    note("2b", "The same on v16",
         "This bench runs v15 only. v16 is a CI matrix question, not something this script can "
         "answer, and asserting it from here would be a claim rather than a check.")
    return started


def ensure_employee(rep, holiday_list=None):
    employee = frappe.db.get_value("FieldMate Field User", rep.name, "employee")
    if employee:
        return employee
    if not frappe.db.exists("DocType", "Employee"):
        return None
    try:
        company = frappe.db.get_value("Company", {}, "name")
        doc = frappe.get_doc({
            "doctype": "Employee", "first_name": rep.full_name, "company": company,
            "date_of_joining": add_days(today(), -365), "date_of_birth": add_days(today(), -9000),
            "gender": frappe.db.get_value("Gender", {}, "name"), "status": "Active",
            # hrms refuses a leave against an employee with no holiday list, and the message
            # names the company rather than the leave, which sends you looking in the wrong place.
            "holiday_list": holiday_list,
        })
        doc.flags.ignore_permissions = True
        doc.insert(ignore_permissions=True)
        frappe.db.set_value("FieldMate Field User", rep.name, "employee", doc.name,
                            update_modified=False)
        return doc.name
    except Exception:
        return None


def criterion_3(fx, started):
    """A full day of pings stores as one Location Trail row; distance within 10% of odometer."""
    from fieldmate.services import trail as trail_service

    rep = fx.reps[1]
    # A straight 10 km run, one ping a minute for nine hours - a realistic day on a beat.
    # Pings are {lat, lon, t}, keyed short because a day of them travels over a 2G uplink.
    # 0.001 degrees of latitude is about 111 m, so 90 steps is roughly 10 km.
    pings, lat = [], DELHI[0]
    stamp = add_to_date(now_datetime(), hours=-9)
    for minute in range(540):
        if minute % 6 == 0:
            lat += 0.001
        pings.append({"lat": round(lat, 6), "lon": DELHI[1],
                      "t": str(add_to_date(stamp, minutes=minute)), "acc": 8})

    frappe.set_user(rep.user)
    try:
        # Sent in six batches, as the pinger does. One row must come out of it, not six.
        for batch in range(0, len(pings), 90):
            trail_service.append(rep.name, pings[batch:batch + 90],
                                 day=started["day"] if started else None)
    finally:
        frappe.set_user("Administrator")

    rows = frappe.get_all("FieldMate Location Trail",
                          filters={"field_user": rep.name, "trail_date": today()},
                          fields=["name", "total_distance_km", "ping_count"])
    distance = flt(rows[0].total_distance_km) if rows else 0
    odometer = 10.0
    within = abs(distance - odometer) / odometer <= 0.10 if distance else False

    check(3, "A day of pings stores as one Location Trail row, distance within 10% of odometer",
          len(rows) == 1 and within,
          f"{len(pings)} pings in 6 batches -> {len(rows)} row, {rows[0].ping_count if rows else 0} "
          f"pings kept · {distance:.2f} km against a 10.00 km odometer")


def criterion_4(fx):
    """A developer-options mock location is flagged, not silently accepted."""
    from fieldmate.services import day as day_service

    rep = fx.reps[2]
    frappe.set_user(rep.user)
    try:
        started = day_service.start(rep.name, {
            "latitude": DELHI[0], "longitude": DELHI[1], "accuracy_m": 5, "selfie": PIXEL,
            "is_mock_location": 1, "location_provider": "mock",
        })
    finally:
        frappe.set_user("Administrator")

    flagged = frappe.db.get_value("FieldMate Day", started["day"], "is_mock_location")

    check(4, "A mock location is flagged rather than silently accepted",
          bool(flagged) and bool(started.get("day")),
          "the day still starts - a rep is not blocked on the word of a flag that can be wrong - "
          f"but it is recorded: is_mock_location = {flagged}")


def criterion_5(fx, started):
    """Killing the app mid-day and reopening resumes the same open day."""
    from fieldmate.services import day as day_service

    rep = fx.reps[1]
    if not started:
        frappe.set_user(rep.user)
        try:
            started = day_service.start(rep.name, {
                "latitude": DELHI[0], "longitude": DELHI[1], "selfie": PIXEL,
            })
        finally:
            frappe.set_user("Administrator")

    # What a reopened app does: ask the server what is going on, with nothing cached.
    frappe.set_user(rep.user)
    try:
        first = day_service.current(rep.name)
        second = day_service.current(rep.name)
    finally:
        frappe.set_user("Administrator")

    same = bool(first) and first.get("day") == started["day"]
    stable = bool(second) and second.get("day") == first.get("day")

    check(5, "Reopening resumes the same open day",
          same and stable,
          f"day {started['day']} reads back identically, still open")

    note("5b", "Killing the app itself",
         "A client behaviour. The server half is proved above; the phone half is step C4 of "
         "MANUAL_TESTS_PHASE4.md and needs a real device.")


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    print(f"\nGate 2 on {SITE}\n" + "-" * 74)
    try:
        fx = build_fixtures()
        criterion_1(fx)
        started = criterion_2(fx)
        criterion_3(fx, started)
        criterion_4(fx)
        criterion_5(fx, started)
    finally:
        # A rollback is not enough on its own. This script commits its fixtures, and several of
        # the services it exercises commit internally anyway, so a transaction lasting to the end
        # was never on offer - six runs of gate2 left 868 records on testerp2 before anybody
        # noticed. The rollback stays as a backstop; `purge` is what actually clears up.
        frappe.db.rollback()
        try:
            purge("G2")
        except Exception as e:
            print(f"  !! could not clean up: {e} - run scripts/clean_gate_fixtures.py")
        frappe.destroy()

    print("-" * 74)
    checked = [r for r in results if r[2] is not None]
    passed = sum(1 for *_, ok, _d in checked if ok)
    skipped = len(results) - len(checked)
    print(f"Gate 2: {passed}/{len(checked)} criteria passed"
          + (f", {skipped} not testable on this bench" if skipped else "") + "\n")
    sys.exit(0 if passed == len(checked) else 1)


if __name__ == "__main__":
    main()
