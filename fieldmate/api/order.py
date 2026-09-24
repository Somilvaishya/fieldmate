"""Order endpoints.

Every one of these resolves the rep from the session and never from a parameter. A device that
could name its own `field_user` could book orders onto a colleague, and the phone has no reason
to know that id in the first place — it learns it at login and we ignore it if it sends it back.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import field_user as field_user_service
from fieldmate.services import order as order_service


def _me() -> str:
	me = field_user_service.for_user()
	if not me:
		raise FieldMateError(Err.PERMISSION_DENIED,
		                     "You are not set up as a field user yet. Ask your manager.")
	return me


@frappe.whitelist()
@endpoint()
def estimate(outlet: str, lines=None, payment_term: str | None = None):
	"""Price a cart without recording anything.

	The phone calls this only when it has a signal. With none it runs the same arithmetic locally
	through its own copy of the engine, and the two are required to agree to the paise.
	"""
	return ok(order_service.estimate(outlet, parse_json(lines, "lines") or [], _me(), payment_term))


@frappe.whitelist(methods=["POST"])
@endpoint()
def submit(payload=None):
	"""Record the order and commit it in one call, which is how the rep experiences it.

	Kept as one endpoint on purpose: a phone that created a draft and then lost signal before
	committing would leave an order nobody fulfils and nobody can see. There is no state between
	the two worth exposing.
	"""
	data = parse_json(payload, "payload") or {}
	created = order_service.create(data, _me())
	return ok(order_service.submit_order(created["name"]))


@frappe.whitelist()
@endpoint()
def list_mine(limit: int = 50):
	return ok({"orders": order_service.mine(_me(), int(limit or 50))})


@frappe.whitelist()
@endpoint()
def detail(order: str):
	doc = frappe.get_doc("FieldMate Order", order)
	order_service.assert_owner(doc)
	return ok(order_service.summarise(doc))


@frappe.whitelist(methods=["POST"])
@endpoint()
def cancel(order: str, reason: str | None = None):
	return ok(order_service.cancel(order, reason))


@frappe.whitelist(methods=["POST"])
@endpoint()
def approve(order: str, decision: str, remarks: str | None = None):
	"""A manager's decision on a breached order. The service refuses self-approval."""
	return ok(order_service.approve(order, decision, remarks))


@frappe.whitelist()
@endpoint()
def queue(distributor: str, status: str | None = None):
	"""A distributor's order queue — the other end of ADR-023.

	Not a rep-facing call. It is here so the Phase 9 portal and the Desk list view read the same
	shape, rather than each growing its own query.
	"""
	return ok({"orders": order_service.for_distributor(distributor, status)})
