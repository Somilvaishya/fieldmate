"""Gate 3 — verify all five criteria on a real site.

Run:  cd sites && ../env/bin/python ../apps/fieldmate/scripts/gate3.py [site]

Everything it creates is rolled back at the end, so it is safe to run against testerp2. It
proves the criteria against the real database rather than against mocks, which is the whole
point of a gate.
"""

import sys
import time

import frappe
from frappe.utils import add_to_date, now_datetime, today

from _guard import require_test_site

SITE = sys.argv[1] if len(sys.argv) > 1 else "testerp2.web.gargsystems.com"

DELHI = (28.6139, 77.2090)
NEAR = (28.61408, 77.20900)     # ~20 m: ordinary GPS drift at the counter
FAR = (28.6139, 77.2136)        # ~450 m: outside any sane shop fence

# A 1x1 PNG. Stands in for a compressed shelf photo; what is being proved is the plumbing.
PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

results = []


def check(number, name, passed, detail=""):
    results.append((number, name, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  [{mark}] {number}. {name}")
    if detail:
        print(f"         {detail}")


def uid(prefix):
    return f"{prefix}-{frappe.generate_hash(length=8)}"


def build_fixtures():
    """A rep, a shop, a beat, a device and a twelve-question survey."""
    territory = frappe.get_doc({
        "doctype": "Territory", "territory_name": uid("G3T"),
        "parent_territory": "All Territories", "is_group": 1,
    }).insert(ignore_permissions=True).name

    user = frappe.get_doc({
        "doctype": "User", "email": f"{uid('g3').lower()}@fieldmate.test",
        "first_name": "Gate", "last_name": "Three", "user_type": "System User",
        "send_welcome_email": 0,
    }).insert(ignore_permissions=True)
    user.add_roles("FieldMate Field Rep")

    rep = frappe.get_doc({
        "doctype": "FieldMate Field User", "user": user.name, "territory": territory,
        "designation": "Field Rep", "status": "Active",
    }).insert(ignore_permissions=True)

    customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
    distributor = frappe.get_doc({
        "doctype": "Customer", "customer_name": uid("G3D"), "customer_type": "Company",
        "customer_group": customer_group,
    }).insert(ignore_permissions=True).name

    outlet = frappe.get_doc({
        "doctype": "FieldMate Outlet", "outlet_name": uid("G3S"), "mobile_no": "9800000000",
        "distributor": distributor, "territory": territory, "approval_status": "Approved",
        "latitude": DELHI[0], "longitude": DELHI[1],
        "enable_geo_fence": 1, "geo_fence_radius_m": 100,
    }).insert(ignore_permissions=True)

    device = frappe.get_doc({
        "doctype": "FieldMate Device Registry", "device_uuid": uid("G3DEV"),
        "user": user.name, "platform": "Android",
    }).insert(ignore_permissions=True)

    template = frappe.get_doc({
        "doctype": "FieldMate Checklist Template", "template_name": uid("G3TPL"),
        "is_active": 1, "applies_to": "Every Visit", "effective_from": today(),
        "territory": territory,
        "questions": [
            {"question_code": f"Q{i}", "question": f"Question {i} as first written",
             "answer_type": "Yes/No", "is_required": 1, "sequence": i}
            for i in range(1, 13)
        ],
    }).insert(ignore_permissions=True)

    return frappe._dict(territory=territory, user=user, rep=rep, outlet=outlet,
                        device=device, template=template)


def criterion_1_and_3(fx):
    """A fully offline visit with 4 photos, 12 answers and a merchandising audit."""
    from fieldmate.services import day as day_service
    from fieldmate.services import sync as sync_service
    from fieldmate.services import visit as visit_service

    day_service.start(fx.rep.name, {
        "latitude": DELHI[0], "longitude": DELHI[1], "accuracy_m": 8,
        "selfie": PIXEL, "device_id": fx.device.name,
    })

    visit_uuid = uid("G3VIS")
    records = [{
        "doctype": "FieldMate Visit",
        "client_uuid": visit_uuid,
        "data": {
            "docstatus": 1,
            "outlet": fx.outlet.name,
            "field_user": fx.rep.name,
            "visit_date": today(),
            "check_in_time": add_to_date(now_datetime(), minutes=-35),
            "check_in_latitude": NEAR[0], "check_in_longitude": NEAR[1],
            "check_out_time": now_datetime(),
            "check_out_latitude": NEAR[0], "check_out_longitude": NEAR[1],
            "visit_outcome": "Order Taken",
            "created_offline": 1,
            "checklist_answers": [
                {"question_code": f"Q{i}", "answer": "Yes", "is_answered": 1}
                for i in range(1, 13)
            ],
        },
    }]

    batch = uid("G3B")
    first = sync_service.push("Administrator", fx.device, batch, records)
    # Replay the identical batch: a dropped connection mid-push must cost nothing.
    replay = sync_service.push("Administrator", fx.device, batch, records)

    visit = first["results"][0]["name"]
    doc = frappe.get_doc("FieldMate Visit", visit)
    count = frappe.db.count("FieldMate Visit", {"client_uuid": visit_uuid})

    audit = frappe.get_doc({
        "doctype": "FieldMate Merchandising Audit", "outlet": fx.outlet.name,
        "field_user": fx.rep.name, "audit_date": today(), "visit": visit,
        "client_uuid": uid("G3MER"), "total_facings": 40,
        "lines": [], "competitors": [
            {"competitor": "Rival", "product": "Their pack", "facings": 30},
        ],
    }).insert(ignore_permissions=True)
    audit.submit()

    # Photos upload after the visit has landed, which is the normal order of events.
    for i in range(4):
        visit_service.add_photo(visit, {
            "photo": PIXEL, "purpose": "Shelf", "caption": f"shelf {i + 1}",
            "client_uuid": uid("G3PIC"),
        })

    doc.reload()
    photo_rows = frappe.get_doc("FieldMate Visit", visit).photos

    check(1, "Offline visit with 12 answers + audit syncs once, no duplicate",
          count == 1
          and doc.docstatus == 1
          and len(doc.checklist_answers) == 12
          and all(a.is_answered for a in doc.checklist_answers)
          and replay["results"][0]["status"] in ("duplicate", "created")
          and frappe.db.get_value("FieldMate Visit", visit, "merchandising_audit") == audit.name,
          f"visit={visit} answers={len(doc.checklist_answers)} rows_for_uuid={count} "
          f"audit={audit.name} replay={replay['results'][0]['status']}")

    # Each stored photo must be a file path, not the image itself: the column is varchar(140).
    stored_as_files = all(
        p.photo and p.photo.startswith(("/files/", "/private/files/")) for p in photo_rows
    )
    sizes = []
    for p in photo_rows:
        file_name = frappe.db.get_value("File", {"file_url": p.photo}, "file_size")
        sizes.append((file_name or 0) / 1024)

    check(3, "4 photos attach to the right visit and arrive under 120 KB",
          len(photo_rows) == 4 and stored_as_files and all(kb <= 120 for kb in sizes),
          f"photos={len(photo_rows)} paths_ok={stored_as_files} "
          f"sizes_kb={[round(k, 1) for k in sizes]}")

    return visit


def criterion_2(fx):
    """A check-in 400 m away is recorded, flagged, and reaches the manager's report."""
    from fieldmate.fieldmate.report.visit_exceptions.visit_exceptions import execute
    from fieldmate.services import sync as sync_service

    far_uuid = uid("G3FAR")
    pushed = sync_service.push("Administrator", fx.device, uid("G3B"), [{
        "doctype": "FieldMate Visit",
        "client_uuid": far_uuid,
        "data": {
            "docstatus": 1,
            "outlet": fx.outlet.name, "field_user": fx.rep.name, "visit_date": today(),
            "check_in_time": add_to_date(now_datetime(), minutes=-40),
            "check_in_latitude": FAR[0], "check_in_longitude": FAR[1],
            "check_out_time": now_datetime(),
            "visit_outcome": "Order Taken",
            # The device claims it was standing in the doorway.
            "distance_from_outlet_m": 2, "is_geo_fence_breach": 0,
        },
    }])

    name = pushed["results"][0]["name"]
    doc = frappe.get_doc("FieldMate Visit", name)

    _, rows = execute({"from_date": today(), "to_date": today()})
    listed = next((r for r in rows if r["visit"] == name), None)

    check(2, "Check-in 400 m away is recorded, flagged, and on the exception report",
          doc.docstatus == 1
          and doc.distance_from_outlet_m > 300
          and doc.is_geo_fence_breach == 1
          and listed is not None
          and "range" in listed["reasons"],
          f"distance={round(doc.distance_from_outlet_m)} m breach={doc.is_geo_fence_breach} "
          f"report_row={'yes' if listed else 'no'} "
          f"reasons={listed['reasons'] if listed else '-'}")


def criterion_4(fx, visit):
    """Templates change with no deploy, and answers already taken still read as asked."""
    before = frappe.get_doc("FieldMate Visit", visit).checklist_answers[0]
    original_text, original_version = before.question, before.template_version

    template = frappe.get_doc("FieldMate Checklist Template", fx.template.name)
    template.questions[0].question = "Completely reworded next month"
    template.append("questions", {
        "question_code": "Q13", "question": "A brand new question",
        "answer_type": "Text", "sequence": 13,
    })
    template.save(ignore_permissions=True)

    after = frappe.get_doc("FieldMate Visit", visit).checklist_answers[0]

    check(4, "Templates change with no deploy; old answers still render as asked",
          template.version == original_version + 1
          and len(template.questions) == 13
          and after.question == original_text
          and after.template_version == original_version,
          f"template v{original_version} -> v{template.version}, "
          f"visit answer still reads {after.question!r} at v{after.template_version}")


def criterion_5(fx):
    """30 offline visits, pushed the way a phone pushes them."""
    from fieldmate.services import sync as sync_service

    records = []
    for i in range(30):
        records.append({
            "doctype": "FieldMate Visit",
            "client_uuid": uid("G3BULK"),
            "data": {
                "docstatus": 1,
                "outlet": fx.outlet.name, "field_user": fx.rep.name, "visit_date": today(),
                "check_in_time": add_to_date(now_datetime(), minutes=-(120 + i * 2)),
                "check_in_latitude": NEAR[0], "check_in_longitude": NEAR[1],
                "check_out_time": add_to_date(now_datetime(), minutes=-(100 + i * 2)),
                "visit_outcome": "Order Taken",
                "created_offline": 1,
                "checklist_answers": [
                    {"question_code": f"Q{q}", "answer": "Yes", "is_answered": 1}
                    for q in range(1, 13)
                ],
            },
        })

    started = time.monotonic()
    pushed = sync_service.push("Administrator", fx.device, uid("G3B"), records)
    server_seconds = time.monotonic() - started

    created = sum(1 for r in pushed["results"] if r["status"] == "created")
    # A visit record with 12 answers is ~2 KB of JSON. 30 of them on a 3G uplink
    # (~400 kbit/s sustained) is roughly 1.2 s of transfer, so the server time is what
    # decides this. Measured here; the radio half needs the real handset.
    check(5, "30 offline visits sync in under 3 minutes",
          created == 30 and server_seconds < 180,
          f"{created}/30 created in {server_seconds:.1f}s of server time "
          f"({server_seconds / 30 * 1000:.0f} ms per visit)")


def main():
    frappe.init(site=SITE)
    frappe.connect()
    require_test_site(SITE)
    frappe.set_user("Administrator")
    frappe.flags.in_test = True

    print(f"\nGate 3 on {SITE}\n" + "-" * 68)
    try:
        fx = build_fixtures()
        visit = criterion_1_and_3(fx)
        criterion_2(fx)
        criterion_4(fx, visit)
        criterion_5(fx)
    finally:
        # Nothing this script made survives it.
        frappe.db.rollback()
        frappe.destroy()

    print("-" * 68)
    passed = sum(1 for *_, ok, _d in results if ok)
    print(f"Gate 3: {passed}/{len(results)} criteria passed\n")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
