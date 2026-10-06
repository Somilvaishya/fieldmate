"""Schemes: what is on offer at this shop, and what this cart actually comes to.

Two calls that look similar and are not. `applicable` hands the phone the compiled specs so it
can price a cart at a counter with no signal at all - that answer is what the rep says out loud.
`evaluate` is the server running the same specs over server prices, and that is the figure of
record. `docs/SCHEME_SPEC.md` allows the two no divergence, so where they differ it is a bug in
one of the two evaluators and nowhere else, which is the whole point of compiling the spec once.

Both resolve the rep from the session. Neither takes a field user.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import field_user as field_user_service
from fieldmate.services import scheme_compile as scheme_service


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
def applicable(outlet: str | None = None, party_type: str | None = None, **kwargs):
	"""The compiled specs for this shop, for the phone to cache and evaluate offline.

	`skipped` comes back alongside them. A scheme that could not be compiled is one a manager
	has to fix, and a payload that dropped it in silence would leave the offer looking live in
	Desk and absent in the field for as long as nobody happened to notice.
	"""
	if not outlet:
		raise FieldMateError(Err.BAD_REQUEST, "Which outlet?")

	try:
		return ok(scheme_service.for_outlet(outlet, _me(), party_type=party_type))
	except frappe.DoesNotExistError as e:
		raise FieldMateError(Err.BAD_REQUEST, "That shop no longer exists.") from e


@frappe.whitelist(methods=["POST"])
@endpoint()
def evaluate(outlet: str | None = None, lines: str | None = None,
             party_type: str | None = None, **kwargs):
	"""What this cart comes to, worked out on the server. Reads only; nothing is booked.

	A POST because the cart travels in the body rather than because anything is written. No
	FieldMate Order, no Sales Order, no GL entry - a retailer order is a secondary sale and is
	terminal in our books (ADR-023), and this call is a quotation for a rep to read.

	Each line is `{"item_code": ..., "qty": ..., "uom": ...}`. The rates are ours, not the
	phone's: the phone's total is kept beside the order as what the rep promised, and checked.
	"""
	if not outlet:
		raise FieldMateError(Err.BAD_REQUEST, "Which outlet?")

	cart = parse_json(lines, "lines") or []
	if not isinstance(cart, list):
		raise FieldMateError(Err.BAD_REQUEST, "lines must be a list.")

	try:
		return ok(scheme_service.evaluate_for(outlet, _me(), cart, party_type=party_type))
	except frappe.DoesNotExistError as e:
		raise FieldMateError(Err.BAD_REQUEST, "That shop no longer exists.") from e
