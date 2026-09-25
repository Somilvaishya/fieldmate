"""The working day, and the beat a rep walks through it.

Thin controllers over `fieldmate.services.day`, `.journey` and `.trail`.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json, readable
from fieldmate.services import day as day_service
from fieldmate.services import field_user as field_user_service
from fieldmate.services import journey as journey_service
from fieldmate.services import trail as trail_service


def _me() -> str:
	field_user = field_user_service.for_user()
	if not field_user:
		raise FieldMateError(
			Err.PERMISSION_DENIED,
			"Your account is not set up as a field user yet. Ask your manager.",
		)
	return field_user


@frappe.whitelist(methods=["POST"])
@endpoint(require_device=True)
def start(device_uuid: str | None = None, _device=None, **kwargs):
	"""Open the day: GPS fix, selfie, odometer. Idempotent."""
	payload = parse_json(kwargs.get("payload"), "payload") or kwargs
	payload.setdefault("device_id", _device.name)
	try:
		return ok(day_service.start(_me(), payload))
	except frappe.ValidationError as e:
		# readable() exists so a framework message never reaches a rep; str(e) bypassed it.
		raise FieldMateError(Err.VALIDATION_FAILED, readable(e)) from e


@frappe.whitelist()
@endpoint()
def current(**kwargs):
	"""Resume an open day after an app restart or a device swap."""
	field_user = _me()
	open_day = day_service.current(field_user)
	if not open_day:
		return ok({"open": False, "planned": journey_service.day_for(field_user, frappe.utils.today())})
	return ok({"open": True, **open_day})


@frappe.whitelist()
@endpoint()
def summary(date: str | None = None, **kwargs):
	"""What the day has produced so far, without closing it.

	The Finish Day screen shows a rep what they are about to commit to. It reads the same
	figures `end()` writes, so the screen cannot show one number and the record keep another.
	"""
	return ok(day_service.summary(_me(), date))


@frappe.whitelist(methods=["POST"])
@endpoint(require_device=True)
def end(device_uuid: str | None = None, _device=None, **kwargs):
	"""Close the day and record what it produced."""
	payload = parse_json(kwargs.get("payload"), "payload") or kwargs
	try:
		return ok(day_service.end(_me(), payload))
	except frappe.ValidationError as e:
		# readable() exists so a framework message never reaches a rep; str(e) bypassed it.
		raise FieldMateError(Err.VALIDATION_FAILED, readable(e)) from e


@frappe.whitelist(methods=["POST"])
@endpoint(require_device=True)
def trail_upload(device_uuid: str | None = None, pings: str | None = None,
                 _device=None, **kwargs):
	"""Append a batch of GPS pings to today's trail.

	Batched rather than per-ping: a phone uploading every 90 seconds would cost more battery in
	radio wake-ups than the pings themselves.
	"""
	parsed = parse_json(pings, "pings") or []
	if not isinstance(parsed, list):
		raise FieldMateError(Err.BAD_REQUEST, "pings must be a list.")
	if len(parsed) > 2000:
		raise FieldMateError(Err.BAD_REQUEST, "Too many pings in one upload.")

	field_user = _me()
	open_day = day_service.current(field_user)
	return ok(trail_service.append(
		field_user=field_user,
		pings=parsed,
		day_start=open_day["day_start"] if open_day else None,
		device_id=_device.name,
	))


# --------------------------------------------------------------------------------------
# Journey plan
# --------------------------------------------------------------------------------------


@frappe.whitelist()
@endpoint()
def today(**kwargs):
	"""Today's beat and its outlets, in visit order."""
	field_user = _me()
	planned = journey_service.day_for(field_user, frappe.utils.today()) or {}

	outlets = []
	if planned.get("beat"):
		outlets = beat_outlets(planned["beat"])

	return ok({
		"date": frappe.utils.today(),
		"status": planned.get("status"),
		"beat": planned.get("beat"),
		"journey_plan": planned.get("journey_plan"),
		"is_working_day": bool(planned.get("is_working_day", 1)),
		"outlets": outlets,
	})


@frappe.whitelist()
@endpoint()
def my_beats(**kwargs):
	"""Every route assigned to this rep, soonest first, with when each next runs."""
	return ok({"beats": journey_service.my_beats(_me())})


@frappe.whitelist()
@endpoint()
def outlets(beat: str | None = None, **kwargs):
	"""Every outlet on a beat, for offline prefetch."""
	if not beat:
		raise FieldMateError(Err.BAD_REQUEST, "Which beat?")
	if not frappe.has_permission("FieldMate Beat", "read", doc=beat):
		raise FieldMateError(Err.PERMISSION_DENIED, "That beat is not yours.")
	return ok({"beat": beat, "outlets": beat_outlets(beat)})


def beat_outlets(beat: str) -> list[dict]:
	"""Outlets on a beat in walking order, with what a check-in decision needs."""
	rows = frappe.get_all(
		"FieldMate Beat Outlet",
		filters={"parent": beat},
		fields=["outlet", "sequence", "expected_duration_min", "is_mandatory"],
		order_by="sequence asc",
		limit_page_length=0,
	)
	if not rows:
		return []

	# get_list, not get_all. `frappe.get_all` forces ignore_permissions=True and discards any
	# value passed for it, so the territory filter the loop below relies on never ran and
	# every shop on the beat came back regardless of who asked. Same defect Gate 1 found in
	# sync.pull; `user` is what actually applies this rep's territory.
	details = {
		o.name: o
		for o in frappe.get_list(
			"FieldMate Outlet",
			filters={"name": ["in", [r.outlet for r in rows]]},
			fields=["name", "outlet_name", "city", "mobile_no", "latitude", "longitude",
			        "geo_fence_radius_m", "approval_status", "outlet_status", "outlet_class"],
			limit_page_length=0,
			user=frappe.session.user,
		)
	}

	out = []
	for row in rows:
		detail = details.get(row.outlet)
		if not detail:
			# Outside this rep's territory, so not theirs to see. Skipped rather than surfaced
			# as a broken row on a phone.
			continue
		out.append({**detail, "sequence": row.sequence,
		            "expected_duration_min": row.expected_duration_min,
		            "is_mandatory": bool(row.is_mandatory)})
	return out
