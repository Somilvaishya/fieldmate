"""The order screen's two reads. Thin - everything real lives in fieldmate.services.catalogue.

Both of these resolve the rep from the **session**. Neither takes a field user as an argument,
and neither would honour one: a device that could name a rep could read another rep's shops,
another rep's prices and another rep's order history, and a stolen phone is the ordinary way that
happens rather than the exotic one.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import catalogue as catalogue_service
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
def items(outlet: str | None = None, **kwargs):
	"""Everything this shop may be sold, priced, plus what it ordered last time.

	The repeat-order prefill rides along rather than taking a call of its own. The cart screen
	needs both before it can draw anything, and a second round trip on a market uplink is a
	second chance for the rep to give up on it.

	Note the price list is not a parameter. A phone that could name its own price list could
	quote the whole cart off whichever one is cheapest.
	"""
	if not outlet:
		raise FieldMateError(Err.BAD_REQUEST, "Which outlet?")

	me = _me()
	try:
		payload = catalogue_service.for_outlet(outlet, me)
		payload["last_order"] = catalogue_service.last_order_for(outlet, me)
	except frappe.DoesNotExistError as e:
		raise FieldMateError(Err.BAD_REQUEST, "That shop no longer exists.") from e

	return ok(payload)


@frappe.whitelist()
@endpoint()
def prices(outlet: str | None = None, items: str | None = None, **kwargs):
	"""Fresh rates for a cart that already exists, and nothing else.

	`items` is a list of `{"item_code": ..., "qty": ...}`, the quantity in base units - the
	phone already holds the conversion factor from `catalogue.items`. Bare item codes work too.
	"""
	if not outlet:
		raise FieldMateError(Err.BAD_REQUEST, "Which outlet?")

	lines = parse_json(items, "items") or []
	if not isinstance(lines, list):
		raise FieldMateError(Err.BAD_REQUEST, "items must be a list.")

	try:
		return ok(catalogue_service.prices_for(outlet, lines, _me()))
	except frappe.DoesNotExistError as e:
		raise FieldMateError(Err.BAD_REQUEST, "That shop no longer exists.") from e
