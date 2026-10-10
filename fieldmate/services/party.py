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


def distributors_of(field_user: str | None) -> list[str]:
	"""The parties this rep sells through.

	Derived from the shops they actually serve rather than from a field on the rep: a rep works
	whoever supplies their beat, and the `distributor` column on FieldMate Field User is empty on
	most sites. The rep's own is folded in when it is set, so a rep with no outlets yet is not
	left with an empty list.
	"""
	if not field_user:
		return []

	territory = frappe.db.get_value("FieldMate Field User", field_user, "territory")
	names = set(frappe.get_all("FieldMate Outlet", filters={"territory": territory},
	                           pluck="distributor"))
	own = frappe.db.get_value("FieldMate Field User", field_user, "distributor")
	if own:
		names.add(own)
	names.discard(None)
	names.discard("")
	return sorted(names)


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
	names = distributors_of(field_user)
	if not names:
		return []

	rows = frappe.get_all(
		"Customer",
		filters={"name": ["in", names]},
		fields=["name", "customer_name", "fm_delivery_days"],
		limit_page_length=0,
	)
	return [
		{
			"distributor": row.name,
			"distributor_name": row.customer_name or row.name,
			# A lead time in days, not a list of weekdays - see `fm_delivery_days`.
			"delivery_days": cint(row.fm_delivery_days) or None,
			"credit_days": credit_days(row.name),
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
