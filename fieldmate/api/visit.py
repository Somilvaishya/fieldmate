"""The visit: check in, do the work, check out.

Thin controllers over `fieldmate.services.visit`. Every one of these is called from a phone that
may lose signal mid-call, so each is idempotent on a client-supplied id: replaying a check-in
returns the visit it already made rather than creating a second one.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import field_user as field_user_service
from fieldmate.services import visit as visit_service


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
def check_in(device_uuid: str | None = None, _device=None, **kwargs):
	"""Arrive at a shop. Idempotent on client_uuid."""
	payload = parse_json(kwargs.get("payload"), "payload") or kwargs
	payload.setdefault("device_id", _device.name)
	return ok(visit_service.check_in(_me(), payload))


@frappe.whitelist()
@endpoint()
def current(**kwargs):
	"""The visit in progress, if the app was killed and reopened inside a shop."""
	open_one = visit_service.open_visit(_me())
	return ok({"open": bool(open_one), **(open_one or {})})


@frappe.whitelist(methods=["POST"])
@endpoint()
def save_tasks(visit: str | None = None, **kwargs):
	"""Save checklist answers and task progress mid-visit.

	Called repeatedly while the rep works, so nothing is lost if they walk out of coverage
	halfway through the form.
	"""
	if not visit:
		raise FieldMateError(Err.BAD_REQUEST, "Which visit?")
	payload = parse_json(kwargs.get("payload"), "payload") or kwargs
	return ok(visit_service.save_tasks(visit, payload))


@frappe.whitelist(methods=["POST"])
@endpoint(require_device=True)
def upload_photo(visit: str | None = None, device_uuid: str | None = None, _device=None, **kwargs):
	"""Attach one photo, out of band from the visit itself.

	Photos are the heaviest thing the app sends. Keeping them on their own call means a shelf
	shot crawling up a 2G link never holds the check-out hostage.
	"""
	if not visit:
		raise FieldMateError(Err.BAD_REQUEST, "Which visit?")
	payload = parse_json(kwargs.get("payload"), "payload") or kwargs
	return ok(visit_service.add_photo(visit, payload))


@frappe.whitelist(methods=["POST"])
@endpoint(require_device=True)
def check_out(visit: str | None = None, device_uuid: str | None = None, _device=None, **kwargs):
	"""Leave the shop, recording what came of the visit."""
	if not visit:
		raise FieldMateError(Err.BAD_REQUEST, "Which visit?")
	payload = parse_json(kwargs.get("payload"), "payload") or kwargs
	return ok(visit_service.check_out(visit, payload))


@frappe.whitelist()
@endpoint()
def history(date: str | None = None, limit: int = 50, **kwargs):
	"""A day's visits, for the app's home screen."""
	return ok({"visits": visit_service.history(_me(), date or frappe.utils.today(), limit)})


@frappe.whitelist()
@endpoint()
def forms(**kwargs):
	"""Every live checklist template with its questions, for the phone to cache.

	The sync registry pulls templates as flat rows, and a template without its questions is an
	empty form. A rep in a basement market has to be able to open the survey, so the whole
	definition is fetched here and kept locally until it changes.
	"""
	templates = []
	for name in frappe.get_all("FieldMate Checklist Template",
	                           filters={"is_active": 1}, pluck="name"):
		doc = frappe.get_cached_doc("FieldMate Checklist Template", name)
		templates.append({
			"name": doc.name,
			"template_name": doc.template_name,
			"version": doc.version,
			"applies_to": doc.applies_to,
			"effective_from": str(doc.effective_from) if doc.effective_from else None,
			"territory": doc.territory,
			"channel": doc.channel,
			"outlet_class": doc.outlet_class,
			"beat": doc.beat,
			"questions": [
				{
					"question_code": q.question_code,
					"question": q.question,
					"answer_type": q.answer_type,
					"options": [o.strip() for o in (q.options or "").splitlines() if o.strip()],
					"is_required": bool(q.is_required),
					"sequence": q.sequence,
					"depends_on_code": q.depends_on_code,
					"depends_on_value": q.depends_on_value,
					"min_value": q.min_value,
					"max_value": q.max_value,
					"help_text": q.help_text,
					"photo_required": bool(q.photo_required),
				}
				for q in sorted(doc.questions, key=lambda r: (r.sequence or 0))
			],
		})

	return ok({"templates": templates})


@frappe.whitelist()
@endpoint()
def no_order_reasons(**kwargs):
	"""The reasons a rep may pick when no order came of a visit.

	Sent as a master so the sheet works offline - a rep standing in a shop with no signal still
	has to be able to say why.
	"""
	rows = frappe.get_all(
		"FieldMate No Order Reason",
		filters={"is_active": 1},
		fields=["name", "reason", "category", "requires_note", "counts_as_productive"],
		order_by="category asc, reason asc",
		limit_page_length=0,
	)
	for row in rows:
		row["requires_note"] = bool(row["requires_note"])
		row["counts_as_productive"] = bool(row["counts_as_productive"])
	return ok({"reasons": rows})
