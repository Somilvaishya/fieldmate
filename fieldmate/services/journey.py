"""Journey plans: turning a set of beats into a month of days.

A beat says "Sharma's route, Mondays, every week". A journey plan turns that into actual dates,
minus holidays and approved leave, so a rep opens the app and sees today's shops rather than a
rule they have to apply themselves.

The generator is deliberately boring and repeatable: given the same beats, holidays and leave it
produces the same plan. Anything that varies between runs would make a plan impossible to check.
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, cint, date_diff, getdate, now_datetime

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def week_of_month(date) -> int:
	"""1-4 (5 collapses into 4).

	A 'W1' beat means the first visit cycle of the month, not the calendar week number, which is
	what a planner means when they write it on a whiteboard.
	"""
	day = getdate(date).day
	return min(((day - 1) // 7) + 1, 4)


def beats_for(field_user: str) -> list[dict]:
	return frappe.get_all(
		"FieldMate Beat",
		filters={"assigned_to": field_user, "is_active": 1},
		fields=["name", "beat_name", "visit_day", "frequency", "week_pattern", "outlet_count"],
		order_by="beat_name",
	)


def holidays_between(holiday_list: str | None, from_date, to_date) -> set:
	if not holiday_list:
		return set()
	rows = frappe.get_all(
		"Holiday",
		filters={"parent": holiday_list, "holiday_date": ["between", [from_date, to_date]]},
		fields=["holiday_date"],
	)
	return {getdate(r.holiday_date) for r in rows}


def leave_dates(field_user: str, from_date, to_date) -> set:
	"""Approved leave only. A pending application is not yet a reason to skip a day.

	Silent when HRMS is absent, which is a normal state rather than an error.
	"""
	if not frappe.db.table_exists("Leave Application"):
		return set()

	employee = frappe.db.get_value("FieldMate Field User", field_user, "employee")
	if not employee:
		return set()

	dates = set()
	for row in frappe.get_all(
		"Leave Application",
		filters={
			"employee": employee,
			"status": "Approved",
			"docstatus": 1,
			"from_date": ["<=", to_date],
			"to_date": [">=", from_date],
		},
		fields=["from_date", "to_date"],
	):
		current = max(getdate(row.from_date), getdate(from_date))
		last = min(getdate(row.to_date), getdate(to_date))
		while current <= last:
			dates.add(current)
			current = add_days(current, 1)
	return dates


def beat_runs_on(beat: dict, date) -> bool:
	"""Does this beat fall on this date?"""
	if WEEKDAYS[getdate(date).weekday()] != beat["visit_day"]:
		return False

	frequency = beat.get("frequency") or "Weekly"
	if frequency == "Weekly":
		return True

	pattern = beat.get("week_pattern") or "All"
	if pattern == "All":
		# Fortnightly with no pattern means alternate cycles; anchor on odd weeks so two
		# fortnightly beats on the same day do not silently collide every week.
		return week_of_month(date) % 2 == 1 if frequency == "Fortnightly" else week_of_month(date) == 1

	return f"W{week_of_month(date)}" == pattern


def build_days(field_user: str, from_date, to_date, holiday_list: str | None = None) -> list[dict]:
	"""One row per calendar date in the window, each already resolved to a beat or a reason."""
	from_date, to_date = getdate(from_date), getdate(to_date)
	if date_diff(to_date, from_date) < 0:
		raise ValueError("to_date is before from_date")

	beats = beats_for(field_user)
	holidays = holidays_between(holiday_list, from_date, to_date)
	on_leave = leave_dates(field_user, from_date, to_date)

	days, current = [], from_date
	while current <= to_date:
		row = {
			"plan_date": current,
			"day_of_week": WEEKDAYS[current.weekday()],
			"week_of_month": week_of_month(current),
			"is_working_day": 1,
			"status": "Planned",
			"beat": None,
			"outlet_count": 0,
		}

		# Leave wins over a holiday: a rep on leave during a holiday is on leave, and the
		# attendance record should say so.
		if current in on_leave:
			row.update(status="Leave", is_working_day=0)
		elif current in holidays:
			row.update(status="Holiday", is_working_day=0)
		else:
			match = next((b for b in beats if beat_runs_on(b, current)), None)
			if match:
				row["beat"] = match["name"]
				row["outlet_count"] = cint(match.get("outlet_count"))
			else:
				# A working day with no beat is left Planned and empty on purpose: it is a gap
				# in the route design, and hiding it would hide the gap.
				row["note"] = "No beat scheduled"

		days.append(row)
		current = add_days(current, 1)

	return days


def generate(field_user: str, from_date, to_date, holiday_list: str | None = None,
             submit: bool = False) -> str:
	"""Create a journey plan for the window. Replaces any existing draft for the same window."""
	existing = frappe.db.get_value(
		"FieldMate Journey Plan",
		{"field_user": field_user, "from_date": getdate(from_date),
		 "to_date": getdate(to_date), "docstatus": 0},
		"name",
	)
	if existing:
		frappe.delete_doc("FieldMate Journey Plan", existing, force=True, ignore_permissions=True)

	if not holiday_list:
		employee = frappe.db.get_value("FieldMate Field User", field_user, "employee")
		if employee and frappe.db.has_column("Employee", "holiday_list"):
			holiday_list = frappe.db.get_value("Employee", employee, "holiday_list")

	doc = frappe.get_doc({
		"doctype": "FieldMate Journey Plan",
		"field_user": field_user,
		"from_date": getdate(from_date),
		"to_date": getdate(to_date),
		"holiday_list": holiday_list,
		"days": build_days(field_user, from_date, to_date, holiday_list),
		"generated_on": now_datetime(),
		"generated_by": frappe.session.user,
	})
	doc.insert(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc.name


def day_for(field_user: str, date) -> dict | None:
	"""What is planned for this rep on this date, from a submitted plan."""
	date = getdate(date)
	plan = frappe.db.get_value(
		"FieldMate Journey Plan",
		{"field_user": field_user, "from_date": ["<=", date], "to_date": [">=", date],
		 "docstatus": 1},
		["name", "holiday_list"],
		as_dict=True,
	)
	if not plan:
		return None

	row = frappe.db.get_value(
		"FieldMate Journey Plan Day",
		{"parent": plan.name, "plan_date": date},
		["name", "beat", "status", "outlet_count", "day_of_week", "is_working_day"],
		as_dict=True,
	)
	if not row:
		return None

	row["journey_plan"] = plan.name
	return row
