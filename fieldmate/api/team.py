"""A manager's phone: the team today, and the decisions waiting on them.

Area and Regional Managers have no Desk (they work from the app, like their reps), so every
decision they used to take in a Desk form has to be reachable from here. The two lists are live
reads scoped to the caller's reporting line; see `services/team.py`.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok
from fieldmate.services import field_user as field_user_service
from fieldmate.services import team as team_service


def _assert_manager() -> None:
	if not set(field_user_service.MANAGER_ROLES) & set(frappe.get_roles()):
		raise FieldMateError(Err.PERMISSION_DENIED, "That is a manager's view.")


@frappe.whitelist()
@endpoint()
def today(on_date: str | None = None):
	"""Every rep in the team, with where their day stands right now."""
	_assert_manager()
	return ok(team_service.today(on=on_date))


@frappe.whitelist()
@endpoint()
def inbox():
	"""Shops, orders, expenses and geo-fence exceptions waiting on this manager."""
	_assert_manager()
	return ok(team_service.inbox())


@frappe.whitelist(methods=["POST"])
@endpoint()
def decide_geo_fence(exception: str, decision: str, notes: str | None = None):
	_assert_manager()
	return ok(team_service.decide_geo_fence(exception, decision, notes))
