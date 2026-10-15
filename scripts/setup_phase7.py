"""Seed everything the Phase 7 manual test needs, in one command.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase7.py
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase7.py --undo
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase7.py --show

The performance screen opens on "no target has been set for you" without this, which is correct
behaviour and useless to test against. Four things have to exist before it says anything:

  1. expense rates in Settings          - a travel claim is refused without a rate, by design
  2. a Sales Person on each field user  - the target tree hangs off ERPNext's own hierarchy
  3. a target plan covering this month  - cascaded, so the leaves are what a rep sees
  4. an incentive scheme with slabs     - so the screen has something to be on track for

It attaches to the field users already on the site rather than inventing reps, because a target
tree over people nobody sells through proves nothing about the site it runs on.

Safe to run twice: everything is looked up by name first.
"""

import sys

import frappe
from frappe.utils import add_days, get_first_day, get_last_day, today

from _guard import run_setup

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
	if not arg.startswith("--"):
		SITE = arg

UNDO = "--undo" in sys.argv
SHOW = "--show" in sys.argv

ROOT_PERSON = "FM National"
PLAN_NAME = "FieldMate Phase 7 demo"
SCHEME_NAME = "FieldMate Phase 7 demo incentive"

# None of these divides evenly by the number of reps on a real site, which is the point: a
# cascade that only works on round numbers works on nothing.
NATIONAL_LINES = [
	("Value", 10_00_000),
	("Volume", 5_001),
	("Outlet Coverage", 617),
	("Productive Calls", 413),
	("New Outlets", 27),
	("Lines Per Call", 4.5),
]


def note(verb: str, what: str, detail: str = "") -> None:
	print(f"  {verb:8} {what}" + (f"   ({detail})" if detail else ""))


# --------------------------------------------------------------------------------------


def configure_settings() -> None:
	settings = frappe.get_single("FieldMate Settings")
	changed = []
	for key, value in (("travel_rate_per_km", 3.5),
	                   ("daily_food_allowance", 250),
	                   ("daily_stay_allowance", 0),
	                   ("expense_receipt_required_above", 500),
	                   ("expense_distance_tolerance_pct", 10)):
		if not settings.get(key):
			settings.set(key, value)
			changed.append(f"{key}={value}")

	if changed:
		settings.flags.ignore_permissions = True
		settings.save(ignore_permissions=True)
		frappe.cache().delete_value("fieldmate_settings")
		note("set", "FieldMate Settings", ", ".join(changed))
	else:
		note("kept", "FieldMate Settings", "already configured")


def sales_person(name: str, parent: str | None = None, is_group: int = 1) -> str:
	existing = frappe.db.get_value("Sales Person", {"sales_person_name": name}, "name")
	if existing:
		return existing
	doc = frappe.get_doc({
		"doctype": "Sales Person",
		"sales_person_name": name,
		"parent_sales_person": parent,
		"is_group": is_group,
		"enabled": 1,
	}).insert(ignore_permissions=True)
	note("created", f"Sales Person {name}")
	return doc.name


def attach_reps() -> list[str]:
	"""Give every active field user a Sales Person under the root, if they have none.

	A rep off the tree cannot be reached by a cascade, and the symptom on the phone is a screen
	saying no target has been set - which is true, and unhelpful.
	"""
	root = sales_person(ROOT_PERSON)
	attached = []

	for rep in frappe.get_all("FieldMate Field User",
	                          filters={"status": "Active"},
	                          fields=["name", "full_name", "sales_person"]):
		if rep.sales_person:
			attached.append(rep.sales_person)
			note("kept", f"{rep.name}", f"-> {rep.sales_person}")
			continue
		person = sales_person(f"FM {rep.full_name or rep.name}"[:140], parent=root, is_group=0)
		frappe.db.set_value("FieldMate Field User", rep.name, "sales_person", person)
		attached.append(person)
		note("linked", f"{rep.name}", f"-> {person}")

	return attached


def build_plan(company: str) -> str | None:
	existing = frappe.db.get_value("FieldMate Target Plan",
	                               {"plan_name": PLAN_NAME, "is_root": 1, "docstatus": 1}, "name")
	if existing:
		note("kept", f"Target plan {existing}")
		return existing

	root = sales_person(ROOT_PERSON)
	doc = frappe.get_doc({
		"doctype": "FieldMate Target Plan",
		"plan_name": PLAN_NAME,
		"company": company,
		"from_date": get_first_day(today()),
		"to_date": get_last_day(today()),
		"sales_person": root,
		"cascade_basis": "Outlet Count",
		"lines": [{"target_type": t, "target_value": v} for t, v in NATIONAL_LINES],
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	note("created", f"Target plan {doc.name}", f"{get_first_day(today())} to {get_last_day(today())}")

	from fieldmate.services import target as target_service
	result = target_service.cascade(doc.name)
	note("cascaded", f"{len(result['children'])} child plan(s)", result.get("basis", ""))

	report = target_service.reconcile(doc.name)
	note("checked", "leaves against root",
	     "they add up" if report["matches"] else "THEY DO NOT ADD UP - investigate")
	return doc.name


def build_scheme(company: str) -> str | None:
	if frappe.db.exists("FieldMate Incentive Scheme", SCHEME_NAME):
		note("kept", f"Incentive scheme {SCHEME_NAME}")
		return SCHEME_NAME

	doc = frappe.get_doc({
		"doctype": "FieldMate Incentive Scheme",
		"scheme_name": SCHEME_NAME,
		"company": company,
		"is_active": 1,
		"valid_from": add_days(today(), -60),
		"measured_on": "Value",
		"qualifying_pct": 80,
		"description": "Hit 80% of your value target to start earning.",
		"slabs": [
			{"slab_idx": 1, "from_pct": 80, "to_pct": 100, "payout_kind": "Fixed Amount",
			 "payout_amount": 4200, "label": "Tier 1"},
			{"slab_idx": 2, "from_pct": 100, "to_pct": 120, "payout_kind": "Fixed Amount",
			 "payout_amount": 6000, "label": "Tier 2"},
			{"slab_idx": 3, "from_pct": 120, "is_open_ended": 1, "payout_kind": "Fixed Amount",
			 "payout_amount": 9000, "label": "Tier 3"},
		],
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()
	note("created", f"Incentive scheme {doc.name}", "3 slabs, qualifies at 80%")
	return doc.name


def measure() -> None:
	from fieldmate.services import target as target_service
	result = target_service.compute_all()
	note("measured", f"{result['computed']} of {result['plans']} plan(s)",
	     f"{len(result['failed'])} failed" if result["failed"] else "")


# --------------------------------------------------------------------------------------


def build() -> None:
	print("\nBuilding Phase 7 fixtures")
	print("-" * 72)

	company = frappe.db.get_single_value("FieldMate Settings", "default_company") \
		or frappe.db.get_value("Company", {}, "name")

	configure_settings()
	people = attach_reps()
	if not people:
		print("\n  !! No active field users on this site, so a target has nobody to reach.")
		print("     Create one, then re-run this.\n")
		return

	build_plan(company)
	build_scheme(company)
	measure()
	frappe.db.commit()


def undo() -> None:
	print("\nRemoving Phase 7 fixtures")
	print("-" * 72)

	# Payouts and achievements first, then the plans they hang off, deepest first - a parent plan
	# whose children still stand refuses to be cancelled.
	for doctype, filters in (
		("FieldMate Incentive Payout", {"scheme": SCHEME_NAME}),
		("FieldMate Achievement", {}),
		("FieldMate Target Plan", {"plan_name": PLAN_NAME}),
		("FieldMate Incentive Scheme", {"name": SCHEME_NAME}),
	):
		names = frappe.get_all(doctype, filters=filters, pluck="name")
		if doctype == "FieldMate Target Plan":
			# Children before parents.
			names.sort(key=lambda n: 0 if frappe.db.get_value(doctype, n, "parent_plan") else 1)
		removed = 0
		for name in names:
			try:
				doc = frappe.get_doc(doctype, name)
				if doc.meta.is_submittable and doc.docstatus == 1:
					doc.flags.ignore_permissions = True
					doc.cancel()
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
				removed += 1
			except Exception as e:
				note("kept", f"{doctype} {name}", str(e)[:50])
		if removed:
			note("removed", f"{removed} {doctype}")

	# Settings, Sales Person links and field users are left alone. The Sales Person tree may be
	# the site's real one, and unlinking a rep from it would undo somebody's configuration rather
	# than this script's.
	note("kept", "Settings, Sales Person tree and field user links",
	     "they may be the site's own")
	frappe.db.commit()


def show_state() -> None:
	print("\nState")
	print("-" * 72)

	settings = frappe.get_single("FieldMate Settings")
	print(f"  travel rate / km      {settings.travel_rate_per_km or '(not set)'}")
	print(f"  food allowance        {settings.daily_food_allowance or '(not set)'}")
	print(f"  distance tolerance    {settings.expense_distance_tolerance_pct or 0}%")

	linked = frappe.db.count("FieldMate Field User",
	                         {"status": "Active", "sales_person": ["is", "set"]})
	total = frappe.db.count("FieldMate Field User", {"status": "Active"})
	print(f"  reps on the tree      {linked} of {total}")

	roots = frappe.get_all("FieldMate Target Plan",
	                       filters={"is_root": 1, "docstatus": 1},
	                       fields=["name", "plan_name", "from_date", "to_date", "child_count"])
	print(f"  root target plans     {len(roots)}")
	for row in roots:
		print(f"      {row.name}  {row.plan_name}  {row.from_date} to {row.to_date}"
		      f"  ({row.child_count} children)")

	print(f"  leaf plans            "
	      f"{frappe.db.count('FieldMate Target Plan', {'docstatus': 1, 'field_user': ['is', 'set']})}")
	print(f"  achievements          {frappe.db.count('FieldMate Achievement')}")
	print(f"  incentive schemes     {frappe.db.count('FieldMate Incentive Scheme', {'docstatus': 1})}")
	print(f"  payouts               {frappe.db.count('FieldMate Incentive Payout')}")
	print(f"  expense claims        {frappe.db.count('FieldMate Expense Claim')}")

	if not UNDO and roots:
		print("\n  On the phone: Today -> My performance, and Today -> Claim expenses\n")


def main() -> None:
	run_setup(SITE, build=build, undo=undo, show_state=show_state,
	          undo_flag=UNDO, show_flag=SHOW)


if __name__ == "__main__":
	main()
