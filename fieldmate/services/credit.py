"""Credit: who the money is owed by, and how much room is left.

This is the one place the two sales models branch. In **order booking** the rep takes an order at
a shop, but the distributor is billed and it is the distributor's credit that is at risk. In
**van sales** the goods come off the vehicle and we bill the shop itself, so the shop's own
customer account is the party. Everything downstream - the order, the invoice, the collection,
the scheme accrual - hangs off that one answer, so it is settled here and nowhere else.
Scattering `if van_sales:` through the order and collection code is how one app quietly becomes
two that share a name (ADR-016).

The second job here is the sentence. A credit result is read out loud by a rep standing at a
counter, to a shopkeeper who is about to be told no, so every path ends in words with the numbers
in them. "CreditLimitExceeded" is not something anybody can say to somebody's face.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, fmt_money

from fieldmate import compat
from fieldmate.services import channel as channel_service
from fieldmate.services import settings as settings_service

WITHIN_LIMIT = "Within Limit"
BREACH = "Breach"
NO_LIMIT_SET = "No Limit Set"


def billing_party(outlet, field_user: str | None = None) -> dict:
	"""Who the money is owed by for a sale at this shop.

	Delegates to `channel.resolve`, which is the one function that decides what kind of sale this
	is and who gets the bill (Phase 1, step 5). The shape is kept because several callers read it.

	**This fixes a live defect.** The old version answered `doc.distributor` unconditionally and
	never read `FieldMate Outlet.customer` at all - that field was described as read by
	`we_are_the_seller` "and absolutely nowhere else", and `we_are_the_seller` used it only to set
	a boolean. So for a shop the company genuinely invoices direct, which is the whole point of
	ADR-024's escape hatch, every caller still got the distributor: the catalogue priced against
	the wrong party, the credit check measured the wrong limit, and `_raise_sales_order` raised
	the Sales Order in the wrong company's name.
	"""
	answer = channel_service.resolve(_outlet(outlet).name, "Outlet", field_user)
	return {
		"outlet": answer["party"],
		# What kind of sale this is, which is what `mode` was always reaching for. Secondary at a
		# kirana, Primary at a shop we invoice ourselves.
		"mode": answer["kind"],
		"party": answer["bill_to"],
		"party_name": answer["bill_to_name"],
		"company": answer["company"],
		# Whether this site makes this kind of sale at all, and why not. Carried rather than acted
		# on here: this function draws screens as well as gating orders, and a rep looking at a
		# catalogue should see prices even on a day somebody has switched the mode off.
		"allowed": answer["allowed"],
		"reason": answer["reason"],
	}


def we_are_the_seller(outlet, field_user: str | None = None) -> dict:
	"""Is this company the party that bills the shop? Answered here and absolutely nowhere else.

	A retailer order is a **secondary** sale: the distributor bills the shop out of their own
	stock, and our books never see it (ADR-023). Booking a Sales Order for one would record
	revenue on a sale we did not make, eat the distributor's credit for stock they never asked
	for, and double-count against stock they may already be holding.

	Exactly **one** case puts us on the other side of the counter: an outlet the company genuinely
	invoices direct, which is the escape hatch `FieldMate Outlet.customer` exists for. Only that
	produces an ERPNext document.

	**Van sales is not the second case, though it looks like one** (ADR-024). The stock in the
	vehicle belongs to the distributor; the rep carries it and hands it over. Van sales is not a
	different seller, it is a different delivery timing - the goods move at the counter instead of
	later - and the sale is the distributor's either way. Treating it as ours would record revenue
	on a sale we did not make and put goods in our Stock Ledger that we had already sold to the
	distributor at primary billing, which is ADR-023's mistake wearing a different hat.

	`order.py` asks this and branches once on the answer. That is the whole point: an
	`if van_sales:` in the order code, and another in the collection code, and another in the
	scheme code, is how one app quietly becomes two that share a name.

	Since step 5 the answer comes from `channel.resolve` rather than from a second reading of
	`FieldMate Outlet.customer` here - one function decides the kind of sale, and this states what
	the order path does about it.
	"""
	party = billing_party(outlet, field_user)
	direct = party["mode"] == settings_service.PRIMARY

	return {
		**party,
		"we_bill": direct,
		"why": "directly billed outlet" if direct else "the distributor sells to this shop",
		# What the order routes to when we are NOT the seller - which is nearly always. The
		# distributor's queue is the whole downstream, and until the Phase 9 portal ships it is a
		# Desk list view filtered on this party.
		"routes_to_distributor": not direct,
	}


def check(outlet, field_user: str | None = None, order_value=0) -> dict:
	"""What this order does to the party's credit, and whether it may go through.

	Returned whole rather than raised. A rep sees this at the door as well as at the till, and
	knowing there is room for ten thousand rupees before the cart is built is worth a great deal
	more than being refused after it.
	"""
	doc = _outlet(outlet)
	result = dict(billing_party(doc, field_user))
	party, company = result["party"], result["company"]
	order_value = flt(order_value)
	settings = settings_service.get()

	result.update({
		"order_value": order_value,
		"limit": 0.0,
		"outstanding": 0.0,
		"exposure": order_value,
		"headroom": None,
		"status": NO_LIMIT_SET,
		"blocks": False,
		"can_override": False,
		"message": "",
	})

	if not party:
		# Nobody to bill, so there is nothing to measure. In order booking this is a shop whose
		# distributor was never filled in; in van sales it is a shop nobody has set up for
		# direct billing, and selling off the van to it would leave goods gone and no invoice.
		result["blocks"] = True
		result["message"] = _no_party_message()
		return result

	if not company:
		# The company decides which ledger the limit and the outstanding are read from. Guessing
		# would read them from the wrong books, and a limit read from the wrong books reads as
		# no limit at all. Say so instead - and do not hold an order over something the rep
		# cannot fix from a market (ADR-017).
		result["message"] = frappe._(
			"Credit could not be checked because no company is set against your login. "
			"This order is not being held; tell your manager so it can be corrected."
		)
		return result

	limit = _limit(doc, party, company)
	# The check counts what is booked and not yet billed as well as what is invoiced. A rep can
	# book a month of business in a morning and none of it is an invoice yet, so a limit measured
	# on invoices alone would not bite until the goods had already gone.
	outstanding = flt(compat.get_outstanding(party, company, include_open_orders=True))
	exposure = outstanding + order_value
	currency = frappe.get_cached_value("Company", company, "default_currency")
	name = result["party_name"] or party

	result["limit"] = limit
	result["outstanding"] = outstanding
	result["exposure"] = exposure

	if not limit:
		# Currency columns in Frappe are NOT NULL DEFAULT 0, so a limit of zero cannot be told
		# apart from a limit nobody has set, and ERPNext reads it the same way. Treating the
		# default as a ceiling would block every order for every new distributor on day one.
		result["message"] = frappe._(
			"{0} has no credit limit set, so nothing is holding this order. They owe {1} today."
		).format(name, _money(outstanding, currency))
		return result

	result["headroom"] = flt(limit - outstanding, 2)

	# Compared at two decimals. A float sum of a hundred invoice totals can land a fraction of a
	# paisa above a limit that was exactly met, and "you are 0.000001 over" is not something a
	# rep can explain across a counter.
	if flt(exposure, 2) <= flt(limit, 2):
		result["status"] = WITHIN_LIMIT
		result["message"] = frappe._(
			"This order is within limit. {0} owes {1} of {2}, leaving {3} after this order."
		).format(name, _money(outstanding, currency), _money(limit, currency),
		         _money(limit - exposure, currency))
		return result

	over = flt(exposure - limit, 2)
	result["status"] = BREACH
	result["blocks"] = bool(cint(settings.get("block_order_on_credit_breach")))
	# There is nothing to override when nothing is being held, so the two settings only compound
	# in one direction: a breach that blocks may have a way forward, a breach that does not
	# never needed one.
	result["can_override"] = result["blocks"] and bool(cint(settings.get("allow_credit_override")))
	result["message"] = _breach_message(
		name, _money(over, currency), _money(limit, currency), result["blocks"], result["can_override"]
	)
	return result


# --------------------------------------------------------------------------------------
# the parts of the answer
# --------------------------------------------------------------------------------------


def _limit(outlet_doc, party: str, company: str) -> float:
	"""The ceiling this sale is measured against. 0.0 means nobody has set one.

	The distributor's limit with us, because the distributor is who we bill. The shop's own
	`credit_limit` is not read: the shop owes the distributor, not us, and the two-level credit
	check that measures that properly is Phase 3 of the channel design.
	"""
	return flt(compat.get_credit_limit(party, company))


def _company(field_user: str | None) -> str | None:
	"""Whose books this sale lands in.

	Read from the rep, then from settings, and never from the session default. Frappe fills an
	empty Link field from whatever company the login last touched in Desk, so a default picked
	up that way would be silently wrong for any rep who has never touched Desk at all.
	"""
	company = None
	if field_user:
		company = frappe.db.get_value("FieldMate Field User", field_user, "company")
	return company or settings_service.value("default_company")


def _outlet(outlet):
	"""Callers hold either a name or an already loaded document. Both are fine here."""
	return frappe.get_doc("FieldMate Outlet", outlet) if isinstance(outlet, str) else outlet


def _money(value, currency: str | None) -> str:
	return fmt_money(flt(value), currency=currency)


# --------------------------------------------------------------------------------------
# the sentences
# --------------------------------------------------------------------------------------


def _no_party_message() -> str:
	return frappe._(
		"This shop has no distributor against it, so there is nobody to bill. Ask your manager "
		"to set one before you book an order."
	)


def _breach_message(name: str, over: str, limit: str, blocks: bool, can_override: bool) -> str:
	if not blocks:
		return frappe._(
			"This order takes {0} {1} past their {2} credit limit. It will still go through, "
			"and the office will see it."
		).format(name, over, limit)

	if can_override:
		return frappe._(
			"This order takes {0} {1} past their {2} credit limit, so your manager has to "
			"approve it before it is confirmed."
		).format(name, over, limit)

	return frappe._(
		"This order takes {0} {1} past their {2} credit limit, so it cannot be booked until "
		"{1} of that is paid."
	).format(name, over, limit)
