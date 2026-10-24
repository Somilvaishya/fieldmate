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
from fieldmate.services import paging
from fieldmate.services import portal as portal_service


def _me() -> str:
	me = field_user_service.for_user()
	if not me:
		raise FieldMateError(Err.PERMISSION_DENIED,
		                     "You are not set up as a field user yet. Ask your manager.")
	return me


@frappe.whitelist()
@endpoint()
def estimate(outlet: str, lines=None, payment_term: str | None = None,
             party_type: str | None = None):
	"""Price a cart without recording anything.

	The phone calls this only when it has a signal. With none it runs the same arithmetic locally
	through its own copy of the engine, and the two are required to agree to the paise.
	"""
	return ok(order_service.estimate(outlet, parse_json(lines, "lines") or [], _me(),
	                                 payment_term, party_type=party_type))


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
def list_mine(limit: int = 50, start: int = 0):
	"""This rep's orders, a page at a time.

	`orders` keeps its name and its type: `api/_base` holds the envelope to additive changes
	because old builds stay in the field for weeks, and one that has never heard of `start` reads
	the first page exactly as it always did. The counts arrive beside it.
	"""
	me = _me()
	start, limit = paging.window(start, limit)
	rows = order_service.mine(me, limit=limit, start=start)
	return ok({"orders": rows,
	           **paging.envelope(rows, order_service.count_mine(me), start, limit)})


@frappe.whitelist()
@endpoint()
def bookings(limit: int = 50):
	"""This rep's season bookings, with what each one still needs up front.

	Its own endpoint rather than a filter on `list_mine`, because the figures a booking is read
	for - the advance due, the advance arrived, the cheques held against it - are not on the order
	document at all. See `order_service.my_bookings`.
	"""
	return ok({"bookings": order_service.my_bookings(_me(), int(limit or 50))})


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
def queue(distributor: str | None = None, status: str | None = None):
	"""A distributor's order queue — the other end of ADR-023.

	Not a rep-facing call. It is here so the Phase 9 portal and the Desk list view read the same
	shape, rather than each growing its own query.

	**Who may ask, and for whom.** The depot named here used to come straight off the request and
	be handed to `for_distributor`, which runs `frappe.get_all` - and that forces
	`ignore_permissions=True`. So any signed-in session, including a rep or a rival depot, could
	read any distributor's whole order book by typing their name. The portal's own service layer
	has always scoped this properly; this endpoint simply went round it.

	A portal session now gets its own depot whatever it asks for. A manager may name any. Anyone
	else is refused.
	"""
	mine = portal_service.distributor_of()
	if mine:
		# Silently narrowed rather than refused on a mismatch: a depot asking for somebody else's
		# queue learns nothing from the answer, not even that the name they guessed exists.
		distributor = mine
	elif not set(frappe.get_roles()) & set(field_user_service.MANAGER_ROLES):
		raise FieldMateError(
			Err.PERMISSION_DENIED,
			"Only a distributor or a manager can open an order queue.",
		)

	if not distributor:
		raise FieldMateError(Err.BAD_REQUEST, "Which distributor's queue?")

	return ok({"orders": order_service.for_distributor(distributor, status)})
