"""Seed everything the Phase 3 manual test needs, in one command.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_manual_test.py
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_manual_test.py --undo

Part A of MANUAL_TESTS_PHASE3.md is ten minutes of fiddly desk work, and three of its
steps only exist to prove the template validation refuses bad input. A script does both
better: it creates the survey, and it *demonstrates* the three refusals instead of asking
somebody to trigger them by hand.

It also sets up two things Part A never mentioned but the rest of the test needs:

  * a **journey plan**, without which the Today screen shows no beat and every visit
    reads as a deviation - so the planned-vs-deviation steps could never pass;
  * an **outlet class** with a real minimum visit length, because the global default is
    3 minutes and no realistic visit is shorter than that, so the short-visit flag would
    never fire.

Safe to run twice: everything is looked up by name first.
"""

import sys

import frappe
from frappe.utils import add_days, getdate, today

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
    if not arg.startswith("--"):
        SITE = arg

UNDO = "--undo" in sys.argv

TEMPLATE_NAME = "Manual Test - Shelf And Stock"
CLASS_NAME = "Manual Test A Class"
REASONS = [
    {"reason": "Stock still with him", "category": "Stock", "requires_note": 0,
     "description": "He has not sold through the last delivery yet."},
    {"reason": "Shop refused", "category": "Shop", "requires_note": 1,
     "description": "Needs a note - a refusal with no reason teaches nobody anything."},
]

# One question per answer type, plus one that only appears when SHELF is answered No.
QUESTIONS = [
    {"question_code": "SHELF", "question": "Is our shelf clean and well faced?",
     "answer_type": "Yes/No", "is_required": 1, "sequence": 1,
     "help_text": "Look at the whole shelf, not just our block."},
    {"question_code": "WHYNOT", "question": "Why is the shelf not right?",
     "answer_type": "Text", "is_required": 0, "sequence": 2,
     "depends_on_code": "SHELF", "depends_on_value": "No",
     "help_text": "Only asked when the shelf is not clean."},
    {"question_code": "FACINGS", "question": "How many facings do we have?",
     "answer_type": "Number", "is_required": 1, "sequence": 3,
     "min_value": 0, "max_value": 50,
     "help_text": "Zero is a real answer. Record it."},
    {"question_code": "STOCK", "question": "What is his stock level?",
     "answer_type": "Single Choice", "options": "Full\nLow\nOut of stock",
     "is_required": 1, "sequence": 4},
    {"question_code": "NOTE", "question": "Anything the owner said worth passing on?",
     "answer_type": "Text", "is_required": 0, "sequence": 5},
    {"question_code": "RATE", "question": "Rate the shop's overall display",
     "answer_type": "Rating", "is_required": 0, "sequence": 6},
]

made, skipped = [], []


def note(kind, what, detail=""):
    (made if kind == "created" else skipped).append(what)
    print(f"  {kind:<8} {what}" + (f"   {detail}" if detail else ""))


# --------------------------------------------------------------------------- A3/A4/A5


def prove_refusals(territory):
    """Trigger the three validations Part A asks a human to trigger by hand."""
    print("\n### The template validation refuses bad input (steps A3, A4, A5) ###")

    cases = [
        ("A3  a question that depends on one asked later", [
            {"question_code": "CHILD", "question": "Why not?", "answer_type": "Text",
             "sequence": 1, "depends_on_code": "PARENT", "depends_on_value": "No"},
            {"question_code": "PARENT", "question": "In stock?", "answer_type": "Yes/No",
             "sequence": 2},
        ], "comes later"),
        ("A4  two questions sharing one code", [
            {"question_code": "DUP", "question": "First", "answer_type": "Text",
             "sequence": 1},
            {"question_code": "DUP", "question": "Second", "answer_type": "Text",
             "sequence": 2},
        ], "both use the code"),
        ("A5  a choice question with no options", [
            {"question_code": "NOOPT", "question": "Which one?",
             "answer_type": "Single Choice", "sequence": 1},
        ], "no options"),
    ]

    for label, questions, expected in cases:
        # A savepoint, never a bare rollback. `frappe.db.rollback()` with no savepoint
        # discards the entire transaction - including everything build() just created a
        # few lines above, which is precisely the bug this script had on its first run.
        mark = "fm_setup_" + frappe.generate_hash(length=8)
        frappe.db.savepoint(mark)
        try:
            frappe.get_doc({
                "doctype": "FieldMate Checklist Template",
                "template_name": f"REFUSAL CHECK {frappe.generate_hash(length=6)}",
                "is_active": 0, "applies_to": "Every Visit", "effective_from": today(),
                "territory": territory, "questions": questions,
            }).insert(ignore_permissions=True)
            frappe.db.rollback(save_point=mark)
            print(f"  NOT REFUSED  {label}  <-- this is a bug, report it")
        except frappe.ValidationError as e:
            message = frappe.utils.strip_html(str(e))
            frappe.db.rollback(save_point=mark)
            print(f"  {'refused ' if expected in message else 'WRONG   '} {label}")
            print(f"           -> {message.strip()[:100]}")


# --------------------------------------------------------------------------- build


def build():
    territory = "All Territories"      # the root: covers every shop, see ADR-020

    # ---- the survey -------------------------------------------------------
    existing = frappe.db.get_value("FieldMate Checklist Template",
                                   {"template_name": TEMPLATE_NAME}, "name")
    if existing:
        template = frappe.get_doc("FieldMate Checklist Template", existing)
        note("exists", f"Checklist Template {template.name}",
             f"v{template.version}, {template.question_count} questions")
    else:
        template = frappe.get_doc({
            "doctype": "FieldMate Checklist Template",
            "template_name": TEMPLATE_NAME,
            "is_active": 1,
            "applies_to": "Every Visit",
            "effective_from": today(),
            "territory": territory,
            "questions": QUESTIONS,
        }).insert(ignore_permissions=True)
        note("created", f"Checklist Template {template.name}",
             f"v{template.version}, {template.question_count} questions")

    # ---- no-order reasons -------------------------------------------------
    for row in REASONS:
        found = frappe.db.get_value("FieldMate No Order Reason", {"reason": row["reason"]}, "name")
        if found:
            note("exists", f"No Order Reason  {row['reason']}")
            continue
        doc = frappe.get_doc({"doctype": "FieldMate No Order Reason", "is_active": 1, **row})
        doc.insert(ignore_permissions=True)
        note("created", f"No Order Reason  {row['reason']}",
             "needs a note" if row["requires_note"] else "")

    # ---- an outlet class with a testable minimum --------------------------
    found = frappe.db.get_value("FieldMate Outlet Class", {"class_name": CLASS_NAME}, "name")
    if found:
        klass = frappe.get_doc("FieldMate Outlet Class", found)
        note("exists", f"Outlet Class {klass.name}")
    else:
        klass = frappe.get_doc({
            "doctype": "FieldMate Outlet Class",
            "class_name": CLASS_NAME,
            "is_active": 1,
            "visits_per_month": 4,
            "min_visit_duration_minutes": 10,
            "description": "Ten minutes, so the short-visit flag is actually reachable. "
                           "The global default is 3, which no real visit ever undercuts.",
        }).insert(ignore_permissions=True)
        note("created", f"Outlet Class {klass.name}", "minimum 10 minutes")

    # Put it on exactly one shop, so there is something to compare against.
    target = frappe.db.get_value("FieldMate Outlet", {"outlet_name": "SHOP-3"}, "name") \
        or frappe.db.get_value("FieldMate Outlet", {}, "name")
    if target and frappe.db.get_value("FieldMate Outlet", target, "outlet_class") != klass.name:
        shop = frappe.get_doc("FieldMate Outlet", target)
        shop.outlet_class = klass.name
        shop.save(ignore_permissions=True)
        note("created", f"{shop.outlet_name} is now {CLASS_NAME}",
             "a visit here under 10 min flags as short")
    elif target:
        note("exists", f"{frappe.db.get_value('FieldMate Outlet', target, 'outlet_name')} "
                       f"already {CLASS_NAME}")

    # ---- a distributor, or "Add a shop" cannot save -----------------------
    #
    # `distributor` is mandatory on FieldMate Outlet and the app deliberately never asks a rep
    # to choose one. With nothing on the rep's record and no profile covering their territory,
    # every attempt to onboard a shop failed. Found on a real phone, not by a test.
    distributor = frappe.db.get_value("Customer", {"disabled": 0}, "name")
    if not distributor:
        note("skipped", "no Customer exists to act as a distributor")
    else:
        for rep_name in frappe.get_all("FieldMate Field User",
                                       filters={"status": "Active"}, pluck="name"):
            rep = frappe.get_doc("FieldMate Field User", rep_name)
            if rep.distributor:
                note("exists", f"{rep.name} -> {rep.distributor}")
                continue
            rep.distributor = distributor
            rep.save(ignore_permissions=True)
            note("created", f"{rep.name} -> {distributor}", "can now add shops")

        profile = frappe.db.get_value("FieldMate Distributor Profile",
                                      {"customer": distributor}, "name")
        if profile:
            note("exists", f"Distributor Profile {profile}")
        else:
            doc = frappe.get_doc({
                "doctype": "FieldMate Distributor Profile",
                "customer": distributor,
                "territory": frappe.db.get_value("FieldMate Outlet", {}, "territory")
                or "All Territories",
                "status": "Active",
            }).insert(ignore_permissions=True)
            note("created", f"Distributor Profile {doc.name}", f"for {distributor}")

    # ---- a journey plan, or the Today screen has no beat ------------------
    from fieldmate.services import journey as journey_service

    for rep in frappe.get_all("FieldMate Field User",
                              filters={"status": "Active"}, pluck="name"):
        if not journey_service.beats_for(rep):
            continue

        from_date, to_date = getdate(today()), add_days(getdate(today()), 20)
        live = frappe.db.get_value("FieldMate Journey Plan", {
            "field_user": rep, "docstatus": 1,
            "from_date": ["<=", to_date], "to_date": [">=", from_date],
        }, "name")
        if live:
            note("exists", f"Journey Plan {live}", f"for {rep}")
            continue

        doc = frappe.get_doc(
            "FieldMate Journey Plan",
            journey_service.generate(rep, from_date, to_date, submit=True),
        )
        working = sum(1 for d in doc.days if d.beat)
        note("created", f"Journey Plan {doc.name}",
             f"for {rep}: {working} working days to {to_date}")

    return template


def show_state():
    print("\n### What the rep will see ###")

    planned = None
    from fieldmate.services import journey as journey_service
    for rep in frappe.get_all("FieldMate Field User",
                              filters={"status": "Active"}, pluck="name"):
        day = journey_service.day_for(rep, today())
        if not day:
            continue
        planned = day
        print(f"  {rep}")
        print(f"      today ({getdate(today()).strftime('%A %d %b %Y')}): "
              f"beat={day.get('beat') or 'none'}  status={day.get('status')}  "
              f"shops={day.get('outlet_count')}")

    if not planned:
        print(f"  Nobody has a beat today ({getdate(today()).strftime('%A')}). "
              f"The beat on this site runs on its own visit_day - check the next one below.")

    print("\n  Shops available to visit:")
    for o in frappe.get_all("FieldMate Outlet",
                            fields=["outlet_name", "territory", "outlet_class",
                                    "latitude", "longitude", "geo_fence_radius_m"]):
        print(f"      {o['outlet_name']:<10} {o['territory']:<12} "
              f"class={o['outlet_class'] or '-':<22} "
              f"fence={o['geo_fence_radius_m']}m  "
              f"pin={'yes' if o['latitude'] else 'NO PIN'}")

    s = frappe.get_single("FieldMate Settings")
    print(f"\n  Settings that shape the test:")
    print(f"      geo-fence enforced        {bool(s.enforce_geo_fence)}")
    print(f"      default fence radius      {s.default_geo_fence_radius_m} m")
    print(f"      exceptions allowed        {bool(s.allow_geo_fence_exception)}")
    print(f"      minimum visit (global)    {s.min_visit_duration_minutes} min")
    print(f"      photo budget              {s.photo_max_kb} KB at {s.photo_max_dimension_px} px")
    print(f"      start-of-day photo        {'required' if s.require_day_start_selfie else 'optional'}")


def undo():
    print("### Removing what this script created ###")

    for reason in REASONS:
        name = frappe.db.get_value("FieldMate No Order Reason", {"reason": reason["reason"]}, "name")
        if name:
            frappe.delete_doc("FieldMate No Order Reason", name, force=True, ignore_permissions=True)
            note("deleted", f"No Order Reason  {reason['reason']}")

    name = frappe.db.get_value("FieldMate Checklist Template", {"template_name": TEMPLATE_NAME}, "name")
    if name:
        frappe.delete_doc("FieldMate Checklist Template", name, force=True, ignore_permissions=True)
        note("deleted", f"Checklist Template {name}")

    klass = frappe.db.get_value("FieldMate Outlet Class", {"class_name": CLASS_NAME}, "name")
    if klass:
        for outlet in frappe.get_all("FieldMate Outlet", filters={"outlet_class": klass}, pluck="name"):
            frappe.db.set_value("FieldMate Outlet", outlet, "outlet_class", None)
        frappe.delete_doc("FieldMate Outlet Class", klass, force=True, ignore_permissions=True)
        note("deleted", f"Outlet Class {klass}")

    # Journey plans are left alone. They are ordinary planning data, not test scaffolding,
    # and deleting a submitted plan a rep may already have worked against is not this
    # script's business.
    print("  kept     journey plans (real planning data, not scaffolding)")


def main():
    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user("Administrator")

    print(f"\nPhase 3 manual-test setup on {SITE}")
    print("=" * 70)
    try:
        if UNDO:
            undo()
        else:
            template = build()
            prove_refusals("All Territories")
            show_state()
            print("\n" + "=" * 70)
            print(f"Part A is done. Survey: {template.name} "
                  f"({template.question_count} questions, version {template.version})")
            print("Open the app and start at Part B.")
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.destroy()

    print(f"\ncreated {len(made)}, already present {len(skipped)}\n")


if __name__ == "__main__":
    main()
