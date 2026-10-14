"""Opening and closing a rep's working day.

A day is the frame every other field record hangs off: visits, orders and collections all belong
to one. So the rules here are about making sure exactly one day is open at a time, and that
closing it records what actually happened rather than what was typed.
"""

from __future__ import annotations

import frappe
from frappe.utils import (
	cint,
	flt,
	get_datetime,
	getdate,
	now_datetime,
	time_diff_in_hours,
	time_diff_in_seconds,
	today,
)

from fieldmate import compat
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

	# A day belongs to its date. An Open record from an earlier date is a day the rep forgot to
	# end, and handing it back is not harmless: `start` is idempotent on this answer, so the rep
	# gets yesterday back with `created: False`, and `visit.check_in` takes `visit_date` from it -
	# so today's visits, orders and collections all land on yesterday's day and yesterday's date.
	# Coverage, attendance and the day counts are wrong from the first check-in and nothing on the
	# screen says so.
	#
	# `close_stale_days` is scheduled to catch this and cannot be the guarantee: it waits out
	# `auto_close_day_after_hours`, so a day started in the evening is still Open the next
	# morning - and on a site whose scheduler is not running it never fires at all, which is how
	# this was found. Closed here, in the one read every caller goes through, so the answer is
	# right whether or not a cron ever ran.
	if getdate(doc.day_date) != getdate(today()):
		auto_close_day(doc)
		return None

	return {
		"day_start": doc.name,
		"day_date": str(doc.day_date),
		"started_at": str(doc.start_time),
		"planned_beat": doc.planned_beat,
		# The name, not only the id. A rep reads "South Market", not "FM-BEAT-0003", and
		# without this the home screen showed them the document id all day.
		"planned_beat_name": frappe.db.get_value(
			"FieldMate Beat", doc.planned_beat, "beat_name"
		) if doc.planned_beat else None,
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
	# A Field Rep holds create and read on their own records, never write or submit - that is
	# deliberate (ADR-004), and it is what keeps generic endpoints like frappe.client.save
	# closed to them. The server submits on their behalf once it has checked who is asking,
	# exactly as it does when posting a Sales Order. Without this a rep could not start a day
	# at all; every gate passed only because it ran as Administrator.
	doc.flags.ignore_permissions = True

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

	adopt_open_visits(field_user, doc)
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
	doc = _record_day_end(field_user, start_doc, end_time, counts, payload)

	start_doc.db_set("status", "Closed", update_modified=False)
	mirror_to_hrms(start_doc, "OUT", timestamp=end_time, day_end=doc.name,
	               latitude=doc.latitude, longitude=doc.longitude)
	write_attendance_summary(field_user, start_doc, doc)

	return {"day_end": doc.name, "created": True, "duration_hours": doc.duration_hours,
	        "distance_km": doc.distance_km, **counts}


def adopt_open_visits(field_user: str, start_doc) -> list[str]:
	"""Move a visit the rep is still in onto the day that has just opened.

	`auto_close_day` leaves a visit checked in today alone, because the rep is standing in that
	shop. That leaves it pointing at a day which is now closed and carrying the wrong date - so
	the day that opens next adopts it, and the visit the rep walks out of is filed under the day
	they walked it in.

	Only visits checked in today, and only while they are still open. Anything older was closed
	with its own day.
	"""
	if not frappe.db.table_exists("FieldMate Visit"):
		return []

	adopted = []
	for row in frappe.get_all(
		"FieldMate Visit",
		filters={"field_user": field_user, "check_out_time": ["is", "not set"], "docstatus": 0},
		fields=["name", "check_in_time", "day_start"],
	):
		if not row.check_in_time or getdate(row.check_in_time) != getdate(start_doc.day_date):
			continue
		if row.day_start == start_doc.name:
			continue
		frappe.db.set_value("FieldMate Visit", row.name, {
			"day_start": start_doc.name,
			"visit_date": start_doc.day_date,
		}, update_modified=False)
		frappe.clear_document_cache("FieldMate Visit", row.name)
		adopted.append(row.name)
	return adopted


def _record_day_end(field_user: str, start_doc, end_time, counts: dict, payload: dict):
	"""The Day End document itself, written the same way however the day came to be over.

	Shared by `end` and `auto_close_day` on purpose. A day the rep forgot to end used to be
	closed by flipping a status and nothing else - no Day End, so no counts, no distance, no
	attendance and no OUT in HRMS. The record of a forgotten day was a day that produced nothing,
	which is not what happened.
	"""
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
	# See the note in start(): a rep holds no submit right of their own (ADR-004).
	doc.flags.ignore_permissions = True
	doc.submit()
	return doc


def last_activity(field_user: str, start_doc):
	"""When the day actually stopped, as far as anything recorded knows.

	Closing a forgotten day at `now` would book a twenty-hour day and an attendance row to match.
	Nobody knows when the rep stopped, so the latest thing the day produced stands in for it, and
	the day's own start time stands in when it produced nothing at all. A figure that is visibly
	the last check-out is better than one that is confidently wrong.
	"""
	stamps = [get_datetime(start_doc.start_time)]
	if frappe.db.table_exists("FieldMate Visit"):
		for row in frappe.get_all(
			"FieldMate Visit",
			filters={"field_user": field_user, "visit_date": start_doc.day_date},
			fields=["check_in_time", "check_out_time"],
		):
			stamps += [get_datetime(v) for v in (row.check_in_time, row.check_out_time) if v]
	return max(stamps)


def auto_close_day(start_doc) -> str | None:
	"""Close a day the rep never ended, as completely as they would have.

	Marked `Auto Closed` rather than `Closed`: a forgotten day is not a finished one and coverage
	figures should not pretend otherwise. Everything else is the real closing - the visit still
	open on it, the Day End with the day's counts, the OUT in HRMS and the attendance summary -
	because a day left half-closed is what made today's work land on yesterday's record.
	"""
	# Imported here, not at the top: `visit` imports this module, so a module-level import is a
	# cycle.
	from fieldmate.services import visit as visit_service

	field_user = start_doc.field_user
	if frappe.db.table_exists("FieldMate Visit"):
		for row in frappe.get_all(
			"FieldMate Visit",
			filters={"field_user": field_user, "visit_date": start_doc.day_date,
			         "check_out_time": ["is", "not set"]},
			fields=["name", "check_in_time"],
		):
			# A visit checked in TODAY is one the rep is standing in, even though it is filed
			# under this stale day - which is exactly what the bug above produced. Closing it
			# would end a live visit from under them, mid-shop, and that is not a tidy-up.
			#
			# Read from `check_in_time`, not `visit_date`: `visit_date` is the field the bug
			# corrupted, so it is the one thing here that cannot be trusted. `start` adopts
			# whatever is left open onto the new day.
			if row.check_in_time and getdate(row.check_in_time) == getdate(today()):
				continue
			visit_service.auto_close(row.name)

	existing = frappe.db.get_value("FieldMate Day End", {"day_start": start_doc.name}, "name")
	if not existing:
		end_time = last_activity(field_user, start_doc)
		counts = day_counts(field_user, start_doc.day_date)
		doc = _record_day_end(field_user, start_doc, end_time, counts, {
			"remarks": frappe._("Closed automatically - the day was never ended."),
		})
		existing = doc.name
		mirror_to_hrms(start_doc, "OUT", timestamp=end_time, day_end=doc.name)
		write_attendance_summary(field_user, start_doc, doc)

	start_doc.db_set("status", "Auto Closed", update_modified=False)
	return existing


def day_counts(field_user: str, date) -> dict:
	"""What the day produced, read from the records rather than from the phone.

	Visits, orders and collections arrive in Phases 3, 4 and 6; until then these are zero rather
	than absent, so Day End has a stable shape from the start.
	"""
	counts = {
		"planned_visits": 0,
		"actual_visits": 0,
		"planned_covered": 0,
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
		# Coverage is about the route, so it counts only shops that were on it. Counting
		# every visit let a rep read 100% coverage on a card that was, two lines below,
		# naming the planned shops they had not been to.
		counts["planned_covered"] = frappe.db.count(
			"FieldMate Visit",
			{"field_user": field_user, "visit_date": date, "docstatus": 1, "is_planned": 1},
		)
		counts["productive_visits"] = frappe.db.count(
			"FieldMate Visit",
			{"field_user": field_user, "visit_date": date, "docstatus": 1,
			 "visit_outcome": "Order Taken"},
		)

	# Orders arrived in Phase 4. Read from the records like everything else here, because a
	# phone that spent the day with no signal cannot know which of its orders finally landed -
	# and a Day End that reports the phone's count rather than the server's is the figure a rep
	# argues about at month end.
	if frappe.db.table_exists("FieldMate Order"):
		booked = frappe.get_all(
			"FieldMate Order",
			filters={"field_user": field_user, "order_date": getdate(date), "docstatus": 1},
			fields=["net_total"],
		)
		counts["orders_count"] = len(booked)
		counts["order_value"] = sum(flt(row.net_total) for row in booked)

	counts["new_outlets"] = frappe.db.count(
		"FieldMate Outlet",
		{"created_by_rep": field_user, "onboarding_date": getdate(date)},
	)

	if counts["planned_visits"]:
		counts["coverage_pct"] = round(
			100.0 * min(counts["planned_covered"], counts["planned_visits"])
			/ counts["planned_visits"], 2
		)
	return counts


def summary(field_user: str, date=None) -> dict:
	"""What the day has produced so far, without ending it.

	The Finish Day screen shows a rep what they are about to close. Everything here is read
	from the records, never from the phone - the same figures `end()` will write, so the
	screen cannot promise one thing and the Day End record say another.
	"""
	date = getdate(date or today())
	open_day = current(field_user)
	counts = day_counts(field_user, date)
	planned = journey_service.day_for(field_user, date) or {}

	measured = trail_service.measure(field_user, date)

	minutes = None
	if open_day and open_day.get("started_at"):
		minutes = max(0, round(
			time_diff_in_seconds(now_datetime(), get_datetime(open_day["started_at"])) / 60.0
		))

	return {
		"date": str(date),
		"open": bool(open_day),
		"day_start": open_day["day_start"] if open_day else None,
		"started_at": open_day["started_at"] if open_day else None,
		"minutes_on_route": minutes,
		"beat": planned.get("beat"),
		"beat_name": planned.get("beat_name"),
		"distance_km": round(measured["km"], 1),
		# "trail", "route", or nothing measured. The day end screen names the figure's source,
		# and a route figure captioned "from your GPS trail" is a claim about data that is not
		# there - the app only reports its position while it is open.
		"distance_basis": measured["basis"],
		"pending_shops": pending_shops(field_user, date, planned.get("beat")),
		**counts,
	}


def pending_shops(field_user: str, date, beat: str | None) -> list[dict]:
	"""Shops on today's route that have no submitted visit yet.

	Named, not counted. "2 shops pending" tells a rep nothing they can act on in the ten
	minutes before they close the day; "Gupta Traders, New Star Stores" does.
	"""
	if not beat:
		return []

	rows = frappe.get_all(
		"FieldMate Beat Outlet", filters={"parent": beat},
		fields=["outlet", "sequence"], order_by="sequence asc", limit_page_length=0,
	)
	if not rows:
		return []

	visited = set(frappe.get_all(
		"FieldMate Visit",
		filters={"field_user": field_user, "visit_date": getdate(date), "docstatus": 1},
		pluck="outlet",
	))
	missing = [r for r in rows if r.outlet not in visited]
	if not missing:
		return []

	names = {
		o.name: o.outlet_name
		for o in frappe.get_all(
			"FieldMate Outlet", filters={"name": ["in", [r.outlet for r in missing]]},
			fields=["name", "outlet_name"], limit_page_length=0,
		)
	}
	return [
		{"outlet": r.outlet, "outlet_name": names.get(r.outlet, r.outlet), "sequence": r.sequence}
		for r in missing
	]


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
	# The same closing `current` does, not a status flip. This used to set the field and stop,
	# which left the visit still open on the day, no Day End at all, and no OUT in HRMS.
	for name in names:
		auto_close_day(frappe.get_doc("FieldMate Day Start", name))
	if names:
		frappe.db.commit()
	return len(names)
