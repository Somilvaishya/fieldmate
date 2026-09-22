"""Opening and closing a rep's working day.

A day is the frame every other field record hangs off: visits, orders and collections all belong
to one. So the rules here are about making sure exactly one day is open at a time, and that
closing it records what actually happened rather than what was typed.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, time_diff_in_hours

from fieldmate import compat
from fieldmate.services import field_user as field_user_service
from fieldmate.services import files as file_service
from fieldmate.services import journey as journey_service
from fieldmate.services import settings as settings_service
from fieldmate.services import trail as trail_service


def current(field_user: str) -> dict | None:
	"""The open day, if there is one.

	Called on every app boot: a rep who kills the app mid-morning must come back to the same day
	rather than starting a second one.
	"""
	name = frappe.db.get_value(
		"FieldMate Day Start",
		{"field_user": field_user, "status": "Open", "docstatus": 1},
		"name",
	)
	if not name:
		return None

	doc = frappe.get_doc("FieldMate Day Start", name)
	return {
		"day_start": doc.name,
		"day_date": str(doc.day_date),
		"started_at": str(doc.start_time),
		"planned_beat": doc.planned_beat,
		"journey_plan": doc.journey_plan,
		"is_mock_location": bool(doc.is_mock_location),
	}


def start(field_user: str, payload: dict) -> dict:
	"""Open the day. Idempotent — a second call returns the day already open."""
	open_day = current(field_user)
	if open_day:
		return {**open_day, "created": False}

	today = getdate(payload.get("day_date") or now_datetime())

	# A day already closed today cannot be reopened by starting again; that would split one
	# day's work across two records and double-count coverage.
	closed = frappe.db.exists(
		"FieldMate Day Start",
		{"field_user": field_user, "day_date": today, "status": ["in", ("Closed", "Auto Closed")],
		 "docstatus": 1},
	)
	if closed:
		raise frappe.ValidationError(
			frappe._("You have already finished today. Ask your manager if you need it reopened.")
		)

	settings = settings_service.get()
	if cint(settings.get("require_day_start_selfie")) and not payload.get("selfie"):
		raise frappe.ValidationError(frappe._("Take the start-of-day photo before you begin."))

	planned = journey_service.day_for(field_user, today) or {}

	doc = frappe.get_doc({
		"doctype": "FieldMate Day Start",
		"field_user": field_user,
		"day_date": today,
		"start_time": payload.get("start_time") or now_datetime(),
		"status": "Open",
		"latitude": payload.get("latitude"),
		"longitude": payload.get("longitude"),
		"accuracy_m": payload.get("accuracy_m"),
		"is_mock_location": cint(payload.get("is_mock_location")),
		"location_provider": payload.get("location_provider"),
		"odometer_start": payload.get("odometer_start"),
		"device_id": payload.get("device_id"),
		"journey_plan": planned.get("journey_plan"),
		"planned_beat": planned.get("beat"),
		"client_uuid": payload.get("client_uuid"),
		"created_offline": cint(payload.get("created_offline")),
	})
	doc.insert(ignore_permissions=True)

	# The photo arrives as a base64 data URL and has to become a real private file: the field
	# holds a path, not an image. Saved after the insert so it attaches to a document that
	# exists, and before submit so the record is complete when it is finalised.
	selfie = file_service.attach_photo(
		payload.get("selfie"),
		filename=f"day-start-{doc.name}",
		doctype="FieldMate Day Start",
		name=doc.name,
		fieldname="selfie",
		max_kb=settings.get("photo_max_kb"),
	)
	if selfie:
		doc.selfie = selfie
		doc.save(ignore_permissions=True)

	doc.submit()

	mirror_to_hrms(doc, "IN")

	return {
		"day_start": doc.name,
		"day_date": str(doc.day_date),
		"started_at": str(doc.start_time),
		"planned_beat": doc.planned_beat,
		"journey_plan": doc.journey_plan,
		"is_mock_location": bool(doc.is_mock_location),
		"created": True,
	}


def end(field_user: str, payload: dict) -> dict:
	"""Close the day and record what it produced."""
	open_day = current(field_user)
	if not open_day:
		raise frappe.ValidationError(frappe._("No day is open. Start your day first."))

	start_doc = frappe.get_doc("FieldMate Day Start", open_day["day_start"])

	existing = frappe.db.get_value("FieldMate Day End", {"day_start": start_doc.name}, "name")
	if existing:
		return {"day_end": existing, "created": False}

	end_time = payload.get("end_time") or now_datetime()
	counts = day_counts(field_user, start_doc.day_date)

	doc = frappe.get_doc({
		"doctype": "FieldMate Day End",
		"day_start": start_doc.name,
		"end_time": end_time,
		"latitude": payload.get("latitude"),
		"longitude": payload.get("longitude"),
		"accuracy_m": payload.get("accuracy_m"),
		"odometer_end": payload.get("odometer_end"),
		"duration_hours": round(
			flt(time_diff_in_hours(get_datetime(end_time), get_datetime(start_doc.start_time))), 2
		),
		"distance_km": trail_service.distance_for(field_user, start_doc.day_date),
		"client_uuid": payload.get("client_uuid"),
		"created_offline": cint(payload.get("created_offline")),
		"remarks": payload.get("remarks"),
		**counts,
	})
	doc.insert(ignore_permissions=True)
	doc.submit()

	start_doc.db_set("status", "Closed", update_modified=False)
	mirror_to_hrms(start_doc, "OUT", timestamp=end_time, day_end=doc.name,
	               latitude=doc.latitude, longitude=doc.longitude)
	write_attendance_summary(field_user, start_doc, doc)

	return {"day_end": doc.name, "created": True, "duration_hours": doc.duration_hours,
	        "distance_km": doc.distance_km, **counts}


def day_counts(field_user: str, date) -> dict:
	"""What the day produced, read from the records rather than from the phone.

	Visits, orders and collections arrive in Phases 3, 4 and 6; until then these are zero rather
	than absent, so Day End has a stable shape from the start.
	"""
	counts = {
		"planned_visits": 0,
		"actual_visits": 0,
		"productive_visits": 0,
		"orders_count": 0,
		"order_value": 0.0,
		"collection_amount": 0.0,
		"new_outlets": 0,
	}

	planned = journey_service.day_for(field_user, date)
	if planned:
		counts["planned_visits"] = cint(planned.get("outlet_count"))

	if frappe.db.table_exists("FieldMate Visit"):
		counts["actual_visits"] = frappe.db.count(
			"FieldMate Visit", {"field_user": field_user, "visit_date": date, "docstatus": 1}
		)
		counts["productive_visits"] = frappe.db.count(
			"FieldMate Visit",
			{"field_user": field_user, "visit_date": date, "docstatus": 1,
			 "visit_outcome": "Order Taken"},
		)

	counts["new_outlets"] = frappe.db.count(
		"FieldMate Outlet",
		{"created_by_rep": field_user, "onboarding_date": getdate(date)},
	)

	if counts["planned_visits"]:
		counts["coverage_pct"] = round(
			100.0 * counts["actual_visits"] / counts["planned_visits"], 2
		)
	return counts


def mirror_to_hrms(day_start, log_type: str, timestamp=None, day_end: str | None = None,
                   latitude=None, longitude=None) -> str | None:
	"""Mirror the day into HRMS attendance when HRMS is installed.

	Coordinates are passed in rather than read off the Day Start, because an OUT log happens
	wherever the rep finished — often a different town. Recording the morning's position on the
	evening's checkin would quietly tell HR that everyone ends where they began.

	Absent HRMS this is a no-op by design — FieldMate must run on a bench that has no HR module,
	and a missing mirror is not a reason to refuse a rep their day.
	"""
	employee = frappe.db.get_value("FieldMate Field User", day_start.field_user, "employee")
	if not employee:
		return None

	name = compat.create_employee_checkin(
		employee=employee,
		log_type=log_type,
		timestamp=timestamp or day_start.start_time,
		latitude=day_start.latitude if latitude is None else latitude,
		longitude=day_start.longitude if longitude is None else longitude,
		device_id=day_start.device_id,
	)
	if not name:
		return None

	target = frappe.get_doc("FieldMate Day End", day_end) if day_end else day_start
	target.db_set("employee_checkin", name, update_modified=False)
	return name


def write_attendance_summary(field_user: str, start_doc, end_doc) -> str:
	"""One row per rep per day, so attendance reporting never scans day records."""
	alert_time = settings_service.value("day_start_alert_time")
	late = False
	if alert_time:
		try:
			late = get_datetime(start_doc.start_time).time() > frappe.utils.get_time(alert_time)
		except Exception:
			late = False

	existing = frappe.db.get_value(
		"FieldMate Attendance Summary",
		{"field_user": field_user, "summary_date": start_doc.day_date},
		"name",
	)
	doc = (
		frappe.get_doc("FieldMate Attendance Summary", existing)
		if existing
		else frappe.new_doc("FieldMate Attendance Summary")
	)

	doc.update({
		"field_user": field_user,
		"summary_date": start_doc.day_date,
		"status": "Present",
		"is_late_start": cint(late),
		"start_time": start_doc.start_time,
		"end_time": end_doc.end_time,
		"working_hours": end_doc.duration_hours,
		"distance_km": end_doc.distance_km,
		"planned_visits": end_doc.planned_visits,
		"actual_visits": end_doc.actual_visits,
		"productive_visits": end_doc.productive_visits,
		"coverage_pct": end_doc.coverage_pct,
		"day_start": start_doc.name,
		"day_end": end_doc.name,
	})
	doc.save(ignore_permissions=True)
	return doc.name


def auto_close_stale_days() -> int:
	"""Close days a rep forgot to end, so tomorrow can start cleanly.

	Scheduled. The day is marked Auto Closed rather than Closed so the difference stays visible:
	a forgotten day is not the same as a finished one, and coverage figures should not pretend
	otherwise.
	"""
	hours = cint(settings_service.value("auto_close_day_after_hours")) or 14
	cutoff = frappe.utils.add_to_date(now_datetime(), hours=-hours)

	names = frappe.get_all(
		"FieldMate Day Start",
		filters={"status": "Open", "docstatus": 1, "start_time": ["<", cutoff]},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value("FieldMate Day Start", name, "status", "Auto Closed",
		                    update_modified=False)
	if names:
		frappe.db.commit()
	return len(names)
