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
	latest = None
	for row in rows:
		days = _days_in(row)
		if days is None:
			continue
		latest = days if latest is None else max(latest, days)
	return latest


def payment_terms_template(customer: str | None) -> str | None:
	"""Which template bills this party. Exposed because a manager asked to see it once."""
	return _template_for(customer)


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


def _days_in(row) -> int | None:
	"""One template row restated as days from the invoice date.

	A blank row falls back to the Payment Term master it names: ERPNext copies the master's values
	into the row when you pick one, but a row written by an import or a patch may not have been.
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
		return cint(months) * DAYS_IN_MONTH or None
	# Both remaining bases count in days. "After the end of the invoice month" adds however many
	# days are left in that month, which depends on an invoice date we do not have here.
	return cint(days) or None
