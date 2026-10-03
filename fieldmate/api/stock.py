"""Stock endpoints: what a shop holds, and what a distributor reports selling.

Every one of these resolves the rep from the session. A device that could name its own
`field_user` could file a count against a colleague.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import field_user as field_user_service
from fieldmate.services import secondary_sales as secondary_service
from fieldmate.services import stock as stock_service


def _me() -> str:
	me = field_user_service.for_user()
	if not me:
		raise FieldMateError(Err.PERMISSION_DENIED,
		                     "You are not set up as a field user yet. Ask your manager.")
	return me


@frappe.whitelist()
@endpoint()
def sheet(outlet: str):
	"""Every SKU this shop could hold, and what it held last time."""
	return ok(stock_service.sheet_for(outlet, _me()))


@frappe.whitelist(methods=["POST"])
@endpoint()
def save(payload=None):
	return ok(stock_service.save_count(parse_json(payload, "payload") or {}, _me()))


@frappe.whitelist(methods=["POST"])
@endpoint()
def secondary_sales_upload(distributor: str, content=None, from_date=None, to_date=None,
                           file_name=None, mapping=None):
	"""A distributor's secondary sales file.

	Not a rep-facing call — this runs from Desk or the Phase 9 portal. It is here rather than in
	its own module because the permission story is identical and splitting it would mean two
	places to keep the envelope in step.
	"""
	if not frappe.has_permission("FieldMate Secondary Sales", "create"):
		raise FieldMateError(Err.PERMISSION_DENIED, "You cannot upload secondary sales.")

	return ok(secondary_service.import_file(
		distributor,
		content,
		from_date,
		to_date,
		file_name=file_name,
		overrides=parse_json(mapping, "mapping") or None,
	))
