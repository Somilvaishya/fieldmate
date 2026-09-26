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

	anchor = getdate(to_date or nowdate())
	window = (getdate(from_date) if from_date else get_first_day(anchor), anchor)

	result = kpi_service.for_team(sales_person, *window)
	return ok({**result, "metrics": kpi_service.core_metrics(result["totals"])})


@frappe.whitelist()
@endpoint()
def exceptions(limit: int = 50, field_user: str | None = None):
	"""What fired recently. A manager sees the team; a rep sees only themselves."""
	if field_user or set(MANAGER_ROLES) & set(frappe.get_roles()):
		if field_user:
			_assert_manager()
		return ok({"alerts": alerts_service.recent(limit=int(limit), field_user=field_user)})
	return ok({"alerts": alerts_service.recent(limit=int(limit), field_user=_me())})


# --------------------------------------------------------------------------------------
# running the machinery by hand
# --------------------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
@endpoint()
def rebuild(from_date: str, to_date: str, field_user: str | None = None, force: int = 0):
	"""Recompute snapshots for a window. The nightly job, on demand."""
	_assert_manager()
	force = bool(frappe.utils.cint(force))
	if field_user:
		return ok(kpi_service.roll_up_range(field_user, from_date, to_date, force=force))

	days = (getdate(to_date) - getdate(from_date)).days + 1
	return ok(kpi_service.roll_up_all(on_date=to_date, days_back=max(days, 1), force=force))


@frappe.whitelist(methods=["POST"])
@endpoint()
def run_alerts(on_date: str | None = None, days_back: int = 1):
	_assert_manager()
	return ok(alerts_service.evaluate_all(on_date=on_date, days_back=int(days_back)))
