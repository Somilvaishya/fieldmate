"""Which season an order belongs to, and whether that makes it a booking.

One rule, and it is the whole of Phase 2's answer to "what kind of order is this":

    a **primary** order dated inside the booking window of its company's active season
    is a **booking** of that season.

Nothing else decides it. There is no booking flag for a rep to tick and no rule table scoring a
season against a party - the same reason `services/channel` has neither. A rep books an order; the
dates on the season say what it was.

**Why this is not in `channel`.** That module answers a question about a *party* - who gets the
bill, at what price. This one answers a question about a *date*. Keeping them apart is what lets
a booking be exactly a primary order with two more fields on it, rather than a third kind of sale
with its own path through pricing, credit and posting.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate, nowdate

from fieldmate.services import settings as settings_service

# Defined with the other kinds of sale, not here. Re-exported so the callers that think in
# seasons do not have to reach past this module for it.
BOOKING = settings_service.BOOKING


def open_for(company: str | None, on=None) -> str | None:
	"""The active season of `company` whose book is open on `on`, if there is one.

	At most one: `FieldMate Season.check_overlap` refuses a second active season booking over the
	same dates for one company, so this never has to choose. A rule for choosing would be the
	configuration language this design does not want.
	"""
	if not company:
		return None

	on = getdate(on or nowdate())
	rows = frappe.get_all(
		"FieldMate Season",
		filters={
			"company": company,
			"is_active": 1,
			"booking_from": ["<=", on],
			"booking_to": [">=", on],
		},
		fields=["name"],
		limit=2,
	)
	if len(rows) > 1:
		# Not reachable through the master's own validation, but a site can be left this way by
		# an import or a direct write. Reported rather than silently picking the first, because
		# "which season did November's orders book into" is not a question to answer by accident.
		frappe.throw(frappe._(
			"{0} has more than one season booking on {1}. Close one before taking orders."
		).format(company, on))

	return rows[0].name if rows else None


def kind_for(resolved: dict, on=None) -> tuple[str, str | None]:
	"""The order kind and the season behind it, from an answer `channel.resolve` already gave.

	`resolve` composes this itself now, because the price list depends on the answer and the
	price list has to be settled before a single line is priced. This stays for a caller holding
	a bare resolve answer - and it is idempotent, so calling it on one `resolve` has already
	decided changes nothing.

	A secondary sale is never a booking: the distributor's own sale to a kirana is not something
	we book a season against, whatever month it falls in.
	"""
	resolved = resolved or {}
	kind = resolved.get("kind")
	if kind == BOOKING:
		return BOOKING, resolved.get("season")
	if kind != settings_service.PRIMARY:
		return kind or settings_service.SECONDARY, None

	season = open_for(resolved.get("company"), on)
	return (BOOKING, season) if season else (settings_service.PRIMARY, None)


def price_list(season: str | None) -> str | None:
	"""What a booking of `season` is priced at.

	A season's list, not the party's. A party that books Holi in November is buying at the
	season's terms, and those are the same for everyone booking it - that is what a season price
	list is for. The party's own list goes back to governing its ordinary primary orders the day
	the book shuts.
	"""
	return frappe.get_cached_value("FieldMate Season", season, "price_list") if season else None


def advance_required(season: str | None, value) -> float:
	"""What has to be in hand before a booking of `season` is released, in rupees.

	Zero where the season asks for none, which is a decision somebody made on the master rather
	than an oversight - a season sold on open terms is an ordinary thing.

	Rounded to the rupee. A percentage of a cart total lands on fractions of a paisa, and
	"you are 0.004 short of your advance" is not something anybody can say to a distributor.
	"""
	if not season:
		return 0.0
	pct = flt(frappe.get_cached_value("FieldMate Season", season, "advance_pct"))
	return flt(flt(value) * pct / 100.0, 2) if pct else 0.0


def payment_terms(season: str | None) -> str | None:
	"""The Payment Terms Template a booking of `season` is sold on, if one is set.

	ERPNext's own document, named on the Sales Order so ERPNext builds the payment schedule from
	it. Blank is a real answer - a season sold on plain terms has none - and the Sales Order then
	carries whatever the customer's own terms say, which is the right fallback.
	"""
	return (frappe.get_cached_value("FieldMate Season", season, "payment_terms_template")
	        if season else None)


def may_amend(season: str | None, on=None) -> tuple[bool, str]:
	"""Is a booking of `season` still changeable on `on`?

	A season's whole commercial point is that the company can plan against the book, so the book
	stops moving at the cutoff. Returned rather than thrown, so a screen can grey a button
	instead of letting a rep find out at submit.
	"""
	if not season:
		return True, ""

	doc = frappe.get_cached_doc("FieldMate Season", season)
	if doc.may_change_on(on or nowdate()):
		return True, ""

	return False, frappe._(
		"{0} closed for changes on {1}. Ask your manager if this has to be altered."
	).format(doc.season_name, frappe.utils.formatdate(doc.change_cutoff or doc.booking_to))


def delivery_window(season: str | None) -> tuple[str | None, str | None]:
	"""The dates a booking line may be delivered between, or `(None, None)` for a plain order."""
	if not season:
		return None, None
	doc = frappe.get_cached_doc("FieldMate Season", season)
	return doc.delivery_from, doc.delivery_to
