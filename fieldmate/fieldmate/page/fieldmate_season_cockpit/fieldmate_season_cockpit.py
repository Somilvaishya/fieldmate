"""The Desk end of the season cockpit. Reads, and nothing else.

Every figure behind these methods is read from the documents that hold it — the booking, the
reservations ERPNext holds, the Delivery Notes, the invoices, the collections. There is nothing
here to write, which is also why this page is safe to leave open and refresh.

A wider audience than the allocation page: an area manager cannot decide who is served short, but
they can certainly be asked why their distributor has not paid.
"""

import frappe

from fieldmate.services import cockpit as cockpit_service

VIEWERS = (
	"System Manager",
	"FieldMate Admin",
	"FieldMate Sales Head",
	"FieldMate Regional Manager",
	"FieldMate Area Manager",
	"FieldMate Dispatch Planner",
)


def _assert_may_view() -> None:
	if not set(frappe.get_roles()) & set(VIEWERS):
		frappe.throw(
			frappe._("A season's book is commercial information. Only {0} can read it.")
			.format(", ".join(VIEWERS)),
			frappe.PermissionError,
		)


# Who sees the whole season. Everybody else in VIEWERS - an Area or Regional Manager - sees the
# bookings of their own reporting line and nobody else's: a distributor's debts in another region
# are not theirs to chase (Phase 10 security pass).
WHOLE_SEASON = ("System Manager", "FieldMate Admin", "FieldMate Sales Head",
                "FieldMate Dispatch Planner")


def _team() -> list[str] | None:
	if frappe.session.user == "Administrator" or set(frappe.get_roles()) & set(WHOLE_SEASON):
		return None
	from fieldmate.services import field_user as field_user_service

	scope = field_user_service.team_scope() or []
	me = field_user_service.for_user()
	return scope + ([me] if me else [])


@frappe.whitelist()
def seasons(company: str | None = None):
	"""Seasons worth opening, newest festival first."""
	_assert_may_view()
	return cockpit_service.seasons(company)


@frappe.whitelist()
def summary(season: str):
	"""The whole cockpit in one call, so the page makes one request rather than four."""
	_assert_may_view()
	return cockpit_service.summary(season, _team())


@frappe.whitelist()
def overdue(season: str | None = None):
	"""Who is late, newest-overdue first. The list this page is usually opened for."""
	_assert_may_view()
	rows = cockpit_service.overdue_payments(field_users=_team())
	return [row for row in rows if not season or row["season"] == season]
