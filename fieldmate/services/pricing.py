"""Which price list a shop is quoted from, and the one price that is not ours to exceed.

Two rules that several callers need and none of them should own. `catalogue` computes rates, the
scheme engine re-prices against them, `channel.resolve` reports which list a party buys on and
`order.create` refuses a cart it cannot stand behind - and all four have to agree about the
answer, so the answer lives here.

It lives here rather than in `catalogue` for a plain reason: `channel.resolve` needs the price
list, and `catalogue` will need `channel.resolve` the moment the order path moves onto it. One of
the two importing the other would be a cycle a step later.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

from fieldmate.services import settings as settings_service


def price_list_for(outlet_doc, field_user: str | None = None) -> str | None:
	"""Which list this shop is quoted from.

	The shop's own list first, because a modern-trade account is the whole reason that field
	exists. **Then its distributor's PTR list** - what the shops under that distributor pay, and
	the answer for the ordinary kirana that has no list of its own. Then the rep's, for a route
	selling off a different list to the same shops; then FieldMate's default; then what the
	company already told ERPNext to sell at.

	The order is specific-beats-general, and it matters in both directions. A list set on one
	shop was set for that shop; a PTR list was set for a whole tier. The other way round would
	quote the tier price at the one account that negotiated its own - which is the error that
	loses the argument with a modern-trade buyer.

	Never `frappe.defaults`: that answers with whatever price list the last Desk session touched
	and is silently wrong for every rep who has never opened Desk (ADR-020). Selling Settings at
	the end is a deliberate configuration rather than a session default, so it does not reopen
	the same hole; without it, every order on a site nobody had configured failed with "no price
	on None", a message that names the symptom and hides the cause, on the one screen where a
	rep is standing in front of a shopkeeper.
	"""
	if field_user is not None and not isinstance(field_user, str):
		raise TypeError(
			f"field_user must be a FieldMate Field User name, got {type(field_user).__name__}. "
			"Check the argument order at the call site."
		)

	if outlet_doc.get("price_list"):
		return outlet_doc.get("price_list")

	distributor = outlet_doc.get("distributor")
	if distributor:
		ptr = frappe.db.get_value("Customer", distributor, "fm_ptr_price_list")
		if ptr:
			return ptr

	if field_user:
		own = frappe.db.get_value("FieldMate Field User", field_user, "default_price_list")
		if own:
			return own

	ours = settings_service.value("default_price_list")
	if ours:
		return ours

	# `or None` because a Single's unset Data column reads back as "", and an empty string is
	# worse than nothing here: `compat.get_item_details` would go on to look for Item Price rows
	# on a price list named "", find none, and report every item as unpriced - which reads on the
	# phone as the catalogue being broken rather than as nobody having configured a price list.
	return frappe.db.get_single_value("Selling Settings", "selling_price_list") or None


def sells_to_us(customer: str | None) -> str | None:
	"""Which list we bill this party from. Theirs, not their shops'."""
	return frappe.db.get_value("Customer", customer, "default_price_list") if customer else None


# --------------------------------------------------------------------------------------
# MRP
# --------------------------------------------------------------------------------------


def is_above_mrp(rate, mrp) -> bool:
	"""Is this rate higher than the printed price on the pack?

	**Both figures are per stock UOM.** `rate` from `compat.get_item_details` is per base unit,
	and an MRP is printed on the consumer pack, which is what the stock UOM counts. A caller that
	has multiplied a rate up into cases must not compare that number here: a case of twelve at
	the right price would read as twelve times over the MRP and every line would be refused.

	A site that holds no MRP for an item answers False rather than refusing. `compat` probes the
	Item for an MRP column and sends None where there is none (see `MRP_FIELDS`), and refusing
	every line on a site that has never recorded an MRP would make the app unusable to say
	something it does not actually know.
	"""
	if rate is None or mrp is None:
		return False
	return flt(rate) > flt(mrp)


# A breach is collected where the rate is computed - in `catalogue.cart_for`, which holds the item
# detail and its MRP together - and named in the payload beside `unpriced_items`. It is
# deliberately NOT carried on a cart line: those lines are the scheme engine's input, and ADR-021
# keeps that contract to whole base units and integer paise. `order.create` is where a breach is
# refused, because booking a line the company may not legally sell at is worse than losing a cart.
