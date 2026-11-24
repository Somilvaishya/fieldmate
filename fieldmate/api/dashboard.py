"""What the phone and the Desk read. All of it from the KPI snapshot.

One endpoint is the exception and says so: `rep_today` measures the day live. The rep is standing
in a market looking at what they did in the last hour, and last night's row is the one number
they would immediately know to be wrong. Everything else - the month, the team, the charts -
reads the table (Gate 8 criterion 3).
"""

from __future__ import annotations

import frappe
from frappe.utils import add_days, get_first_day, get_last_day, getdate, nowdate

from fieldmate.api._base import Err, FieldMateError, endpoint, ok
from fieldmate.services import alerts as alerts_service
from fieldmate.services import field_user as field_user_service
from fieldmate.services import kpi as kpi_service
from fieldmate.services import paging

MANAGER_ROLES = ("FieldMate Area Manager", "FieldMate Regional Manager",
                 "FieldMate Sales Head", "FieldMate Admin", "System Manager")


def _me() -> str:
	mine = field_user_service.for_user()
	if not mine:
		raise FieldMateError(Err.PERMISSION_DENIED, "You are not set up as a field user.")
	return mine


def _assert_manager() -> None:
	if not set(MANAGER_ROLES) & set(frappe.get_roles()):
		raise FieldMateError(Err.PERMISSION_DENIED, "That is a manager's view.")


# --------------------------------------------------------------------------------------
# the rep
# --------------------------------------------------------------------------------------


@frappe.whitelist()
@endpoint()
def rep_today(on_date: str | None = None):
	"""The operational cockpit: where the day stands, right now.

	Measured live rather than read from the snapshot, because this is the one screen whose
	figures the rep can check against their own memory of the last hour.
	"""
	mine = _me()
	day = getdate(on_date or nowdate())
	measured = kpi_service.today_for(mine, day)

	rep = frappe.db.get_value("FieldMate Field User", mine,
	                          ["full_name", "territory"], as_dict=True) or frappe._dict()

	return ok({
		"field_user": mine,
		"full_name": rep.full_name,
		"date": str(day),
		"beat": measured.get("beat"),
		"day_started": bool(measured.get("day_started")),
		"day_closed": bool(measured.get("day_closed")),
		"visits": {
			"planned": measured.get("planned_visits"),
			"made": measured.get("actual_visits"),
			"productive": measured.get("productive_visits"),
			"remaining": max((measured.get("planned_visits") or 0)
			                 - (measured.get("actual_visits") or 0), 0),
			"strike_rate": measured.get("productive_pct"),
			"compliance": measured.get("visit_compliance_pct"),
		},
		"orders": {
			"count": measured.get("orders_count"),
			"value": measured.get("order_value"),
			"qty": measured.get("order_qty"),
			"lines": measured.get("order_lines"),
			"shops": measured.get("outlets_billed"),
		},
		"money": {
			"collected": measured.get("collection_amount"),
			"receipts": measured.get("collection_count"),
			"deposited": measured.get("deposited_amount"),
			# What is still in the satchel, which is the figure the rep is responsible for.
			"in_hand": (measured.get("collection_amount") or 0)
			           - (measured.get("deposited_amount") or 0),
		},
		"travel": {
			"distance_km": measured.get("distance_km"),
			"hours": measured.get("duration_hours"),
		},
	})


@frappe.whitelist()
@endpoint()
def rep_month(on_date: str | None = None, from_date: str | None = None,
              to_date: str | None = None):
	"""The month, read from the snapshot, with the nine named.

	Takes an explicit window as well as a date, because the screen has a month stepper on it and
	a caller asking for August should not have to know which day of August to send.
	"""
	mine = _me()
	if from_date and to_date:
		window = (getdate(from_date), getdate(to_date))
	else:
		anchor = getdate(on_date or nowdate())
		window = (get_first_day(anchor), get_last_day(anchor))

	result = kpi_service.period(mine, *window)
	totals = result["totals"]

	return ok({
		**result,
		"metrics": kpi_service.core_metrics(totals),
		"days_left": max((window[1] - getdate(nowdate())).days, 0)
		if window[0] <= getdate(nowdate()) <= window[1] else 0,
	})


@frappe.whitelist()
@endpoint()
def rep_trend(days: int = 14):
	"""A short run of daily rows, for a sparkline. Snapshot only."""
	mine = _me()
	to_date = getdate(nowdate())
	from_date = add_days(to_date, -(max(int(days), 1) - 1))
	return ok({"days": frappe.get_all(
		"FieldMate KPI Snapshot",
		filters={"field_user": mine, "snapshot_date": ["between", [from_date, to_date]]},
		fields=["snapshot_date", "order_value", "actual_visits", "productive_visits",
		        "collection_amount", "productive_pct"],
		order_by="snapshot_date asc", limit_page_length=0)})


# --------------------------------------------------------------------------------------
# the manager
# --------------------------------------------------------------------------------------


@frappe.whitelist()
@endpoint()
def manager_summary(sales_person: str | None = None, from_date: str | None = None,
                    to_date: str | None = None):
	"""Everybody under a node of the tree, ranked. Snapshot only.

	Without a sales person it resolves the caller's own, so a manager opening this does not have
	to know their node in a hierarchy somebody else maintains.
	"""
	_assert_manager()

	if not sales_person:
		mine = field_user_service.for_user()
		sales_person = frappe.db.get_value("FieldMate Field User", mine, "sales_person") \
			if mine else None
	if not sales_person:
		raise FieldMateError(
			Err.BAD_REQUEST,
			"No sales person to summarise. Say which one, or set one on your own profile.")

	_assert_my_branch(sales_person)

	anchor = getdate(to_date or nowdate())
	window = (getdate(from_date) if from_date else get_first_day(anchor), anchor)
	if window[0] > window[1]:
		raise FieldMateError(Err.BAD_REQUEST, "The start date is after the end date.")
	if (window[1] - window[0]).days > MAX_SUMMARY_DAYS:
		raise FieldMateError(Err.BAD_REQUEST, "At most a year at a time.")

	result = kpi_service.for_team(sales_person, *window)
	return ok({**result, "metrics": kpi_service.core_metrics(result["totals"])})


# One request reads every snapshot in the window for every rep under the node.
MAX_SUMMARY_DAYS = 366


def _assert_my_branch(sales_person: str) -> None:
	"""A manager summarises their own node of the tree or one below it, never a cousin's.

	Any Area Manager could pass the root and read every rep in the company (Phase 10 security
	pass). Sales Head and the office answer for everybody and are not narrowed.
	"""
	if field_user_service.team_scope() is None:
		return
	from fieldmate.services import target as target_service

	mine = field_user_service.for_user()
	own = frappe.db.get_value("FieldMate Field User", mine, "sales_person") if mine else None
	if not own or sales_person not in target_service.subtree(own):
		raise FieldMateError(Err.PERMISSION_DENIED, "That part of the team is not yours.")


@frappe.whitelist()
@endpoint()
def exceptions(limit: int = 50, field_user: str | None = None, start: int = 0):
	"""What fired recently. A manager sees the team; a rep sees only themselves."""
	start, limit = paging.window(start, limit)
	team = None
	if field_user or set(MANAGER_ROLES) & set(frappe.get_roles()):
		if field_user:
			_assert_manager()
			# Somebody else's rep is not yours to read, by name or otherwise (Phase 10).
			field_user_service.assert_in_team(field_user)
		else:
			# None for Sales Head and the office; the reporting line for everybody else. It used
			# to be None for every manager, which read the whole company's alert log.
			team = field_user_service.team_scope()
		whose = field_user
	else:
		# A rep asking is always asking about themselves, whatever they put in the argument.
		whose = _me()
	rows, total = alerts_service.recent_page(limit=limit, field_user=whose, start=start,
	                                         field_users=team)
	return ok({"alerts": rows, **paging.envelope(rows, total, start, limit)})


# --------------------------------------------------------------------------------------
# running the machinery by hand
# --------------------------------------------------------------------------------------


# The most these two will do in one request. They are the nightly jobs, run inside a web request
# that commits per rep: `2000-01-01 .. today` was ten thousand days for every rep in the company,
# open to any Area Manager (Phase 10 security pass). A month is what a manager ever needs to
# restate; anything longer is a `bench execute` for somebody with the server.
MAX_MACHINERY_DAYS = 31


def _window_days(from_date, to_date) -> int:
	days = (getdate(to_date) - getdate(from_date)).days + 1
	if days < 1:
		raise FieldMateError(Err.BAD_REQUEST, "The start date is after the end date.")
	if days > MAX_MACHINERY_DAYS:
		raise FieldMateError(
			Err.BAD_REQUEST,
			f"At most {MAX_MACHINERY_DAYS} days at a time. Run a longer stretch month by month.")
	return days


def _assert_company_wide() -> None:
	if not set(field_user_service.COMPANY_WIDE_ROLES) & set(frappe.get_roles()) \
			and frappe.session.user != "Administrator":
		raise FieldMateError(
			Err.PERMISSION_DENIED, "Only the Sales Head or an admin can run this for everybody.")


@frappe.whitelist(methods=["POST"])
@endpoint()
def rebuild(from_date: str, to_date: str, field_user: str | None = None, force: int = 0):
	"""Recompute snapshots for a window. The nightly job, on demand.

	For one rep, any manager whose team they are in. For the whole company, only the roles that
	answer for the whole company.
	"""
	_assert_manager()
	days = _window_days(from_date, to_date)
	force = bool(frappe.utils.cint(force))
	if field_user:
		field_user_service.assert_in_team(field_user)
		return ok(kpi_service.roll_up_range(field_user, from_date, to_date, force=force))

	_assert_company_wide()
	return ok(kpi_service.roll_up_all(on_date=to_date, days_back=days, force=force))


@frappe.whitelist(methods=["POST"])
@endpoint()
def run_alerts(on_date: str | None = None, days_back: int = 1):
	"""Every rule over every rep, so company-wide roles only, and a month at most."""
	_assert_company_wide()
	days_back = frappe.utils.cint(days_back)
	if not 1 <= days_back <= MAX_MACHINERY_DAYS:
		raise FieldMateError(
			Err.BAD_REQUEST, f"days_back must be between 1 and {MAX_MACHINERY_DAYS}.")
	return ok(alerts_service.evaluate_all(on_date=on_date, days_back=days_back))
