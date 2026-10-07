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


def billing_party(outlet, field_user: str | None = None, party_type: str | None = None,
                  on=None) -> dict:
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
	if (party_type or "Outlet") == "Customer":
		name = outlet if isinstance(outlet, str) else outlet.name
	else:
		name = _outlet(outlet).name
	# `on` is the order date. It only matters for a primary sale - it decides which season, if
	# any, the order books into and therefore which list it is priced from.
	answer = channel_service.resolve(name, party_type or "Outlet", field_user, on=on)
	return {
		"outlet": answer["party"],
		# What kind of sale this is: Secondary at a kirana, Primary at a shop we invoice
		# ourselves.
		#
		# Under **both** names, and that is the point. This dict reshapes `channel.resolve`'s
		# answer and renamed `kind` to `mode` on the way through, so one value had two names
		# depending on which side of this function you stood on. Phase 2 walked straight into it:
		# `season.kind_for` read `kind`, got nothing, and quietly made every primary order
		# secondary. `kind` is the name; `mode` stays because this dict is part of the catalogue
		# payload and a phone that has not updated still reads it.
		"kind": answer["kind"],
		"mode": answer["kind"],
		# Empty unless this is a booking. Carried rather than re-derived downstream: the date
		# that decided it is here and is not necessarily today.
		"season": answer.get("season"),
		# The list this party buys on, which for a booking is its season's rather than its own.
		# Carried because `cart_for` has to settle the list before it prices a single line, and
		# re-deriving it there would be a second answer to a question already answered here.
		"price_list": answer.get("price_list"),
		"party": answer["bill_to"],
		"party_name": answer["bill_to_name"],
		"company": answer["company"],
		# Whether this site makes this kind of sale at all, and why not. Carried rather than acted
		# on here: this function draws screens as well as gating orders, and a rep looking at a
		# catalogue should see prices even on a day somebody has switched the mode off.
		"allowed": answer["allowed"],
		"reason": answer["reason"],
	}


def we_are_the_seller(outlet, field_user: str | None = None,
                      party_type: str | None = None) -> dict:
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
	party = billing_party(outlet, field_user, party_type)
	# `is_primary`, not `== PRIMARY`: a season booking is a primary sale under a different word,
	# and comparing the string stopped every booking from posting a Sales Order.
	direct = settings_service.is_primary(party["kind"])

	return {
		**party,
		"we_bill": direct,
		"why": "directly billed outlet" if direct else "the distributor sells to this shop",
		# What the order routes to when we are NOT the seller - which is nearly always. The
		# distributor's queue is the whole downstream, and until the Phase 9 portal ships it is a
		# Desk list view filtered on this party.
		"routes_to_distributor": not direct,
	}


def check(outlet, field_user: str | None = None, order_value=0,
          party_type: str | None = None) -> dict:
	"""What this order does to the credit on both sides of it, and whether it may go through.

	Returned whole rather than raised. A rep sees this at the door as well as at the till, and
	knowing there is room for ten thousand rupees before the cart is built is worth a great deal
	more than being refused after it.

	**Two levels, because a secondary sale has two debts behind it.** The shop owes its
	distributor; the distributor owes us. Until now only the second was measured, which meant a
	kirana ten thousand rupees overdue with its distributor looked perfectly clear as long as the
	distributor was square with us - and the distributor, who is the one who would refuse, found
	out when the order reached their queue.

	The top-level figures stay the distributor's, because that is what the order document records
	and what ERPNext can actually prove. The shop's own position arrives under `shop`, and
	`status` is the worse of the two so that a caller reading one field is not told "within limit"
	while one of the two parties is over.

	**The shop's figure is FieldMate's own count, not a ledger.** We are not a party to that sale,
	so there is no receivable to read: it accrues from the orders we booked and falls as
	collections come in, and a distributor who invoiced the shop something we never saw is a gap
	it cannot close. The message says so, because a rep arguing it across a counter needs to know
	which of the two numbers is which.
	"""
	result = _party_level(outlet, field_user, order_value, party_type)
	result["shop"] = _shop_level(outlet, field_user, order_value, party_type)
	# The party's own verdict, kept before the merge below can overwrite it. Without this a
	# caller can see that *something* breached and not which, because `status` becomes the worse
	# of the two - and "the distributor is over" and "the shop is over" are different problems
	# with different remedies.
	result["party_status"] = result["status"]
	result["party_message"] = result["message"]

	shop = result["shop"]
	if shop and shop["status"] == BREACH and result["status"] != BREACH:
		# The distributor is square with us and the shop is not with them. The order is still
		# worth taking - the distributor decides whether to serve it - but the rep must not read
		# "within limit" off a screen and say so out loud.
		result["status"] = BREACH
		result["blocks"] = shop["blocks"]
		result["can_override"] = shop["can_override"]
		result["message"] = shop["message"]
	return result


def _party_level(outlet, field_user: str | None = None, order_value=0,
                 party_type: str | None = None) -> dict:
	"""What the party we bill owes us, read from ERPNext's own receivable."""
	# A primary order is on a Customer and has no shop to load. `billing_party` takes the name
	# either way; only the outlet path needs the document, for its own credit fields.
	doc = None if (party_type or "Outlet") == "Customer" else _outlet(outlet)
	result = dict(billing_party(doc or outlet, field_user, party_type))
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


def _shop_position(outlet: str, field_user: str | None) -> dict:
	"""What this shop owes its distributor, from the soft ledger.

	A named seam rather than an inline import, so that a test about *the credit verdict* can
	stand this in without reaching into `services.collection` - what that function counts is its
	own business and `test_collection` is where it is proved.
	"""
	from fieldmate.services import collection as collection_service

	return collection_service.outstanding_for(outlet, field_user)


def _shop_level(outlet, field_user: str | None, order_value, party_type: str | None) -> dict | None:
	"""What this shop owes its distributor, and whether this order puts it over its limit.

	None for a primary sale: there is no second level there, because the party we bill is the
	party being sold to and `_party_level` has already measured it.

	The figure is `collection.outstanding_for`, which counts the orders this app booked at this
	shop and subtracts the collections allocated against them. It is the only count of this debt
	anywhere - we are not a party to that sale and ERPNext holds no receivable for it - and it is
	honest about being an estimate.

	A shop with no limit set is not measured. A Currency column is NOT NULL DEFAULT 0, so a zero
	cannot be told from a blank, and treating the default as a ceiling would put every shop in
	the country over its limit on the day it was onboarded.
	"""
	if (party_type or "Outlet") == "Customer":
		return None

	doc = _outlet(outlet)
	# One source for all of it, including the limit: `outstanding_for` already reads the shop's
	# `credit_limit`, and two readings of one field are two chances to disagree.
	position = _shop_position(doc.name, field_user)
	limit = flt(position.get("credit_limit"))
	outstanding = flt(position.get("outstanding"))
	exposure = flt(outstanding + flt(order_value), 2)
	settings = settings_service.get()
	company = _company(field_user)
	currency = frappe.get_cached_value("Company", company, "default_currency") if company else None

	answer = {
		"outlet": doc.name,
		"outlet_name": position.get("outlet_name"),
		"limit": limit,
		"outstanding": outstanding,
		"overdue": flt(position.get("overdue")),
		"exposure": exposure,
		"headroom": position.get("headroom"),
		"status": NO_LIMIT_SET if not limit else WITHIN_LIMIT,
		"blocks": False,
		"can_override": False,
		"message": "",
		# Said plainly wherever this is shown. The distributor's figure comes out of a ledger;
		# this one is our own arithmetic over orders and collections.
		"is_our_own_count": True,
	}
	if not limit or exposure <= flt(limit, 2):
		return answer

	over = flt(exposure - limit, 2)
	answer["status"] = BREACH
	answer["blocks"] = bool(cint(settings.get("block_order_on_credit_breach")))
	answer["can_override"] = answer["blocks"] and bool(
		cint(settings.get("allow_credit_override")))
	answer["message"] = frappe._(
		"{0} is {1} over the limit their distributor allows them, counting this order. That is "
		"our own count of what they owe, from the orders booked here and the money collected "
		"against them - collect what is due, or ask your manager."
	).format(answer["outlet_name"] or doc.name, _money(over, currency))
	return answer


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
