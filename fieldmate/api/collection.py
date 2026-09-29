"""Collection endpoints.

Every one resolves the rep from the session. A device that could name its own `field_user` could
declare a colleague's cash deposited.

Note what is **not** here: nothing a rep calls posts anything. `confirm` is the only endpoint that
reaches the ledger, and it refuses the person who declared the deposit (ADR-025, Gate 6
criterion 2).
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import collection as collection_service
from fieldmate.services import field_user as field_user_service


def _me() -> str:
	me = field_user_service.for_user()
	if not me:
		raise FieldMateError(Err.PERMISSION_DENIED,
		                     "You are not set up as a field user yet. Ask your manager.")
	return me


@frappe.whitelist()
@endpoint()
def outstanding(outlet: str):
	"""What this shop owes, the bills behind it, and how old they are."""
	return ok(collection_service.outstanding_for(outlet, _me()))


@frappe.whitelist(methods=["POST"])
@endpoint()
def create(payload=None):
	"""Record money taken at a counter. Posts nothing, whoever it came from."""
	return ok(collection_service.create(parse_json(payload, "payload") or {}, _me()))


@frappe.whitelist()
@endpoint()
def list_mine(status: str | None = None, limit: int = 50):
	return ok({"collections": collection_service.mine(_me(), status, int(limit or 50))})


@frappe.whitelist()
@endpoint()
def distributors():
	"""The depots this rep can take money from. Needed before they can take any."""
	return ok({"distributors": collection_service.distributors_for(_me())})


@frappe.whitelist()
@endpoint()
def in_hand():
	"""What the rep is still carrying, and since when."""
	return ok(collection_service.undeposited(_me()))


@frappe.whitelist(methods=["POST"])
@endpoint()
def deposit(payload=None):
	"""The rep declaring where the money went. Still posts nothing."""
	return ok(collection_service.declare_deposit(parse_json(payload, "payload") or {}, _me()))


@frappe.whitelist(methods=["POST"])
@endpoint()
def confirm(deposit: str):
	"""Somebody at our end confirming the money arrived — the only path to the ledger.

	Not a rep-facing call. The service refuses the person who declared it, and a Field Rep holds
	no permission on Payment Entry in the first place.
	"""
	if not frappe.has_permission("FieldMate Collection Deposit", "write"):
		raise FieldMateError(Err.PERMISSION_DENIED, "You cannot confirm deposits.")
	return ok(collection_service.confirm_deposit(deposit))


@frappe.whitelist(methods=["POST"])
@endpoint()
def bounce(collection: str, reason: str | None = None):
	"""A cheque came back. Restores whatever it appeared to settle."""
	if not frappe.has_permission("FieldMate Collection", "write"):
		raise FieldMateError(Err.PERMISSION_DENIED, "You cannot mark a collection bounced.")
	return ok(collection_service.bounce(collection, reason))
