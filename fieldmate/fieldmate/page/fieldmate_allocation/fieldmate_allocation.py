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
from fieldmate.services import dispatch as dispatch_service

# Who may divide short stock between distributors. Not an area manager: this is a decision about
# one territory at the expense of another, and the person making it has to be able to see both.
ALLOWED = ("System Manager", "FieldMate Admin", "FieldMate Sales Head")

# Who may send the goods. A superset, because a dispatch planner carries out the allocation
# somebody else decided - they load vans, they do not choose who is served short.
DISPATCHERS = (*ALLOWED, "FieldMate Dispatch Planner")


def _assert_allowed() -> None:
	if not set(frappe.get_roles()) & set(ALLOWED):
		frappe.throw(
			frappe._("Allocating a season decides which distributor is served short. Only {0} "
			         "can do that.").format(", ".join(ALLOWED)),
			frappe.PermissionError,
		)


def _assert_may_dispatch() -> None:
	if not set(frappe.get_roles()) & set(DISPATCHERS):
		frappe.throw(
			frappe._("Dispatching a season takes stock out of the warehouse. Only {0} can do "
			         "that.").format(", ".join(DISPATCHERS)),
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


# --------------------------------------------------------------------------------------
# dispatch — the other half of the same screen
# --------------------------------------------------------------------------------------
#
# Here rather than on a page of its own because a planner looking at a season wants both answers
# at once: what each booking was given, and how much of it has actually gone. Two pages would mean
# allocating on one and finding out on the other.


@frappe.whitelist()
def position(season: str):
	"""Booked, held, shipped, billed — every one read back from the documents themselves."""
	_assert_may_dispatch()
	return dispatch_service.position(season)


@frappe.whitelist()
def ready(season: str):
	"""The bookings with stock held against them, waiting to go."""
	_assert_may_dispatch()
	return dispatch_service.ready(season)


@frappe.whitelist()
def deliver(season: str, orders=None, posting_date=None):
	"""Ship what is held. One submitted Delivery Note per booking."""
	_assert_may_dispatch()
	if isinstance(orders, str):
		orders = frappe.parse_json(orders)
	return dispatch_service.deliver(season, orders=orders, posting_date=posting_date)


@frappe.whitelist()
def invoice(season: str):
	"""Bill what has shipped. One submitted Sales Invoice per Delivery Note."""
	_assert_may_dispatch()
	return dispatch_service.invoice(season)


@frappe.whitelist()
def trip(season: str, on: str, vehicle: str, departure_time: str):
	"""Group the season's Delivery Notes into one draft Delivery Trip."""
	_assert_may_dispatch()
	return dispatch_service.trip(season, on, vehicle, departure_time)
