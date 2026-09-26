"""Targets, achievement and incentives, as the phone reads them.

Everything here is scoped to the caller. A rep asking for "my targets" gets theirs; there is no
argument for a rep name, because an endpoint that took one would be an endpoint that could be
asked for somebody else's numbers. Managers read the same data through Desk, where the framework
scoping in `hooks.py` narrows nothing for them.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok
from fieldmate.services import field_user as field_user_service
from fieldmate.services import incentive as incentive_service
from fieldmate.services import target as target_service

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


# --------------------------------------------------------------------------------------
# the performance screen
# --------------------------------------------------------------------------------------


@frappe.whitelist()
@endpoint()
def my_targets(as_on: str | None = None):
	"""Where this rep stands against everything they were asked for."""
	return ok(target_service.mine(_me(), as_on=as_on))


@frappe.whitelist()
@endpoint()
def achievement(as_on: str | None = None):
	"""The same figures plus what they are currently worth in incentive.

	One call, because the performance screen shows both and two round trips on a phone in a
	market is one round trip too many.
	"""
	mine = _me()
	return ok({
		"targets": target_service.mine(mine, as_on=as_on),
		"incentive": incentive_service.on_track(mine, as_on=as_on),
	})


@frappe.whitelist()
@endpoint()
def my_payouts(limit: int = 12):
	return ok({"payouts": incentive_service.mine(_me(), limit=int(limit))})


# --------------------------------------------------------------------------------------
# the manager's side
# --------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
@endpoint()
def cascade(plan: str):
	"""Split a plan down the tree. Re-runnable."""
	_assert_manager()
	return ok(target_service.cascade(plan))


@frappe.whitelist()
@endpoint()
def reconcile(plan: str):
	"""Do the leaves still add up to the root? Gate 7 criterion 1, over HTTP."""
	_assert_manager()
	return ok(target_service.reconcile(plan))


@frappe.whitelist(methods=["POST"])
@endpoint()
def recompute(plan: str | None = None, as_on: str | None = None):
	"""Measure one plan, or every live one. The nightly job by hand."""
	_assert_manager()
	if plan:
		return ok({"achievement": target_service.compute(plan)})
	return ok(target_service.compute_all(as_on=as_on))


@frappe.whitelist(methods=["POST"])
@endpoint()
def compute_payouts(from_date: str, to_date: str, dry_run: int = 0):
	_assert_manager()
	return ok(incentive_service.compute_period(from_date, to_date,
	                                           dry_run=bool(frappe.utils.cint(dry_run))))


@frappe.whitelist(methods=["POST"])
@endpoint()
def decide_payout(payout: str, decision: str, remarks: str | None = None):
	_assert_manager()
	return ok(incentive_service.approve(payout, decision, remarks=remarks))


@frappe.whitelist(methods=["POST"])
@endpoint()
def mark_payout_paid(payout: str, reference: str, paid_on: str | None = None):
	_assert_manager()
	return ok(incentive_service.mark_paid(payout, reference, paid_on=paid_on))
