"""A manager's Plan tab: the team's beats and their monthly journey plans.

Area Managers built these in Desk; they have no Desk now, so the phone does it. Every call is
manager-only and held to the caller's reporting line - see `services/plan.py`.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import field_user as field_user_service
from fieldmate.services import plan as plan_service


def _assert_manager() -> None:
	if not set(field_user_service.MANAGER_ROLES) & set(frappe.get_roles()):
		raise FieldMateError(Err.PERMISSION_DENIED, "That is a manager's view.")


@frappe.whitelist()
@endpoint()
def overview(month: str | None = None, territory: str | None = None,
             from_date: str | None = None, to_date: str | None = None):
	"""Every rep in the team - or one territory of it - and where their plan stands."""
	_assert_manager()
	return ok(plan_service.overview(month, territory=territory, from_date=from_date,
	                                to_date=to_date))


@frappe.whitelist()
@endpoint()
def territories():
	"""The territories this login may plan in, by its Territory User Permission."""
	_assert_manager()
	return ok({"territories": plan_service.territories()})


@frappe.whitelist()
@endpoint()
def holiday_lists(field_user: str):
	"""The rep's own holiday list, and any other this login may read."""
	_assert_manager()
	return ok(plan_service.holiday_lists(field_user))


@frappe.whitelist()
@endpoint()
def days(plan: str):
	_assert_manager()
	return ok(plan_service.days(plan))


@frappe.whitelist(methods=["POST"])
@endpoint()
def build(field_user: str, month: str | None = None, from_date: str | None = None,
          to_date: str | None = None, holiday_list: str | None = None):
	"""Make the window's draft from the rep's beats, holidays and leave."""
	_assert_manager()
	return ok(plan_service.build(field_user, month, from_date=from_date, to_date=to_date,
	                             holiday_list=holiday_list))


@frappe.whitelist(methods=["POST"])
@endpoint()
def approve(plan: str):
	_assert_manager()
	return ok(plan_service.approve(plan))


@frappe.whitelist(methods=["POST"])
@endpoint()
def cancel(plan: str):
	_assert_manager()
	return ok(plan_service.cancel(plan))


@frappe.whitelist()
@endpoint()
def beats(field_user: str | None = None, territory: str | None = None):
	_assert_manager()
	return ok({"beats": plan_service.beats(field_user, territory=territory)})


@frappe.whitelist()
@endpoint()
def beat_options(field_user: str):
	"""The territories and distributors a beat for this rep may be set to."""
	_assert_manager()
	return ok(plan_service.beat_options(field_user))


@frappe.whitelist()
@endpoint()
def beat(name: str):
	_assert_manager()
	return ok(plan_service.beat(name))


@frappe.whitelist()
@endpoint()
def free_outlets(territory: str, q: str | None = None):
	"""Shops in a territory no active beat covers yet."""
	_assert_manager()
	return ok({"outlets": plan_service.free_outlets(territory, q)})


@frappe.whitelist(methods=["POST"])
@endpoint()
def save_beat(payload=None):
	_assert_manager()
	data = parse_json(payload, "payload") or {}
	if not isinstance(data, dict):
		raise FieldMateError(Err.BAD_REQUEST, "Send the beat as an object.")
	return ok(plan_service.save_beat(data))
