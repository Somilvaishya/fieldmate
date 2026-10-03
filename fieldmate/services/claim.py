"""Scheme claims: a distributor asking for back what a rep gave away out of his stock.

The shape of this module mirrors `order.py` for a reason. A distributor, like a rep, holds no
write permission on anything that touches money (ADR-004 extended to the portal). Every function
here is called from a whitelisted endpoint that has already established *which* distributor is
asking, and then does the work server-elevated. Nothing in this file decides who the caller is;
that is `portal.py`, and keeping the two apart is what makes the scoping auditable.

One accounting document comes out of the whole phase: a credit note, raised on approval. Nothing
else here posts anything.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate, now_datetime, nowdate

from fieldmate import compat
from fieldmate.fieldmate.doctype.fieldmate_claim.fieldmate_claim import (
	CLAIMABLE_KINDS,
	eligible_rows,
)
from fieldmate.services import settings as settings_service

OPEN_STATUSES = ("Draft", "Pending Approval", "Approved")


# --------------------------------------------------------------------------------------
# building
# --------------------------------------------------------------------------------------


def claimable(distributor: str, from_date, to_date, scheme: str | None = None) -> dict:
	"""What this distributor could claim for this window, without creating anything.

	The portal calls this to fill the preview a person looks at before raising the claim. It is
	also what the reconciliation on the saved document compares against, so the two can never
	disagree about what the window holds.
	"""
	rows = eligible_rows(distributor, from_date, to_date, scheme=scheme)
	by_scheme: dict[str, dict] = {}
	for row in rows:
		bucket = by_scheme.setdefault(row.scheme, {
			"scheme": row.scheme,
			"scheme_name": frappe.db.get_value("FieldMate Scheme", row.scheme, "scheme_name"),
			"lines": 0, "outlets": set(), "amount": 0.0, "free_qty": 0.0,
		})
		bucket["lines"] += 1
		bucket["amount"] += flt(row.benefit_amount)
		bucket["free_qty"] += flt(row.free_qty)
		if row.outlet:
			bucket["outlets"].add(row.outlet)

	schemes = []
	for bucket in by_scheme.values():
		bucket["outlets"] = len(bucket["outlets"])
		schemes.append(bucket)
	schemes.sort(key=lambda s: s["amount"], reverse=True)

	return {
		"distributor": distributor,
		"from_date": str(getdate(from_date)),
		"to_date": str(getdate(to_date)),
		"scheme": scheme,
		"line_count": len(rows),
		"total_amount": sum(flt(r.benefit_amount) for r in rows),
		"outlet_count": len({r.outlet for r in rows if r.outlet}),
		"schemes": schemes,
	}


def build(distributor: str, from_date, to_date, scheme: str | None = None,
          reference_no: str | None = None, remarks: str | None = None) -> str:
	"""Raise a draft claim for everything unclaimed in the window.

	A draft, not a submission. Somebody at the depot reads the lines and submits, because a claim
	that raised and submitted itself would be a claim nobody looked at, and the first person to
	look at it would be the person approving it.
	"""
	rows = eligible_rows(distributor, from_date, to_date, scheme=scheme)
	if not rows:
		frappe.throw(
			frappe._("Nothing is left to claim between {0} and {1}.")
			.format(getdate(from_date), getdate(to_date))
		)

	company = frappe.db.get_value("FieldMate Scheme Ledger", rows[0].name, "company") \
		or settings_service.value("default_company")

	doc = frappe.new_doc("FieldMate Claim")
	doc.claim_date = nowdate()
	doc.distributor = distributor
	# `customer` is deliberately not set here. `resolve_party` on the controller is the one place
	# that decides it, and it answers the same way whether the claim was built from this service,
	# from the portal or by hand in Desk.
	doc.company = company
	doc.currency = frappe.db.get_value("Company", company, "default_currency")
	doc.from_date = getdate(from_date)
	doc.to_date = getdate(to_date)
	doc.scheme = scheme
	doc.reference_no = reference_no
	doc.remarks = remarks
	for row in rows:
		doc.append("items", {"scheme_ledger": row.name})

	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def submit_claim(name: str) -> dict:
	doc = frappe.get_doc("FieldMate Claim", name)
	if doc.docstatus != 0:
		frappe.throw(frappe._("This claim has already been submitted."))
	doc.flags.ignore_permissions = True
	doc.submit()
	return summarise(doc.reload() or doc)


# --------------------------------------------------------------------------------------
# approval and settlement
# --------------------------------------------------------------------------------------


def approve(name: str, decision: str, approved_amount=None, remarks: str | None = None,
            settle: bool = True) -> dict:
	"""Agree or refuse, and on agreement raise the credit note.

	`settle` exists because approving and paying are two decisions at most companies: a sales
	head agrees the claim, finance releases the note days later. Where they are one person it is
	one call, and the default says so.
	"""
	doc = frappe.get_doc("FieldMate Claim", name)
	if doc.docstatus != 1:
		frappe.throw(frappe._("Only a submitted claim can be approved or rejected."))
	if doc.claim_status not in ("Pending Approval", "Approved"):
		frappe.throw(
			frappe._("This claim is {0} and is no longer waiting on a decision.")
			.format(doc.claim_status.lower()))

	if decision == "Rejected":
		if not remarks:
			frappe.throw(frappe._("Say why it was rejected. A bare rejection is a phone call."))
		doc.db_set("claim_status", "Rejected", update_modified=False)
		doc.db_set("rejection_reason", remarks, update_modified=False)
		doc.db_set("approved_by", frappe.session.user, update_modified=False)
		doc.db_set("approved_on", now_datetime(), update_modified=False)
		doc.db_set("approved_amount", 0, update_modified=False)
		_release(doc)
		return summarise(doc.reload() or doc)

	if decision != "Approved":
		frappe.throw(frappe._("A claim is either Approved or Rejected."))

	amount = flt(approved_amount) if approved_amount is not None else flt(doc.claimed_amount)
	if amount <= 0:
		frappe.throw(frappe._("An approved claim has to be worth something."))
	if amount > flt(doc.claimed_amount) + 0.005:
		frappe.throw(
			frappe._("You cannot approve {0} against a claim for {1}.")
			.format(amount, doc.claimed_amount))

	doc.db_set("approved_amount", amount, update_modified=False)
	doc.db_set("approved_by", frappe.session.user, update_modified=False)
	doc.db_set("approved_on", now_datetime(), update_modified=False)
	doc.db_set("approval_remarks", remarks, update_modified=False)
	doc.db_set("claim_status", "Approved", update_modified=False)

	if settle:
		return settle_claim(doc.name)
	return summarise(doc.reload() or doc)


def settle_claim(name: str, posting_date=None) -> dict:
	"""Raise the credit note and close the accruals behind it."""
	doc = frappe.get_doc("FieldMate Claim", name)
	# Already settled is the ordinary state after a retried click, not an error. Checked before
	# the status guard, because by then the status IS "Settled" and the guard would refuse the
	# one call that should be free.
	if doc.credit_note:
		return summarise(doc)
	if doc.claim_status != "Approved":
		frappe.throw(
			frappe._("Only an approved claim can be settled. This one is {0}.")
			.format(doc.claim_status.lower()))

	company = doc.company
	note = compat.make_credit_note({
		# The claim name is the key. An approval clicked twice on a slow connection asks for the
		# same credit note and gets the one that already exists.
		"key": f"CLAIM:{doc.name}",
		"customer": doc.customer,
		"company": company,
		"currency": doc.currency,
		"posting_date": posting_date or nowdate(),
		"amount": flt(doc.approved_amount),
		"item_code": settings_service.value("claim_settlement_item"),
		"income_account": settings_service.value("claim_expense_account"),
		"cost_center": settings_service.value("claim_cost_center")
		               or frappe.db.get_value("Company", company, "cost_center"),
		"description": _describe(doc),
	})

	doc.db_set("credit_note", note, update_modified=False)
	doc.db_set("settled_on", posting_date or nowdate(), update_modified=False)
	doc.db_set("claim_status", "Settled", update_modified=False)

	for row in doc.items or []:
		frappe.db.set_value("FieldMate Scheme Ledger", row.scheme_ledger,
		                    {"status": "Settled", "settled_on": doc.settled_on},
		                    update_modified=False)

	return summarise(doc.reload() or doc)


def _describe(doc) -> str:
	scheme = f" for {doc.scheme}" if doc.scheme else ""
	return (f"FieldMate scheme claim {doc.name}{scheme}: {doc.line_count} benefits granted at "
	        f"{doc.outlet_count} outlets between {doc.from_date} and {doc.to_date}.")


def _release(doc) -> None:
	"""Put a rejected claim's accruals back on the table.

	A rejected claim that keeps its rows marked Claimed would silently delete the distributor's
	entitlement: he fixes whatever was wrong, claims again, and the window comes back empty.
	"""
	for row in doc.items or []:
		frappe.db.set_value("FieldMate Scheme Ledger", row.scheme_ledger,
		                    {"status": "Accrued", "claim": None}, update_modified=False)


def reverse(name: str) -> dict:
	"""Undo a settled claim: cancel the note, then release the ledger.

	In that order, and the order is not a preference. A submitted Sales Invoice linked from the
	claim is a back-link, and Frappe refuses to cancel the claim while one stands - the same trap
	that caught the Scheme Ledger on order cancel and the Payment Entry on a bounced collection.
	"""
	doc = frappe.get_doc("FieldMate Claim", name)
	note = doc.credit_note
	if note:
		doc.db_set("credit_note", None, update_modified=False)
		compat.cancel_credit_note(note)

	doc.db_set("claim_status", "Approved", update_modified=False)
	doc.db_set("settled_on", None, update_modified=False)
	for row in doc.items or []:
		frappe.db.set_value("FieldMate Scheme Ledger", row.scheme_ledger,
		                    {"status": "Claimed", "settled_on": None}, update_modified=False)
	return summarise(doc.reload() or doc)


# --------------------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------------------


def for_distributor(distributor: str, status: str | None = None, limit: int = 50) -> list[dict]:
	filters = {"distributor": distributor, "docstatus": ["<", 2]}
	if status:
		filters["claim_status"] = status
	return frappe.get_all(
		"FieldMate Claim",
		filters=filters,
		fields=["name", "claim_date", "from_date", "to_date", "scheme", "reference_no",
		        "claim_status", "line_count", "outlet_count", "claimed_amount",
		        "approved_amount", "reconciles", "variance_amount", "credit_note", "settled_on",
		        "rejection_reason", "docstatus"],
		order_by="claim_date desc, creation desc",
		limit_page_length=limit,
	)


def totals_for(distributor: str) -> dict:
	"""The four figures across the top of the claims screen.

	Counted from the claims themselves rather than kept as running totals anywhere: a stored
	total is a total that drifts, and this one is read by the person who is owed the money.
	"""
	buckets = {"claimed": 0.0, "approved": 0.0, "settled": 0.0, "rejected": 0.0}
	counts = {"claimed": 0, "approved": 0, "settled": 0, "rejected": 0, "pending": 0}
	pending = 0.0

	for row in frappe.get_all(
		"FieldMate Claim",
		filters={"distributor": distributor, "docstatus": 1},
		fields=["claim_status", "claimed_amount", "approved_amount"],
		limit_page_length=0,
	):
		claimed = flt(row.claimed_amount)
		buckets["claimed"] += claimed
		counts["claimed"] += 1
		if row.claim_status == "Pending Approval":
			pending += claimed
			counts["pending"] += 1
		elif row.claim_status == "Approved":
			buckets["approved"] += flt(row.approved_amount)
			counts["approved"] += 1
		elif row.claim_status == "Settled":
			buckets["approved"] += flt(row.approved_amount)
			buckets["settled"] += flt(row.approved_amount)
			counts["approved"] += 1
			counts["settled"] += 1
		elif row.claim_status == "Rejected":
			buckets["rejected"] += claimed
			counts["rejected"] += 1

	return {**buckets, "pending": pending, "counts": counts}


def summarise(doc) -> dict:
	if isinstance(doc, str):
		doc = frappe.get_doc("FieldMate Claim", doc)
	return {
		"name": doc.name,
		"distributor": doc.distributor,
		"claim_date": str(doc.claim_date) if doc.claim_date else None,
		"from_date": str(doc.from_date) if doc.from_date else None,
		"to_date": str(doc.to_date) if doc.to_date else None,
		"scheme": doc.scheme,
		"reference_no": doc.reference_no,
		"claim_status": doc.claim_status,
		"docstatus": doc.docstatus,
		"line_count": doc.line_count,
		"outlet_count": doc.outlet_count,
		"discount_amount": flt(doc.discount_amount),
		"free_goods_amount": flt(doc.free_goods_amount),
		"claimed_amount": flt(doc.claimed_amount),
		"approved_amount": flt(doc.approved_amount),
		"ledger_count": doc.ledger_count,
		"ledger_amount": flt(doc.ledger_amount),
		"variance_amount": flt(doc.variance_amount),
		"reconciles": bool(doc.reconciles),
		"credit_note": doc.credit_note,
		"settled_on": str(doc.settled_on) if doc.settled_on else None,
		"settlement_reference": doc.settlement_reference,
		"rejection_reason": doc.rejection_reason,
		"approval_remarks": doc.approval_remarks,
		"lines": [
			{"ledger": r.scheme_ledger, "scheme": r.scheme, "order": r.order,
			 "outlet": r.outlet, "posting_date": str(r.posting_date) if r.posting_date else None,
			 "benefit_kind": r.benefit_kind, "item_code": r.item_code,
			 "benefit_amount": flt(r.benefit_amount), "free_qty": flt(r.free_qty),
			 "field_user": r.field_user}
			for r in (doc.items or [])
		],
	}


__all__ = ["CLAIMABLE_KINDS", "OPEN_STATUSES", "approve", "build", "claimable",
           "for_distributor", "reverse", "settle_claim", "submit_claim", "summarise",
           "totals_for"]
