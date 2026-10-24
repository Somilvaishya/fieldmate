"""Outlet endpoints. Thin — everything real lives in fieldmate.services.outlet."""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import importer as importer_service
from fieldmate.services import outlet as outlet_service
from fieldmate.services import paging


@frappe.whitelist()
@endpoint()
def search(q: str | None = None, beat: str | None = None, limit: int = 50, start: int = 0,
           **kwargs):
	"""Territory-scoped outlet search, for reps whose patch is too big to mirror.

	The one list on this app that genuinely runs to thousands - Gate 1 imports five thousand
	shops - so it is the one where a cap with no page was most obviously a dead end.
	"""
	start, limit = paging.window(start, limit)
	rows = outlet_service.search(query=q, beat=beat, limit=limit, start=start)
	return ok({"outlets": rows,
	           **paging.envelope(rows, outlet_service.count_search(query=q, beat=beat),
	                             start, limit)})


@frappe.whitelist()
@endpoint()
def detail(outlet: str | None = None, **kwargs):
	"""Outlet 360: profile, contacts, credit, and whether an order can be taken."""
	if not outlet:
		raise FieldMateError(Err.BAD_REQUEST, "Which outlet?")
	try:
		return ok(outlet_service.detail(outlet))
	except frappe.DoesNotExistError as e:
		raise FieldMateError(Err.BAD_REQUEST, "That shop no longer exists.") from e


@frappe.whitelist(methods=["POST"])
@endpoint()
def create(**kwargs):
	"""Onboard a shop from the field. Always lands unapproved."""
	payload = parse_json(kwargs.get("payload"), "payload") or kwargs
	if not payload.get("outlet_name"):
		raise FieldMateError(Err.BAD_REQUEST, "Enter the shop name.")
	if not payload.get("mobile_no"):
		raise FieldMateError(Err.BAD_REQUEST, "Enter a mobile number for the shop.")
	return ok(outlet_service.create(payload))


@frappe.whitelist(methods=["POST"])
@endpoint()
def update(outlet: str | None = None, **kwargs):
	"""Correct details a rep can see from the doorstep."""
	if not outlet:
		raise FieldMateError(Err.BAD_REQUEST, "Which outlet?")
	payload = parse_json(kwargs.get("payload"), "payload") or kwargs
	return ok(outlet_service.update(outlet, payload))


@frappe.whitelist(methods=["POST"])
@endpoint()
def approve(outlet: str | None = None, decision: str | None = None,
            notes: str | None = None, **kwargs):
	"""A manager's decision on a shop a rep onboarded."""
	if not outlet:
		raise FieldMateError(Err.BAD_REQUEST, "Which outlet?")
	try:
		return ok(outlet_service.approve(outlet, decision, notes))
	except ValueError as e:
		raise FieldMateError(Err.BAD_REQUEST, str(e)) from e


# --------------------------------------------------------------------------------------
# Bulk import — Desk and admin tooling, never the field app
# --------------------------------------------------------------------------------------


@frappe.whitelist()
@endpoint()
def import_template(**kwargs):
	return ok(importer_service.outlet_template())


@frappe.whitelist(methods=["POST"])
@endpoint()
def bulk_import(rows: str | None = None, dry_run: int = 1, **kwargs):
	"""Validate a file and optionally write it. Defaults to a dry run on purpose."""
	if not frappe.has_permission("FieldMate Outlet", "create"):
		raise FieldMateError(Err.PERMISSION_DENIED, "You cannot import outlets.")

	parsed = parse_json(rows, "rows") or []
	if not isinstance(parsed, list):
		raise FieldMateError(Err.BAD_REQUEST, "rows must be a list.")

	return ok(importer_service.import_outlets(parsed, dry_run=bool(int(dry_run))))
