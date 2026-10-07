"""Visits: checking in at a shop, doing the work, checking out.

This is the core loop and the highest-volume table in the system. Two principles run through it.

**Evidence is recomputed, never accepted.** Distance from the shop, fence breach, duration and
short-visit are all derived on the server from the shop's own pin and the server's clock. A device
that could set them could also fake a day's coverage, and coverage is what managers act on.

**Almost nothing is blocked in the field.** A check-in 400 m away is recorded and flagged, not
refused. A visit off the planned beat is recorded as a deviation. Blocking either would not produce
better data; it would produce a rep who stops using the app, and then there is no data at all. The
one exception is a required checklist answer at a shop that was actually open - the rep is standing
there and can answer, so asking is reasonable.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, time_diff_in_seconds

from fieldmate.services import day as day_service
from fieldmate.services import field_user as field_user_service
from fieldmate.services import files as file_service
from fieldmate.services import journey as journey_service
from fieldmate.services import scope
from fieldmate.services import settings as settings_service
from fieldmate.services.trail import haversine_km

# Outcomes where the shop was never open for business. A rep cannot answer questions about a
# shelf they could not see, so required answers are not demanded for these.
SHOP_NOT_OPEN = ("Outlet Closed", "Owner Absent")


# --------------------------------------------------------------------------- geo


class OpenVisitError(frappe.ValidationError):
	"""A check-in refused because the rep has not checked out of the last shop.

	Carries the open visit so the screen can offer the one thing that fixes it - a link back to
	that shop - rather than only naming it.
	"""

	def __init__(self, message, visit=None):
		super().__init__(message)
		self.visit = visit or {}


def geo_check(outlet_doc, latitude, longitude) -> dict:
	"""How far the check-in was from the shop, and whether that is outside its fence.

	A shop with no pin cannot be checked, which is a data gap rather than a breach - treating it
	as one would punish reps for a master nobody has filled in.
	"""
	radius = outlet_doc.effective_geo_fence_radius()
	no_shop_pin = not (flt(outlet_doc.latitude) and flt(outlet_doc.longitude))
	no_device_fix = latitude in (None, "") or longitude in (None, "")
	if no_shop_pin or no_device_fix:
		return {
			"distance_from_outlet_m": None,
			"is_geo_fence_breach": 0,
			"radius_m": radius,
			"unmeasurable": "shop has no pin" if no_shop_pin else "no gps fix",
		}

	metres = haversine_km(outlet_doc.latitude, outlet_doc.longitude, latitude, longitude) * 1000
	enforced = cint(settings_service.value("enforce_geo_fence"))
	fenced = cint(outlet_doc.enable_geo_fence)

	return {
		"distance_from_outlet_m": round(metres, 1),
		"is_geo_fence_breach": 1 if (enforced and fenced and metres > radius) else 0,
		"radius_m": radius,
		"unmeasurable": None,
	}


def raise_fence_exception(visit_doc, geo: dict) -> str | None:
	"""Open a pending exception so a breach lands in a queue rather than a report nobody runs."""
	if not cint(settings_service.value("allow_geo_fence_exception")):
		return None

	doc = frappe.get_doc({
		"doctype": "FieldMate Geo Fence Exception",
		"outlet": visit_doc.outlet,
		"field_user": visit_doc.field_user,
		"exception_date": visit_doc.visit_date,
		"status": "Pending",
		"distance_m": geo["distance_from_outlet_m"],
		"reason": frappe._("Raised automatically at check-in on visit {0}.").format(visit_doc.name),
		"latitude": visit_doc.check_in_latitude,
		"longitude": visit_doc.check_in_longitude,
		"accuracy_m": visit_doc.check_in_accuracy_m,
	})
	doc.insert(ignore_permissions=True)
	return doc.name


def minimum_minutes(outlet_doc) -> int:
	"""The shortest a visit to this shop should sensibly take.

	A large A-class outlet warrants longer than a tiny one, so the class overrides the global.
	"""
	if outlet_doc.outlet_class:
		per_class = frappe.db.get_value(
			"FieldMate Outlet Class", outlet_doc.outlet_class, "min_visit_duration_minutes"
		)
		if cint(per_class):
			return cint(per_class)
	return cint(settings_service.value("min_visit_duration_minutes"))


# --------------------------------------------------------------------------- checklists


def applicable_templates(outlet, field_user: str, visit_date) -> list:
	"""Active checklist templates whose scope matches this shop today.

	Scope matching lives in `services.scope`, which treats a territory as the tree it is - see
	the note there about why equality is the wrong comparison. Templates are read through the
	cache: the same handful apply to every visit all day.
	"""
	names = frappe.get_all(
		"FieldMate Checklist Template",
		filters={"is_active": 1, "effective_from": ["<=", getdate(visit_date)]},
		pluck="name",
	)
	matched = []
	for name in names:
		doc = frappe.get_cached_doc("FieldMate Checklist Template", name)
		if not scope.applies_to_outlet(doc, outlet):
			continue
		if doc.beat and not is_on_beat(doc.beat, outlet.name):
			continue
		if doc.applies_to == "New Outlet Only" and outlet.approval_status == "Approved":
			continue
		if doc.applies_to == "First Visit Of Month" and visited_this_month(
			outlet.name, field_user, visit_date
		):
			continue
		matched.append(doc)
	return matched


def visited_this_month(outlet: str, field_user: str, visit_date) -> bool:
	date = getdate(visit_date)
	return bool(frappe.db.count("FieldMate Visit", {
		"outlet": outlet,
		"field_user": field_user,
		"visit_date": ["between", [date.replace(day=1), date]],
		"docstatus": ["<", 2],
	}))


def build_checklist(outlet, field_user: str, visit_date) -> list[dict]:
	"""Snapshot the questions as they read today.

	The wording and the template version are copied onto the answer row. A template reworded next
	month must not change what a visit last month appears to have asked. Options, help text and
	branching rules are deliberately *not* copied - they are rendering concerns, and duplicating
	them across millions of answer rows would cost far more than it proves.
	"""
	rows = []
	for template in applicable_templates(outlet, field_user, visit_date):
		for question in sorted(template.questions, key=lambda q: cint(q.sequence)):
			rows.append({
				"question_code": question.question_code,
				"question": question.question,
				"answer_type": question.answer_type,
				"is_required": question.is_required,
				"sequence": question.sequence,
				"template": template.name,
				"template_version": template.version,
			})
	return rows


def question_spec(template: str, question_code: str) -> dict:
	"""The rendering rules for one question, read from its template."""
	if not template:
		return {}
	doc = frappe.get_cached_doc("FieldMate Checklist Template", template)
	for q in doc.questions:
		if q.question_code == question_code:
			return {
				"options": [o.strip() for o in (q.options or "").splitlines() if o.strip()],
				"depends_on_code": q.depends_on_code,
				"depends_on_value": q.depends_on_value,
				"min_value": flt(q.min_value) if q.min_value is not None else None,
				"max_value": flt(q.max_value) if q.max_value is not None else None,
				"help_text": q.help_text,
				"photo_required": bool(q.photo_required),
			}
	# The question was removed from the template after this visit snapshotted it. The answer
	# still stands; it simply renders without branching.
	return {}


# --------------------------------------------------------------------------- the visit


def open_visit(field_user: str) -> dict | None:
	"""The visit currently in progress, if any."""
	name = frappe.db.get_value(
		"FieldMate Visit",
		{"field_user": field_user, "check_out_time": ["is", "not set"], "docstatus": 0},
		"name",
	)
	return summarise(frappe.get_doc("FieldMate Visit", name)) if name else None


def check_in(field_user: str, payload: dict) -> dict:
	"""Start a visit. Idempotent on client_uuid."""
	client_uuid = payload.get("client_uuid")
	if client_uuid:
		existing = frappe.db.get_value("FieldMate Visit", {"client_uuid": client_uuid}, "name")
		if existing:
			return {**summarise(frappe.get_doc("FieldMate Visit", existing)), "created": False}

	outlet_name = payload.get("outlet")
	if not outlet_name:
		frappe.throw(frappe._("Which shop?"))

	# Read permission is what proves the shop is in this rep's territory.
	if not frappe.has_permission("FieldMate Outlet", "read", doc=outlet_name,
	                             user=frappe.session.user):
		raise frappe.PermissionError(frappe._("That shop is not in your territory."))

	day = day_service.current(field_user)
	if not day:
		frappe.throw(frappe._("Start your day before visiting a shop."))

	# An open visit elsewhere. This used to be closed, always and silently: one tap from the shop
	# list ended the visit the rep was standing in, stamped it "No Order" and short, and told
	# nobody. A rep could walk down a row of shops leaving a trail of empty visits that count
	# towards coverage. Checking out is the way a visit ends.
	#
	# It is refused rather than closed, but only for a check-in happening now. A visit created
	# offline already happened - the rep was in that shop - and refusing it when the queue lands
	# would delete real work, so those still close the stale one. `close_open_visit` is the
	# deliberate override, sent after the rep has been told on screen what it does.
	previous = open_visit(field_user)
	if previous:
		# Only another shop. Checking in again at the shop they are already in is a rep
		# re-opening the app or retrying a push, not walking off mid-visit.
		elsewhere = previous["outlet"] != outlet_name
		live = not cint(payload.get("created_offline"))
		if elsewhere and live and not cint(payload.get("close_open_visit")):
			shop = frappe.db.get_value("FieldMate Outlet", previous["outlet"],
			                           "outlet_name") or previous["outlet"]
			raise OpenVisitError(
				frappe._("You are still checked in at {0}. Check out from there first.")
				.format(shop),
				visit={**previous, "outlet_name": shop},
			)
		auto_close(previous["visit"])

	outlet = frappe.get_doc("FieldMate Outlet", outlet_name)
	visit_date = getdate(day["day_date"])
	latitude, longitude = payload.get("latitude"), payload.get("longitude")
	geo = geo_check(outlet, latitude, longitude)
	planned = journey_service.day_for(field_user, visit_date) or {}
	on_beat = bool(planned.get("beat")) and is_on_beat(planned["beat"], outlet_name)

	doc = frappe.get_doc({
		"doctype": "FieldMate Visit",
		"visit_date": visit_date,
		"outlet": outlet_name,
		"field_user": field_user,
		"beat": planned.get("beat"),
		"day_start": day["day_start"],
		"journey_plan": planned.get("journey_plan"),
		"visit_sequence": next_sequence(field_user, visit_date),
		"is_planned": 1 if on_beat else 0,
		"is_deviation": 0 if on_beat else 1,
		"deviation_reason": payload.get("deviation_reason"),
		"deviation_note": payload.get("deviation_note"),
		"check_in_time": payload.get("check_in_time") or now_datetime(),
		"check_in_latitude": latitude,
		"check_in_longitude": longitude,
		"check_in_accuracy_m": payload.get("accuracy_m"),
		"distance_from_outlet_m": geo["distance_from_outlet_m"],
		"is_geo_fence_breach": geo["is_geo_fence_breach"],
		"is_mock_location": cint(payload.get("is_mock_location")),
		"location_provider": payload.get("location_provider"),
		"client_uuid": client_uuid or frappe.generate_hash(length=32),
		"created_offline": cint(payload.get("created_offline")),
		"device_id": payload.get("device_id"),
		"app_version": payload.get("app_version"),
		"tasks": build_tasks(outlet),
		"checklist_answers": build_checklist(outlet, field_user, visit_date),
	})
	doc.insert(ignore_permissions=True)

	# Both of these need the visit's name, so they follow the insert.
	photo = file_service.attach_photo(
		payload.get("check_in_photo"), filename=f"checkin-{doc.name}",
		doctype="FieldMate Visit", name=doc.name, fieldname="check_in_photo",
		max_kb=settings_service.value("photo_max_kb"),
	)
	if photo:
		doc.db_set("check_in_photo", photo, update_modified=False)
	if geo["is_geo_fence_breach"]:
		exception = raise_fence_exception(doc, geo)
		if exception:
			doc.db_set("geo_fence_exception", exception, update_modified=False)

	return {
		**summarise(doc),
		"created": True,
		"geo": geo,
		"min_visit_minutes": minimum_minutes(outlet),
	}


def is_on_beat(beat: str, outlet: str) -> bool:
	return bool(frappe.db.exists("FieldMate Beat Outlet", {"parent": beat, "outlet": outlet}))


def next_sequence(field_user: str, date) -> int:
	return cint(frappe.db.count(
		"FieldMate Visit", {"field_user": field_user, "visit_date": getdate(date)}
	)) + 1


def build_tasks(outlet) -> list[dict]:
	"""What this visit is expected to include."""
	tasks = [
		{"task": frappe._("Check the shelf"), "task_type": "Merchandising", "is_mandatory": 0},
		{"task": frappe._("Count his stock"), "task_type": "Stock Audit", "is_mandatory": 0},
		{"task": frappe._("Collect what is due"), "task_type": "Collection", "is_mandatory": 0},
		{"task": frappe._("Take the order"), "task_type": "Order", "is_mandatory": 0},
	]
	if outlet.approval_status != "Approved":
		tasks.insert(0, {
			"task": frappe._("Shop is awaiting approval - no order yet"),
			"task_type": "Other", "status": "Skipped", "is_mandatory": 0,
		})
	return tasks


def save_tasks(visit: str, payload: dict) -> dict:
	"""Record checklist answers, task progress and remarks mid-visit.

	Called repeatedly as the rep works, so it must be safe to replay: every call overwrites the
	rows it is given and leaves the rest alone.
	"""
	doc = frappe.get_doc("FieldMate Visit", visit)
	assert_owner(doc)
	if doc.check_out_time:
		frappe.throw(frappe._("This visit is already finished."))

	answers = {a.get("question_code"): a for a in (payload.get("answers") or [])}
	for row in doc.checklist_answers:
		given = answers.get(row.question_code)
		if not given:
			continue
		has_text = given.get("answer") not in (None, "")
		has_number = given.get("answer_number") not in (None, "")
		row.answer = given.get("answer")
		row.answer_number = flt(given.get("answer_number")) if has_number else 0
		if has_text or has_number or given.get("photo"):
			row.is_answered = 1
		if given.get("photo"):
			row.photo = file_service.attach_photo(
				given["photo"], filename=f"chk-{doc.name}-{row.question_code}",
				doctype="FieldMate Visit", name=doc.name, fieldname="checklist_answers",
				max_kb=settings_service.value("photo_max_kb"),
			)

	statuses = {t.get("task"): t for t in (payload.get("tasks") or [])}
	for row in doc.tasks:
		given = statuses.get(row.task)
		if not given or not given.get("status"):
			continue
		row.status = given["status"]
		row.note = given.get("note") or row.note
		if row.status == "Done" and not row.completed_on:
			row.completed_on = now_datetime()

	if payload.get("remarks") is not None:
		doc.remarks = payload["remarks"]

	doc.save(ignore_permissions=True)
	return summarise(doc)


def add_photo(visit: str, payload: dict) -> dict:
	"""Attach a photo. Called out of band, so a slow upload never blocks the visit.

	The visit is very often already submitted by the time a photo arrives: records sync first
	and pictures follow, which is the whole reason they are on separate queues. The photos
	table is `allow_on_submit` for exactly this, and a cancelled visit is the one case where
	a late photo has nowhere sensible to go.
	"""
	doc = frappe.get_doc("FieldMate Visit", visit)
	assert_owner(doc)
	if doc.docstatus == 2:
		frappe.throw(frappe._("That visit was cancelled, so the photo cannot be attached."))

	client_uuid = payload.get("client_uuid")
	if client_uuid and any(p.client_uuid == client_uuid for p in doc.photos):
		return {"visit": doc.name, "photos": len(doc.photos), "duplicate": True}

	url = file_service.attach_photo(
		payload.get("photo"), filename=f"visit-{doc.name}-{len(doc.photos) + 1}",
		doctype="FieldMate Visit", name=doc.name, fieldname="photos",
		max_kb=settings_service.value("photo_max_kb"),
	)
	if not url:
		frappe.throw(frappe._("No photo was sent."))

	doc.append("photos", {
		"photo": url,
		"purpose": payload.get("purpose") or "Other",
		"caption": payload.get("caption"),
		"taken_at": payload.get("taken_at") or now_datetime(),
		"latitude": payload.get("latitude"),
		"longitude": payload.get("longitude"),
		"size_kb": cint(payload.get("size_kb")),
		"client_uuid": client_uuid,
	})
	doc.save(ignore_permissions=True)
	return {"visit": doc.name, "photos": len(doc.photos), "duplicate": False}


def check_out(visit: str, payload: dict) -> dict:
	"""Close the visit, recording the outcome and deriving duration."""
	doc = frappe.get_doc("FieldMate Visit", visit)
	assert_owner(doc)
	if doc.check_out_time:
		return {**summarise(doc), "created": False}

	outcome = payload.get("visit_outcome")
	if not outcome:
		frappe.throw(frappe._("What happened at this shop?"))

	# The check-out sheet can carry last answers and remarks, so fold them in before validating.
	if payload.get("answers") or payload.get("tasks") or payload.get("remarks") is not None:
		save_tasks(visit, payload)
		doc.reload()

	validate_outcome(doc, outcome, payload)
	if outcome not in SHOP_NOT_OPEN:
		assert_required_answers(doc)

	end = get_datetime(payload.get("check_out_time") or now_datetime())
	seconds = time_diff_in_seconds(end, get_datetime(doc.check_in_time))
	minutes = max(0, round(seconds / 60.0))
	outlet = frappe.get_doc("FieldMate Outlet", doc.outlet)

	doc.check_out_time = end
	doc.check_out_latitude = payload.get("latitude")
	doc.check_out_longitude = payload.get("longitude")
	doc.duration_minutes = minutes
	doc.is_short_visit = 1 if minutes < minimum_minutes(outlet) else 0
	doc.visit_outcome = outcome
	doc.no_order_reason = payload.get("no_order_reason")
	doc.next_visit_date = payload.get("next_visit_date")

	doc.save(ignore_permissions=True)
	# A rep holds create and read on their own visits, never submit (ADR-004). Ownership is
	# checked by assert_owner above; the server closes the visit on their behalf.
	doc.flags.ignore_permissions = True
	doc.submit()
	field_user_service.touch(frappe.session.user)
	return {**summarise(doc), "created": True}


def validate_outcome(doc, outcome: str, payload: dict) -> None:
	"""A visit with no order and no reason teaches nobody anything."""
	if outcome == "Order Taken":
		return

	reason = payload.get("no_order_reason")
	if not reason:
		frappe.throw(frappe._("Choose a reason for the missed order."))

	requires_note = frappe.db.get_value("FieldMate No Order Reason", reason, "requires_note")
	if cint(requires_note) and not (payload.get("remarks") or doc.remarks):
		frappe.throw(frappe._("This reason needs a note saying what actually happened."))


def assert_required_answers(doc) -> None:
	missing = [
		r.question for r in doc.checklist_answers
		if cint(r.is_required) and not cint(r.is_answered)
	]
	if missing:
		frappe.throw(frappe._("Answer these before you leave: {0}").format(", ".join(missing[:5])))


def auto_close(visit: str) -> None:
	"""Close a visit the rep walked away from, so the next check-in is not blocked.

	Required answers are not demanded here - the rep has already left, and refusing would strand
	them outside the next shop, which is the one thing this whole module is trying to avoid.
	"""
	doc = frappe.get_doc("FieldMate Visit", visit)
	if doc.check_out_time:
		return

	end = now_datetime()
	doc.check_out_time = end
	doc.duration_minutes = max(
		0, round(time_diff_in_seconds(end, get_datetime(doc.check_in_time)) / 60.0)
	)
	doc.is_short_visit = 1
	# Read from what the visit produced, not from what is on the field. `visit_outcome` is a
	# Select with options and no default, so it holds its first option - "Order Taken" - from the
	# moment the visit is inserted. `doc.visit_outcome or "No Order"` therefore never fired, and
	# every visit closed this way was recorded as a sale that was never made. `day_counts` counts
	# exactly that string as a productive visit, so a rep walking a row of shops without checking
	# out inflated their own productivity figure.
	doc.visit_outcome = "Order Taken" if took_an_order(doc) else "No Order"
	doc.remarks = ((doc.remarks or "") + "\n"
	               + frappe._("Closed automatically when the next visit began.")).strip()
	if doc.visit_outcome != "Order Taken" and not doc.no_order_reason:
		doc.no_order_reason = default_no_order_reason()
	doc.save(ignore_permissions=True)
	if doc.docstatus == 0:
		doc.flags.ignore_permissions = True
		doc.submit()


def took_an_order(doc) -> bool:
	"""Did this visit actually book something? Read from the orders, not from the visit."""
	if not frappe.db.table_exists("FieldMate Order"):
		return False
	return bool(frappe.db.exists("FieldMate Order", {"visit": doc.name, "docstatus": 1}))


def default_no_order_reason() -> str | None:
	return frappe.db.get_value("FieldMate No Order Reason", {"is_active": 1}, "name")


def assert_owner(doc) -> None:
	if doc.field_user == field_user_service.for_user():
		return
	if not frappe.has_permission("FieldMate Visit", "write", doc=doc.name):
		raise frappe.PermissionError(frappe._("This is not your visit."))


def history(field_user: str, date=None, limit: int = 50) -> list[dict]:
	"""A day's visits, for the app's home screen."""
	filters = {"field_user": field_user}
	if date:
		filters["visit_date"] = getdate(date)
	rows = frappe.get_list(
		"FieldMate Visit",
		filters=filters,
		fields=["name as visit", "outlet", "visit_date", "check_in_time", "check_out_time",
		        "duration_minutes", "visit_outcome", "is_planned", "is_deviation",
		        "is_geo_fence_breach", "is_short_visit", "visit_sequence"],
		order_by="check_in_time asc",
		limit_page_length=cint(limit),
		user=frappe.session.user,
	)
	for row in rows:
		row["check_in_time"] = str(row["check_in_time"]) if row["check_in_time"] else None
		row["check_out_time"] = str(row["check_out_time"]) if row["check_out_time"] else None
		row["visit_date"] = str(row["visit_date"])
	return rows


def summarise(doc) -> dict:
	"""Plain dict for the app. No document objects across the wire."""
	return {
		"visit": doc.name,
		"outlet": doc.outlet,
		"visit_date": str(doc.visit_date),
		"visit_sequence": cint(doc.visit_sequence),
		"checked_in_at": str(doc.check_in_time) if doc.check_in_time else None,
		"checked_out_at": str(doc.check_out_time) if doc.check_out_time else None,
		"duration_minutes": cint(doc.duration_minutes),
		"is_planned": bool(doc.is_planned),
		"is_deviation": bool(doc.is_deviation),
		"distance_from_outlet_m": (
			flt(doc.distance_from_outlet_m) if doc.distance_from_outlet_m is not None else None
		),
		"is_geo_fence_breach": bool(doc.is_geo_fence_breach),
		"geo_fence_exception": doc.geo_fence_exception,
		"is_short_visit": bool(doc.is_short_visit),
		"visit_outcome": doc.visit_outcome,
		"no_order_reason": doc.no_order_reason,
		"remarks": doc.remarks,
		"photos": len(doc.photos or []),
		"tasks": [
			{"task": t.task, "task_type": t.task_type, "status": t.status,
			 "is_mandatory": bool(t.is_mandatory), "note": t.note}
			for t in (doc.tasks or [])
		],
		"checklist": [
			{
				"question_code": a.question_code,
				"question": a.question,
				"answer_type": a.answer_type,
				"answer": a.answer,
				"answer_number": a.answer_number,
				"is_answered": bool(a.is_answered),
				"photo": a.photo,
				"is_required": bool(a.is_required),
				"sequence": cint(a.sequence),
				"template": a.template,
				"template_version": cint(a.template_version),
				**question_spec(a.template, a.question_code),
			}
			for a in sorted(doc.checklist_answers or [], key=lambda r: cint(r.sequence))
		],
	}
