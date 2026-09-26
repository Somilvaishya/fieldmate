"""Our end of a claim: agreeing to it, refusing it, paying it.

Separate from `api/portal.py` because the two have opposite audiences and opposite guards. The
portal asks; this decides. A portal user reaching any method here is refused by the role check,
not by a scoping rule, because nothing about a depot's own identity makes an approval theirs to
give.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok
from fieldmate.services import claim as claim_service

# Who may agree that we owe a distributor money. Deliberately short.
APPROVER_ROLES = ("FieldMate Sales Head", "FieldMate Admin", "System Manager")


def _assert_approver() -> None:
	if not set(APPROVER_ROLES) & set(frappe.get_roles()):
		raise FieldMateError(Err.PERMISSION_DENIED,
		                     "Approving a claim is a sales head's decision.")


@frappe.whitelist()
@endpoint()
def pending(distributor: str | None = None, limit: int = 100):
	"""Everything waiting on somebody at our end."""
	_assert_approver()
	filters = {"claim_status": "Pending Approval", "docstatus": 1}
	if distributor:
		filters["distributor"] = distributor
	return ok({"claims": frappe.get_all(
		"FieldMate Claim",
		filters=filters,
		fields=["name", "distributor", "claim_date", "from_date", "to_date", "scheme",
		        "reference_no", "line_count", "outlet_count", "claimed_amount",
		        "reconciles", "variance_amount", "submitted_on"],
		order_by="submitted_on asc",
		limit_page_length=int(limit),
	)})


@frappe.whitelist()
@endpoint()
def detail(claim: str):
	_assert_approver()
	return ok(claim_service.summarise(claim))


@frappe.whitelist(methods=["POST"])
@endpoint()
def decide(claim: str, decision: str, approved_amount=None, remarks: str | None = None,
           settle: int = 1):
	"""Approve or reject. Approving with `settle` raises the credit note in the same call."""
	_assert_approver()
	return ok(claim_service.approve(claim, decision, approved_amount=approved_amount,
	                                remarks=remarks, settle=bool(frappe.utils.cint(settle))))


@frappe.whitelist(methods=["POST"])
@endpoint()
def settle(claim: str, posting_date: str | None = None):
	"""Release the credit note for a claim approved earlier."""
	_assert_approver()
	return ok(claim_service.settle_claim(claim, posting_date=posting_date))


@frappe.whitelist(methods=["POST"])
@endpoint()
def reverse(claim: str):
	"""Cancel the credit note and put the claim back to approved."""
	_assert_approver()
	return ok(claim_service.reverse(claim))
