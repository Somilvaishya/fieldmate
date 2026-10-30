"""Field users, and the row-level access that follows from them.

Territory scoping is the security boundary of the whole app: it is what stops a rep in one
district reading another district's outlets, prices and customers. It is enforced with Frappe's
own `User Permission` rather than custom permission code, so it applies uniformly to the API,
the Desk, reports and exports — anywhere a query runs — instead of only where we remembered to
add a filter.
"""

from __future__ import annotations

import frappe

MARKER = "FieldMate territory scope"


def call_target(field_user: str, on=None) -> dict:
	"""How many shops this rep is expected to reach today, and where that number came from.

	**The route answers first.** A journey plan already says which beat is walked today and how
	many shops are on it, so on a planned day the honest target is a fact rather than a figure
	somebody typed once. It moves with the plan: a short beat on Thursday asks for less than a long
	one on Monday, which a flat number can never say.

	The field on the Field User is the fallback, for a day with no plan or a site that works to a
	flat expectation. It used to be the only answer, and it shipped with a default of 25 - so every
	rep on every site was asked for 25 calls a day whether their beat held 12 shops or 60, and
	nobody had chosen that.

	`None` where there is neither. Better a dash on the screen than a number nobody stands behind.
	"""
	from fieldmate.services import journey as journey_service

	planned = journey_service.day_for(field_user, on or frappe.utils.nowdate()) or {}
	if planned.get("is_working_day") and frappe.utils.cint(planned.get("outlet_count")):
		return {
			"daily_target_calls": frappe.utils.cint(planned["outlet_count"]),
			"daily_target_basis": "route",
			"daily_target_beat": planned.get("beat_name") or planned.get("beat"),
		}

	typed = frappe.utils.cint(
		frappe.db.get_value("FieldMate Field User", field_user, "daily_target_calls"))
	return {
		"daily_target_calls": typed or None,
		"daily_target_basis": "profile" if typed else None,
		"daily_target_beat": None,
	}


def for_user(user: str | None = None) -> str | None:
	"""The FieldMate Field User record for a login, if there is one."""
	user = user or frappe.session.user
	return frappe.db.get_value("FieldMate Field User", {"user": user}, "name")


def get(user: str | None = None):
	name = for_user(user)
	return frappe.get_doc("FieldMate Field User", name) if name else None


def territory_of(user: str | None = None) -> str | None:
	name = for_user(user)
	return frappe.db.get_value("FieldMate Field User", name, "territory") if name else None


def sync_territory_permission(doc) -> None:
	"""Make the User Permission match the record, whatever state it was in before.

	Rewritten rather than patched: a stale permission is a rep quietly reading a territory they
	were moved out of months ago.
	"""
	clear_territory_permission(doc.user)

	# Inactive staff keep their history but lose their access.
	if doc.status != "Active":
		return

	frappe.get_doc({
		"doctype": "User Permission",
		"user": doc.user,
		"allow": "Territory",
		"for_value": doc.territory,
		# Territory is a tree. Leaving descendants visible is what lets a manager sit on a parent
		# node and see every area beneath it without a row per area.
		"hide_descendants": 0,
		"apply_to_all_doctypes": 1,
		"is_default": 1,
	}).insert(ignore_permissions=True)


def clear_territory_permission(user: str) -> None:
	for name in frappe.get_all(
		"User Permission", filters={"user": user, "allow": "Territory"}, pluck="name"
	):
		frappe.delete_doc("User Permission", name, force=True, ignore_permissions=True)


def touch(user: str | None = None) -> None:
	"""Record that this rep did something, without a full save."""
	name = for_user(user)
	if name:
		frappe.db.set_value(
			"FieldMate Field User", name, "last_active_on", frappe.utils.now_datetime(),
			update_modified=False,
		)


def profile(user: str | None = None) -> dict:
	"""What the app needs to know about who is signed in. Plain dict, no document leaks."""
	doc = get(user)
	if not doc:
		return {}
	from fieldmate.services import settings as settings_service

	return {
		"field_user": doc.name,
		"designation": doc.designation,
		"status": doc.status,
		"territory": doc.territory,
		"distributor": doc.distributor,
		"company": doc.company,
		"price_list": doc.default_price_list or settings_service.value("default_price_list"),
		"sales_mode": settings_service.resolve_sales_mode(doc.name),
		"can_create_outlet": bool(doc.can_create_outlet),
		"can_collect_payment": bool(doc.can_collect_payment),
		# Both the number and where it came from, because "25 calls" and "25 shops are on your
		# route today" are different claims and a rep can only act on the second.
		**call_target(doc.name),
	}


# --------------------------------------------------------------------------------------
# what is a rep's own — targets, achievement, incentive
# --------------------------------------------------------------------------------------
#
# Territory scoping (above) answers "which shops", and User Permission enforces it everywhere.
# It cannot answer "whose target", because a target belongs to a person rather than to a place
# and two reps routinely share a territory.
#
# So Phase 7 adds a second, narrower rule for the three DocTypes that carry somebody's own
# numbers: a Field Rep sees the rows that name them, and nobody else's. Applied through the
# framework hooks rather than in each API, for the reason ADR-027 gives - the service layer only
# covers the screens we wrote, and these rows are worth protecting from the ones we did not.
# Everybody above a rep keeps the full view: a manager who cannot see their team's numbers has
# no job to do.

MANAGER_ROLES = ("FieldMate Area Manager", "FieldMate Regional Manager",
                 "FieldMate Sales Head", "FieldMate Admin", "System Manager")


def rep_only(user: str | None = None) -> str | None:
	"""The Field User a session is limited to, or None for anyone not limited at all."""
	user = user or frappe.session.user
	if user in ("Guest", "Administrator"):
		return None
	roles = set(frappe.get_roles(user))
	if not roles & {"FieldMate Field Rep"} or roles & set(MANAGER_ROLES):
		return None
	return for_user(user)


def own_rows_query(doctype: str, user: str | None = None) -> str:
	mine = rep_only(user)
	if not mine:
		return ""
	return f"`tab{doctype}`.field_user = {frappe.db.escape(mine)}"


def own_row(doc, user: str | None = None) -> bool:
	mine = rep_only(user)
	if not mine:
		return True
	# A plan above the leaves carries no field_user at all. A rep has no business reading the
	# region's number, so an unowned row is refused rather than shared.
	return getattr(doc, "field_user", None) == mine


def managers_of(field_user: str) -> list[str]:
	"""Everyone above this rep in the reporting line, nearest first.

	Walked rather than assumed to be one level: an order a rep's own area manager is away from
	should still be decidable by the regional manager above them, without anybody re-pointing
	`reports_to` for an afternoon.

	Loop-safe. The DocType refuses a cycle on save, but a chain that hangs the approval of an
	order is a worse failure than one that stops early.
	"""
	chain, current, seen = [], field_user, {field_user}
	while True:
		current = frappe.db.get_value("FieldMate Field User", current, "reports_to")
		if not current or current in seen:
			return chain
		seen.add(current)
		chain.append(current)


# Roles that answer for the whole company rather than for a team. The same three that may decide
# any order (`order.APPROVER_ROLES`): a Sales Head sits above every reporting line, and an
# administrator has no line at all.
COMPANY_WIDE_ROLES = ("FieldMate Sales Head", "FieldMate Admin", "System Manager")


def team_of(field_user: str) -> list[str]:
	"""Everyone below this person in the reporting line, at any depth. `managers_of` reversed.

	The same line an order's approval walks up, so the people a manager sees in the app are
	exactly the people whose orders they may decide - one definition, not two that drift.

	Loop-safe for the same reason `managers_of` is.
	"""
	team, frontier, seen = [], [field_user], {field_user}
	while frontier:
		below = frappe.get_all("FieldMate Field User",
		                       filters={"reports_to": ["in", frontier]}, pluck="name")
		frontier = [name for name in below if name not in seen]
		seen.update(frontier)
		team.extend(frontier)
	return team


def team_scope(user: str | None = None) -> list[str] | None:
	"""The field users a manager answers for, or None for somebody who answers for all of them.

	An empty list is a real answer, not "everyone": a manager nobody reports to yet has a team of
	nobody, and must see nothing rather than the whole company.
	"""
	user = user or frappe.session.user
	if user == "Administrator" or set(frappe.get_roles(user)) & set(COMPANY_WIDE_ROLES):
		return None
	mine = for_user(user)
	return team_of(mine) if mine else []


def assert_in_team(field_user: str, user: str | None = None) -> None:
	"""Refuse a decision about somebody outside the caller's reporting line."""
	scope = team_scope(user)
	if scope is not None and field_user not in scope:
		frappe.throw(frappe._("{0} is not in your team.").format(field_user),
		             frappe.PermissionError)


def location_trail_query(user: str | None = None) -> str:
	"""A rep's own trail, and nobody else's.

	This is the only one of these that is about a person rather than a number. A GPS trail is
	where somebody was all day, minute by minute - the most personal thing the app records, and
	the thing the DPDP consent was taken for. The Field Rep role held a plain `read` on the
	DocType with no `if_owner` and no query condition, so any rep could list any colleague's
	movements by name.

	Managers are not scoped here, for the same reason they are not scoped on targets or KPIs:
	seeing their reps' work is the job. What is refused is rep reading rep.
	"""
	return own_rows_query("FieldMate Location Trail", user)


def target_plan_query(user: str | None = None) -> str:
	return own_rows_query("FieldMate Target Plan", user)


def achievement_query(user: str | None = None) -> str:
	return own_rows_query("FieldMate Achievement", user)


def incentive_payout_query(user: str | None = None) -> str:
	return own_rows_query("FieldMate Incentive Payout", user)


def expense_claim_query(user: str | None = None) -> str:
	return own_rows_query("FieldMate Expense Claim", user)


def kpi_snapshot_query(user: str | None = None) -> str:
	return own_rows_query("FieldMate KPI Snapshot", user)


def own_row_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
	return own_row(doc, user)
