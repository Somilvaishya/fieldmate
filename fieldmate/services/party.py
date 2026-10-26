"""What FieldMate needs to know about a party we bill, derived rather than stored.

A party is an ERPNext Customer (ADR-013, and Phase 1's retirement of FieldMate Distributor
Profile). Everything commercial about it - its credit limit, its payment terms, its price list -
is already the Customer's own, held in the shape ERPNext bills from. This module reads that shape
and answers the one or two plain questions a phone screen asks, so that no `fm_` field has to
hold a second copy of a number ERPNext is already keeping.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

from fieldmate.services import settings as settings_service

# A month, for the one term basis that counts in months. ERPNext resolves this exactly against a
# real invoice date; we have no invoice date here, only a party, so this is the approximation a
# rep would make out loud at a counter. It is used for display, never to set a due date on a
# document - `services.collection` reads the order's own credit_days for that.
DAYS_IN_MONTH = 30


def credit_days(customer: str | None) -> int | None:
	"""How many days this party has to pay in full, or None if nobody has said.

	Derived from the Payment Terms Template, following ERPNext's own fallback order: the
	Customer's template, then its Customer Group's, then the Company default. The answer is the
	**latest** day any part of the bill is due, because that is what "you have N days" means to
	the person being told it. A template reading "half in fifteen days, half in thirty" answers
	thirty; it does not answer twenty-two and a half, and it is deliberately not stored as a
	single number anywhere, because no single number states it.
	"""
	template = _template_for(customer)
	if not template:
		return None

	rows = frappe.get_all(
		"Payment Terms Template Detail",
		filters={"parent": template},
		fields=["payment_term", "credit_days", "credit_months", "due_date_based_on"],
		limit_page_length=0,
	)
	if not rows:
		return None

	# Zero is an answer, not an absence. `credit_days` is an Int column and so cannot tell a
	# deliberate zero from an empty field - but a Payment Terms Template row only exists because
	# somebody configured one, and a row reading "100% of it, zero days after the invoice date"
	# is how ERPNext spells payable on delivery. It puts the invoice date in `due_date` for that
	# row, so this says nothing different. None is kept for the one case that really is an
	# absence: no template anywhere in the chain.
	#
	# Found on testerp2, where a template named "15 Days" had nothing in its Credit Days field.
	# Answering None there hid the misconfiguration; answering 0 shows it.
	return max(_days_in(row) for row in rows)


def payment_terms_template(customer: str | None) -> str | None:
	"""Which template bills this party. Exposed because a manager asked to see it once."""
	return _template_for(customer)


# --------------------------------------------------------------------------------------
# what a rep carries about their depots
# --------------------------------------------------------------------------------------


# Why a party is on a rep's list. Carried through to the phone and shown beside the name, because
# a list nobody can explain is the defect this replaced: one party appeared, nobody could say on
# what grounds, and when none appeared the screen blamed the territory - which on most sites was
# not the reason at all.
BY_ACCOUNT = "account"
BY_TERRITORY = "territory"
BY_SHOPS = "shops"
BY_ASSIGNMENT = "assigned"

WHY = {
	BY_ACCOUNT: "Your account",
	BY_TERRITORY: "In your territory",
	BY_SHOPS: "Supplies your shops",
	BY_ASSIGNMENT: "Assigned to you",
}


def _territory_subtree(territory: str | None) -> list[str]:
	"""A territory and everything under it.

	The whole tree, not the one node. A rep covering a leaf sees only that leaf either way, but a
	manager standing on an area saw **nothing** when this was an exact match - their own node
	holds no shops and no parties, every one of those sits on a child.
	"""
	if not territory:
		return []
	bounds = frappe.db.get_value("Territory", territory, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return [territory]
	return frappe.get_all(
		"Territory",
		filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]},
		pluck="name",
	) or [territory]


def reachable(field_user: str | None) -> dict[str, str]:
	"""The parties this rep may sell to directly, each with the reason it is on the list.

	A rep's book and a rep's map are different things, and a site keeps one, the other, or both.
	So there is no single rule here - there are four ways on, and a party needs only one:

	- **Their own account.** The rep's `sales_person` named on the Customer's Sales Team. This is
	  the answer wherever somebody owns the relationship: the party is theirs wherever it sits on
	  the map.
	- **Their territory.** A party with a channel tier anywhere in the rep's territory subtree.
	- **It supplies their shops.** The `distributor` behind outlets in that same subtree. This was
	  the only rule before, and it is kept: on a route-selling site it is still the true one.
	- **Assigned on their record.** `FieldMate Field User.distributor`, for a rep who has no shops
	  yet and would otherwise start with an empty screen.

	The first two are new, and both require `fm_tier` - a Customer FieldMate cannot place in the
	chain cannot be ordered on at all, so listing one is a door that opens onto a refusal. The
	third deliberately does not: it has never required a tier, and quietly dropping a party a rep
	has been ordering on for months is not a fix.

	A party reached more than one way is named by the most specific reason, which is the order
	these are written in.
	"""
	if not field_user:
		return {}

	rep = frappe.db.get_value(
		"FieldMate Field User", field_user, ["territory", "sales_person", "distributor"],
		as_dict=True)
	if not rep:
		return {}

	territories = _territory_subtree(rep.territory)
	found: dict[str, str] = {}

	def take(names, why):
		for name in names:
			if name and name not in found:
				found[name] = why

	if rep.sales_person:
		take(frappe.get_all(
			"Sales Team",
			filters={"parenttype": "Customer", "sales_person": rep.sales_person},
			pluck="parent",
		), BY_ACCOUNT)

	if territories:
		take(frappe.get_all(
			"Customer",
			filters={"territory": ["in", territories], "fm_tier": ["is", "set"],
			         "disabled": 0},
			pluck="name",
		), BY_TERRITORY)

		take(frappe.get_all(
			"FieldMate Outlet", filters={"territory": ["in", territories]}, pluck="distributor",
		), BY_SHOPS)

	if rep.distributor:
		take([rep.distributor], BY_ASSIGNMENT)

	# An account route can name a party that is not a Customer we sell to at all - a Sales Team
	# row survives its party being disabled. Checked once, at the end, rather than per route.
	live = set(frappe.get_all(
		"Customer", filters={"name": ["in", list(found)], "disabled": 0}, pluck="name",
	)) if found else set()

	return {name: why for name, why in found.items() if name in live}


def distributors_of(field_user: str | None) -> list[str]:
	"""Just the names, for callers that do not draw a screen."""
	return sorted(reachable(field_user))


def counter_facts(field_user: str | None) -> list[dict]:
	"""What a rep reads out at a counter about whoever supplies the shop they are standing in.

	Three things, and only three: who the order is going to, when they dispatch, and how long the
	shop has to pay. The phone has to answer all of them with no signal, so they travel in the
	bootstrap payload, which the client stores and reads back offline.

	This replaces syncing FieldMate Distributor Profile wholesale (step 2d-iii). That pull also
	carried a price list, a status, a mobile number and a minimum order value, none of which the
	app has ever read - the registry comment beside it claimed the minimum was read out at the
	counter, and it never was. Sending what is used is also what makes this safe to answer here:
	a FieldMate endpoint decides exactly which Customer fields leave the server, where registering
	Customer for sync would have had to hand a handset read access to the whole master.
	"""
	why = reachable(field_user)
	if not why:
		return []

	rows = frappe.get_all(
		"Customer",
		filters={"name": ["in", list(why)]},
		fields=["name", "customer_name", "fm_delivery_days", "fm_tier"],
		limit_page_length=0,
	)
	return [
		{
			"distributor": row.name,
			"distributor_name": row.customer_name or row.name,
			# A lead time in days, not a list of weekdays - see `fm_delivery_days`.
			"delivery_days": cint(row.fm_delivery_days) or None,
			"credit_days": credit_days(row.name),
			# Where in the chain they sit, so the screen can say "Distributor" rather than leave
			# a rep guessing which of several names in front of them is which.
			"tier": row.fm_tier or None,
			# Why this one is on this rep's list, as a code and as words. Additive, so a handset
			# that has not updated simply does not read them.
			"why": why[row.name],
			"why_label": WHY.get(why[row.name]) or "",
		}
		for row in rows
	]


# --------------------------------------------------------------------------------------
# the reads
# --------------------------------------------------------------------------------------


def _template_for(customer: str | None) -> str | None:
	if not customer:
		return None
	row = frappe.db.get_value("Customer", customer, ["payment_terms", "customer_group"],
	                          as_dict=True)
	if not row:
		return None
	if row.payment_terms:
		return row.payment_terms
	if row.customer_group:
		group = frappe.db.get_value("Customer Group", row.customer_group, "payment_terms")
		if group:
			return group
	# The company default, which on most sites is the only one anybody set. FieldMate's own
	# default company first: `frappe.defaults` is the session default that ADR-020 keeps out of
	# every other decision, and it is no more trustworthy here.
	company = settings_service.value("default_company") \
		or frappe.defaults.get_global_default("company")
	return frappe.db.get_value("Company", company, "payment_terms") if company else None


def _days_in(row) -> int:
	"""One template row restated as days from the invoice date. Zero is a valid answer.

	A row holding neither falls back to the Payment Term master it names: ERPNext copies the
	master's values into the row when you pick one, but a row written by an import or a patch may
	not have been. The fallback cannot tell a deliberate zero from an empty row either, and reads
	the master in both cases - which costs one query and answers the same zero.
	"""
	days, months, basis = row.get("credit_days"), row.get("credit_months"), \
		row.get("due_date_based_on")
	if not days and not months and row.get("payment_term"):
		master = frappe.db.get_value(
			"Payment Term", row["payment_term"],
			["credit_days", "credit_months", "due_date_based_on"], as_dict=True) or {}
		days, months = master.get("credit_days"), master.get("credit_months")
		basis = basis or master.get("due_date_based_on")

	if basis == "Month(s) after the end of the invoice month":
		return cint(months) * DAYS_IN_MONTH
	# Both remaining bases count in days. "After the end of the invoice month" adds however many
	# days are left in that month, which depends on an invoice date we do not have here.
	return cint(days)
