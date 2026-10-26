"""The credit position for whoever an order is for.

The phone had one way to read credit - `outlet.detail` - and it takes an outlet. On a primary
order the party is a Customer, so that call could not answer, and the screen said **"No credit
limit is recorded for this distributor"** over a distributor with a fifty thousand rupee limit
sitting on their Customer record. Not knowing is not the same as there being nothing to know, and
the screen had no way to tell the two apart because nobody had ever asked the question.

`services/credit` has handled a Customer since it was written - `_party_level` branches on the
party type in its second line - and `order.submit` has used it on every primary order. This is
that answer, over HTTP, for the screen that quotes the number before the order exists.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok
from fieldmate.services import credit as credit_service
from fieldmate.services import field_user as field_user_service


def _me() -> str:
	field_user = field_user_service.for_user()
	if not field_user:
		raise FieldMateError(
			Err.PERMISSION_DENIED,
			"Your account is not set up as a field user yet. Ask your manager.",
		)
	return field_user


@frappe.whitelist()
@endpoint()
def position(party: str | None = None, party_type: str | None = None):
	"""What this party owes us today, and what they are allowed.

	Standing, with no order value in it: what a cart does to the position is arithmetic the phone
	does itself as quantities change, so that a rep at a counter is not waiting on a round trip
	between taps. The server answers what is owed today.

	Returned under `credit`, in the same shape `outlet.detail` returns, so the phone's reader
	handles both without knowing which call it came from.
	"""
	if not party:
		raise FieldMateError(Err.BAD_REQUEST, "Which party?")

	kind = party_type or "Customer"
	if kind == "Customer" and not frappe.db.exists("Customer", party):
		# Named plainly. The screen that calls this is about to quote a credit figure, and the
		# one thing it must not do is draw a blank as though it were a zero.
		raise FieldMateError(Err.BAD_REQUEST, "That party is not on this site any more.")

	return ok({"credit": credit_service.reading(party, _me(), kind)})
