"""The Desk end of a season's allocation.

Thin, like every other facade in this app: the arithmetic is `services/allocation` and the
reservations are ERPNext's. These three methods exist to be called from a page and to check who
is asking before they call it.

**Not in `fieldmate.api`.** That package is the phone's facade - device-authenticated, versioned,
and shaped for a rep standing in a market. Allocating a season is a desk job done by somebody
looking at a whole season at once, and giving it a device-bound endpoint would be a lie about who
uses it.
"""

import frappe

from fieldmate.services import allocation as allocation_service

# Who may divide short stock between distributors. Not an area manager: this is a decision about
# one territory at the expense of another, and the person making it has to be able to see both.
ALLOWED = ("System Manager", "FieldMate Admin", "FieldMate Sales Head")


def _assert_allowed() -> None:
	if not set(frappe.get_roles()) & set(ALLOWED):
		frappe.throw(
			frappe._("Allocating a season decides which distributor is served short. Only {0} "
			         "can do that.").format(", ".join(ALLOWED)),
			frappe.PermissionError,
		)


@frappe.whitelist()
def seasons():
	"""Seasons with released bookings against them. Nothing to allocate without one."""
	_assert_allowed()
	return allocation_service.seasons_worth_allocating()


@frappe.whitelist()
def preview(season: str, rule: str = allocation_service.ADVANCE_FIRST):
	"""What each booking would get. Changes nothing, and is the same arithmetic as `apply`."""
	_assert_allowed()
	return allocation_service.preview(season, rule)


@frappe.whitelist()
def apply(season: str, rule: str = allocation_service.ADVANCE_FIRST):
	"""Reserve what the preview says, in ERPNext. The reservations are the record."""
	_assert_allowed()
	return allocation_service.apply(season, rule)


@frappe.whitelist()
def revert(season: str):
	"""Give it all back so the season can be allocated again."""
	_assert_allowed()
	return allocation_service.revert(season)


@frappe.whitelist()
def held(season: str):
	"""What this season is holding right now, read back from ERPNext rather than from us."""
	_assert_allowed()
	return allocation_service.held_by(season)
