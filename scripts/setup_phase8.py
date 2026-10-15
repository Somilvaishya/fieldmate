"""Seed everything the Phase 8 manual test needs, in one command.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase8.py
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase8.py --undo
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase8.py --show

Every chart, card and screen in Phase 8 reads `FieldMate KPI Snapshot`, and that table is empty
until something rolls it up. So a site that has all the Phase 8 code and has never run the job
shows a dashboard of zeros - which is correct, and looks exactly like a bug.

This rolls up whatever the site already has. It invents no visits and no orders: a dashboard
over made-up data proves nothing about the site it runs on, and the numbers on the screen have
to be ones a person can go and check against the documents behind them.

Safe to run twice: the rollup rewrites rows rather than adding them.
"""

import sys
import time

import frappe
from frappe.utils import add_days, getdate, nowdate

from _guard import run_setup

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
	if not arg.startswith("--"):
		SITE = arg

UNDO = "--undo" in sys.argv
SHOW = "--show" in sys.argv

# How far back to roll up. Ninety days is enough for a month view to have a previous month
# beside it, and short enough to finish while somebody is watching.
DAYS = 90


def note(verb: str, what: str, detail: str = "") -> None:
	print(f"  {verb:8} {what}" + (f"   ({detail})" if detail else ""))


def build() -> None:
	from fieldmate.services import alerts as alerts_service
	from fieldmate.services import kpi as kpi_service

	print("\nBuilding Phase 8 fixtures")
	print("-" * 72)

	made = alerts_service.install_starter_rules()
	note("created" if made else "kept", f"{made or 5} alert rule(s)",
	     "the five exceptions" if made else "already there")

	reps = frappe.get_all("FieldMate Field User", filters={"status": "Active"},
	                      fields=["name", "full_name"])
	if not reps:
		print("\n  !! No active field users on this site, so there is nothing to roll up.\n")
		return

	to_date = getdate(nowdate())
	from_date = add_days(to_date, -(DAYS - 1))
	note("rolling", f"{len(reps)} rep(s)", f"{from_date} to {to_date}")

	started = time.time()
	written = unchanged = 0
	for rep in reps:
		result = kpi_service.roll_up_range(rep.name, from_date, to_date)
		written += result["written"]
		unchanged += result["unchanged"]
		frappe.db.commit()
	seconds = time.time() - started

	note("wrote", f"{written} rep-day row(s)",
	     f"{unchanged} already current · {seconds:.1f}s")

	# The alerts read the rows that were just written, so they run second. The other way round
	# would judge the period on whatever the table held before.
	outcome = alerts_service.evaluate_all(days_back=min(DAYS, 30))
	note("evaluated", f"{outcome['rules']} rule(s)",
	     f"{outcome['fired']} fired, {outcome['already_logged']} already logged")

	frappe.db.commit()


def undo() -> None:
	print("\nRemoving Phase 8 fixtures")
	print("-" * 72)

	for doctype in ("FieldMate Alert Log", "FieldMate KPI Snapshot"):
		names = frappe.get_all(doctype, pluck="name")
		for name in names:
			try:
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			except Exception:
				pass
		if names:
			note("removed", f"{len(names)} {doctype}")
		frappe.db.commit()

	# Alert rules are left alone. A site may have tuned a threshold, and this script did not
	# create the ones it found.
	note("kept", "alert rules", "a site may have tuned them")


def show_state() -> None:
	from fieldmate.setup import insights as insights_setup

	print("\nState")
	print("-" * 72)

	rows = frappe.db.count("FieldMate KPI Snapshot")
	print(f"  snapshot rows         {rows}")
	if rows:
		span = frappe.db.sql("""
			select min(snapshot_date), max(snapshot_date),
			       count(distinct field_user), sum(order_value)
			from `tabFieldMate KPI Snapshot`
		""")[0]
		print(f"      {span[0]} to {span[1]} · {span[2]} rep(s) · "
		      f"{float(span[3] or 0):,.0f} booked")

	print(f"  alert rules           {frappe.db.count('FieldMate Alert Rule')} "
	      f"({frappe.db.count('FieldMate Alert Rule', {'is_active': 1})} active)")
	print(f"  alerts logged         {frappe.db.count('FieldMate Alert Log')}")

	for doctype, label in (("Dashboard Chart", "charts"), ("Number Card", "cards"),
	                       ("Report", "reports"), ("Workspace", "workspaces")):
		names = frappe.get_all(doctype, filters={"module": "FieldMate"}, pluck="name")
		print(f"  {label:21} {len(names)}  {names if len(names) < 6 else ''}")

	state = insights_setup.report()
	print(f"  insights on this site {state['installed_on_site']}"
	      + ("" if state["installed_on_site"]
	         else "   (so setup/insights.py has only ever been seen to no-op)"))

	if not UNDO and rows:
		print("\n  Desk: the FieldMate workspace. Phone: Today -> How today is going\n")


def main() -> None:
	run_setup(SITE, build=build, undo=undo, show_state=show_state,
	          undo_flag=UNDO, show_flag=SHOW)


if __name__ == "__main__":
	main()
