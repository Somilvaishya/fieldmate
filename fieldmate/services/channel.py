"""What kind of sale is this, and who gets the bill.

One question, asked once, in one place. Everything downstream - which price list, which credit
limit, whether a Sales Order is posted at all - follows from the answer, so it is worth being
able to point at the single function that decides it.

**The answer comes from the party, never from a setting.** A rep booking at a kirana is making a
secondary sale because the distributor bills that shop; a rep booking on a super stockist is
making a primary sale because we bill them. No rule table decides it, and no mode is chosen by
hand. FieldMate Settings says which kinds this site makes **at all**; this says which kind a
given order is.

There is deliberately no scoring, no priority and no rule document. The design this replaces had
a Channel Rule table resolving a mode from company, state, item group, tier and season by a
weighted score. That is a configuration language, and a configuration language is a thing nobody
can answer questions about six months later. Every product this was read against - FieldAssist,
BeatRoute, Salesforce Consumer Goods Cloud - keeps one party record with a type and lets the kind
follow from it.
"""

from __future__ import annotations

import frappe

from fieldmate.services import pricing
from fieldmate.services import settings as settings_service

# A depot holding our own stock. Real in the chain, not a party we sell to.
CFA = "CFA"


def resolve(party: str, party_type: str | None = None, field_user: str | None = None) -> dict:
	"""Resolve one party to a kind of sale, a billing party and a price list.

	`party_type` is "Outlet" or "Customer". It can be left out and will be worked out, which is
	for callers that hold a name and no context; a caller that knows should say so, because a
	guess is one more thing that can be wrong.

	Returns whole rather than throwing. A rep standing at a counter needs to be told what they
	can do before they build a cart, not refused after - the same reason `credit.check` returns
	its verdict instead of raising.
	"""
	party_type = party_type or _kind_of(party)

	if party_type == "Outlet":
		answer = _from_outlet(party)
	elif party_type == "Customer":
		answer = _from_customer(party)
	else:
		return _no(None, None, party, "That is not a shop or a customer we know.")

	# The site's own switch, applied last. A party can be perfectly well set up for a kind of
	# sale this company does not make.
	if answer["allowed"] and not settings_service.allows(answer["kind"]):
		word = "Primary" if answer["kind"] == settings_service.PRIMARY else "Secondary"
		answer["allowed"] = False
		answer["reason"] = frappe._(
			"{0} sales are switched off for this company. Ask your manager."
		).format(word)

	answer["company"] = _company(field_user)
	return answer


# --------------------------------------------------------------------------------------
# the two kinds
# --------------------------------------------------------------------------------------


def _from_outlet(outlet: str) -> dict:
	"""A shop. Secondary, unless it is one of the few we invoice ourselves."""
	doc = frappe.db.get_value(
		"FieldMate Outlet", outlet,
		["name", "outlet_name", "distributor", "customer", "price_list"],
		as_dict=True,
	)
	if not doc:
		return _no("Outlet", None, outlet, frappe._("That shop was not found."))

	# ADR-024's escape hatch: a shop the company genuinely invoices direct. Rare, and the only
	# case where `FieldMate Outlet.customer` is read at all. It is a primary sale - we are the
	# seller - and naming the right party here is what stops the Sales Order being billed to the
	# distributor, which is what it did before this function existed.
	if doc.customer:
		return {
			"kind": settings_service.PRIMARY,
			"party_type": "Outlet",
			"party": doc.name,
			"party_name": doc.outlet_name,
			"bill_to": doc.customer,
			"bill_to_name": _customer_name(doc.customer),
			# We are the seller here, so the fallback is the list we bill them from rather than a
			# PTR; the shop's own still wins, for the reason `pricing.price_list_for` gives.
			"price_list": doc.price_list or pricing.sells_to_us(doc.customer),
			"tier": _tier_of(doc.customer),
			"direct_billed": True,
			"allowed": True,
			"reason": "",
		}

	if not doc.distributor:
		return _no("Outlet", doc.outlet_name, doc.name, frappe._(
			"This shop has no distributor against it, so there is nobody to bill. Ask your "
			"manager to set one before you book an order."))

	return {
		"kind": settings_service.SECONDARY,
		"party_type": "Outlet",
		"party": doc.name,
		"party_name": doc.outlet_name,
		# The distributor bills the shop. Our books never see this sale.
		"bill_to": doc.distributor,
		"bill_to_name": _customer_name(doc.distributor),
		# What the shop pays. The chain is `pricing.price_list_for` - the shop's own list, then
		# the distributor's PTR, then the rep's and the company's. This used to read the PTR
		# first, which would have quoted the tier price at the one modern-trade account that had
		# negotiated its own.
		"price_list": pricing.price_list_for(doc),
		"tier": _tier_of(doc.distributor),
		"direct_billed": False,
		"allowed": True,
		"reason": "",
	}


def _from_customer(customer: str) -> dict:
	"""A party we bill, or one that buys from its super stockist."""
	doc = frappe.db.get_value(
		"Customer", customer,
		["name", "customer_name", "fm_tier", "fm_buys_from", "fm_parent_customer"],
		as_dict=True,
	)
	if not doc:
		return _no("Customer", None, customer, frappe._("That customer was not found."))

	base = {
		"kind": settings_service.PRIMARY,
		"party_type": "Customer",
		"party": doc.name,
		"party_name": doc.customer_name,
		"tier": doc.fm_tier,
		"direct_billed": False,
	}

	if not doc.fm_tier:
		return {**base, "bill_to": None, "bill_to_name": None, "price_list": None,
		        "allowed": False, "reason": frappe._(
			        "{0} has no channel tier, so FieldMate does not know what they are in the "
			        "chain. Set one on the Customer.").format(doc.customer_name)}

	if doc.fm_tier == CFA:
		return {**base, "bill_to": None, "bill_to_name": None, "price_list": None,
		        "allowed": False, "reason": frappe._(
			        "{0} is a depot holding our own stock, not a party we sell to."
		        ).format(doc.customer_name)}

	# Buying from a super stockist means our sale is to that super stockist, not to them. They
	# are still visited and still tracked; the bill simply goes somewhere else.
	bill_to = doc.name
	if doc.fm_buys_from == "Parent":
		if not doc.fm_parent_customer:
			return {**base, "bill_to": None, "bill_to_name": None, "price_list": None,
			        "allowed": False, "reason": frappe._(
				        "{0} is set to buy from a parent, but no parent is named. Set Buys From "
				        "Party on the Customer.").format(doc.customer_name)}
		bill_to = doc.fm_parent_customer

	return {**base, "bill_to": bill_to, "bill_to_name": _customer_name(bill_to),
	        "price_list": pricing.sells_to_us(bill_to), "allowed": True, "reason": ""}


# --------------------------------------------------------------------------------------
# the small reads
# --------------------------------------------------------------------------------------


def _kind_of(party: str) -> str | None:
	"""Outlet first: a rep's day is almost entirely shops, and a miss here costs a second read."""
	if frappe.db.exists("FieldMate Outlet", party):
		return "Outlet"
	if frappe.db.exists("Customer", party):
		return "Customer"
	return None


def _tier_of(customer: str | None) -> str | None:
	return frappe.db.get_value("Customer", customer, "fm_tier") if customer else None


# Which list a party buys on is `services.pricing`, not two private readers here. There were two
# - one for what a party pays us and one for what its shops pay - and having both in this file is
# how this module came to answer the PTR question differently from the catalogue.


def _customer_name(customer: str | None) -> str | None:
	return frappe.db.get_value("Customer", customer, "customer_name") if customer else None


def _company(field_user: str | None) -> str | None:
	"""Whose books. From the rep, then from settings, and never from the session default.

	Frappe fills an empty Link field from whatever company the login last touched in Desk, so a
	default picked up that way would be silently wrong for any rep who has never opened Desk.
	"""
	company = None
	if field_user:
		company = frappe.db.get_value("FieldMate Field User", field_user, "company")
	return company or settings_service.value("default_company")


def _no(party_type: str | None, party_name: str | None, party: str, reason: str) -> dict:
	return {
		"kind": None, "party_type": party_type, "party": party, "party_name": party_name,
		"bill_to": None, "bill_to_name": None, "price_list": None, "tier": None,
		"direct_billed": False, "allowed": False, "reason": reason,
	}
