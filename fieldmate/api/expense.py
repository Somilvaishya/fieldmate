"""Expense claims, as the rep files them and as a manager answers them."""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import expense as expense_service
from fieldmate.services import field_user as field_user_service

APPROVER_ROLES = ("FieldMate Area Manager", "FieldMate Regional Manager",
                  "FieldMate Sales Head", "FieldMate Admin", "System Manager")


def _me() -> str:
	mine = field_user_service.for_user()
	if not mine:
		raise FieldMateError(Err.PERMISSION_DENIED, "You are not set up as a field user.")
	return mine


def _assert_manager() -> None:
	if not set(APPROVER_ROLES) & set(frappe.get_roles()):
		raise FieldMateError(Err.PERMISSION_DENIED, "That is a manager's decision.")


@frappe.whitelist()
@endpoint()
def estimate(claim_date: str | None = None, expense_type: str = "Travel"):
	"""What the day is worth before anything is filed. Fills the screen."""
	return ok(expense_service.estimate(_me(), claim_date=claim_date, expense_type=expense_type))


@frappe.whitelist(methods=["POST"])
@endpoint()
def create_claim(payload=None):
	"""File one. Idempotent on the device's own uuid, like everything a phone creates."""
	data = parse_json(payload, "payload") or {}
	if not isinstance(data, dict):
		raise FieldMateError(Err.BAD_REQUEST, "Send the claim as an object.")
	result = expense_service.create(data, _me())
	if frappe.utils.cint(data.get("submit", 1)) and result["docstatus"] == 0:
		result = expense_service.submit_claim(result["name"], _me())
	return ok(result)


@frappe.whitelist()
@endpoint()
def my_claims(limit: int = 30):
	return ok(expense_service.mine(_me(), limit=int(limit)))


@frappe.whitelist()
@endpoint()
def detail(claim: str):
	doc = frappe.get_doc("FieldMate Expense Claim", claim)
	expense_service.assert_owner(doc, _me())
	return ok(expense_service.summarise(doc))


@frappe.whitelist()
@endpoint()
def pending(limit: int = 100):
	"""Everything waiting on a manager, oldest first."""
	_assert_manager()
	return ok({"claims": expense_service.pending_for_manager(limit=int(limit))})


@frappe.whitelist(methods=["POST"])
@endpoint()
def decide(claim: str, decision: str, approved_amount=None, remarks: str | None = None,
           settle: int = 1):
	_assert_manager()
	return ok(expense_service.approve(claim, decision, approved_amount=approved_amount,
	                                  remarks=remarks,
	                                  settle=bool(frappe.utils.cint(settle))))


@frappe.whitelist(methods=["POST"])
@endpoint()
def reverse(claim: str):
	_assert_manager()
	return ok(expense_service.reverse(claim))
