"""A manager's day: who is out, how far they have got, and what is waiting on a decision.

Everything here is read **live**, unlike `kpi.for_team`, which reads last night's snapshot. The
two answer different questions. The snapshot is the month and the ranking, and must be one number
everybody agrees on; this is "Ravi has not started his day and it is ten o'clock", which is
useless by tomorrow.

Who counts as the team is `field_user.team_scope` - the reporting line an order's approval walks
up - so the people on this board are exactly the people whose orders the manager may decide.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, nowdate

from fieldmate.services import field_user as field_user_service

# The kinds of thing a manager decides from the phone, in the order the inbox shows them: a shop
# that cannot be sold to yet, an order a distributor is waiting on, money a rep is owed, and a
# check-in that needs excusing.
INBOX_KINDS = ("outlets", "orders", "expenses", "geo_fence")

INBOX_LIMIT = 50


def _members(scope: list[str] | None) -> list[dict]:
	filters = {"status": "Active"}
	if scope is not None:
		filters["name"] = ["in", scope]
	return frappe.get_all("FieldMate Field User", filters=filters,
	                      fields=["name", "full_name", "designation", "territory",
	                              "reports_to", "last_active_on", "mobile_no"],
	                      order_by="full_name asc", limit_page_length=0)


def today(user: str | None = None, on: str | None = None) -> dict:
	"""Every rep in the caller's team, with where their day stands right now."""
	on = on or nowdate()
	scope = field_user_service.team_scope(user)
	if scope is not None and not scope:
		return {"date": on, "members": [], "totals": _totals([])}

	members = _members(scope)
	names = [m.name for m in members]
	if not names:
		return {"date": on, "members": [], "totals": _totals([])}

	days = {d.field_user: d for d in frappe.get_all(
		"FieldMate Day", filters={"field_user": ["in", names], "day_date": on, "docstatus": ["<", 2]},
		fields=["field_user", "status", "start_time", "end_time", "planned_beat"])}

	visits: dict[str, dict] = {}
	for v in frappe.get_all(
			"FieldMate Visit", filters={"field_user": ["in", names], "visit_date": on,
			                            "docstatus": ["<", 2]},
			fields=["field_user", "visit_outcome", "check_in_time"]):
		row = visits.setdefault(v.field_user, {"visits": 0, "productive": 0, "last_check_in": None})
		row["visits"] += 1
		if v.visit_outcome == "Order Taken":
			row["productive"] += 1
		if v.check_in_time and (not row["last_check_in"] or v.check_in_time > row["last_check_in"]):
			row["last_check_in"] = v.check_in_time

	orders: dict[str, dict] = {}
	for o in frappe.get_all(
			"FieldMate Order", filters={"field_user": ["in", names], "order_date": on,
			                            "docstatus": 1,
			                            "order_status": ["not in", ["Cancelled", "Rejected"]]},
			fields=["field_user", "grand_total"]):
		row = orders.setdefault(o.field_user, {"orders": 0, "order_value": 0.0})
		row["orders"] += 1
		row["order_value"] += flt(o.grand_total)

	out = []
	for m in members:
		day = days.get(m.name)
		v = visits.get(m.name, {})
		o = orders.get(m.name, {})
		target = field_user_service.call_target(m.name, on)
		out.append({
			"field_user": m.name,
			"full_name": m.full_name or m.name,
			"designation": m.designation,
			"territory": m.territory,
			"mobile_no": m.mobile_no,
			"day_status": _day_status(day),
			"started_at": str(day.start_time) if day and day.start_time else None,
			"ended_at": str(day.end_time) if day and day.end_time else None,
			"beat": (day.planned_beat if day else None) or target.get("daily_target_beat"),
			"planned_calls": cint(target.get("daily_target_calls")),
			"visits": cint(v.get("visits")),
			"productive": cint(v.get("productive")),
			"orders": cint(o.get("orders")),
			"order_value": flt(o.get("order_value")),
			"last_check_in": str(v["last_check_in"]) if v.get("last_check_in") else None,
			"last_active_on": str(m.last_active_on) if m.last_active_on else None,
		})

	# Who needs a call first: nobody out yet, then the day running, then the day done. Inside each,
	# least done first - the manager opens this to find the rep who is behind, not to admire the
	# one who is ahead.
	rank = {"Not Started": 0, "Working": 1, "Ended": 2}
	out.sort(key=lambda r: (rank[r["day_status"]], r["visits"], r["full_name"]))

	return {"date": on, "members": out, "totals": _totals(out)}


def _day_status(day) -> str:
	if not day:
		return "Not Started"
	return "Working" if day.status == "Open" else "Ended"


def _totals(rows: list[dict]) -> dict:
	return {
		"members": len(rows),
		"started": sum(1 for r in rows if r["day_status"] != "Not Started"),
		"not_started": sum(1 for r in rows if r["day_status"] == "Not Started"),
		"visits": sum(r["visits"] for r in rows),
		"planned_calls": sum(r["planned_calls"] for r in rows),
		"productive": sum(r["productive"] for r in rows),
		"orders": sum(r["orders"] for r in rows),
		"order_value": sum(r["order_value"] for r in rows),
	}


# --------------------------------------------------------------------------------------
# the inbox
# --------------------------------------------------------------------------------------


def inbox(user: str | None = None) -> dict:
	"""Everything waiting on this manager, by kind, oldest first, with a count of each."""
	user = user or frappe.session.user
	scope = field_user_service.team_scope(user)
	if scope is not None and not scope:
		return {"counts": dict.fromkeys(INBOX_KINDS, 0), "total": 0,
		        **{kind: [] for kind in INBOX_KINDS}}

	def team(filters: dict, field: str = "field_user") -> dict:
		if scope is not None:
			filters[field] = ["in", scope]
		return filters

	outlets = frappe.get_all(
		"FieldMate Outlet",
		filters=team({"approval_status": "Pending Approval"}, field="created_by_rep"),
		fields=["name", "outlet_name", "owner_name", "mobile_no", "territory", "city",
		        "channel", "created_by_rep", "onboarding_date", "latitude", "longitude",
		        "shop_photo", "creation"],
		order_by="creation asc", limit_page_length=INBOX_LIMIT)

	orders = frappe.get_all(
		"FieldMate Order",
		filters=team({"approval_status": "Pending", "docstatus": 1,
		              "order_status": "Pending Approval"}),
		fields=["name", "field_user", "outlet", "customer", "order_date", "grand_total",
		        "total_lines", "credit_status", "credit_limit_at_order", "outstanding_at_order",
		        "approval_rule", "creation"],
		order_by="creation asc", limit_page_length=INBOX_LIMIT)

	from fieldmate.services import expense as expense_service

	expenses, _ = expense_service.pending_for_manager_page(limit=INBOX_LIMIT, user=user)

	fences = frappe.get_all(
		"FieldMate Geo Fence Exception",
		filters=team({"status": "Pending", "docstatus": 0}),
		fields=["name", "field_user", "outlet", "exception_date", "distance_m", "accuracy_m",
		        "reason", "creation"],
		order_by="creation asc", limit_page_length=INBOX_LIMIT)

	# The names a phone shows, resolved once rather than one lookup per row.
	people = _names("FieldMate Field User", "full_name",
	                {r.get("field_user") or r.get("created_by_rep")
	                 for r in [*outlets, *orders, *expenses, *fences]})
	shops = _names("FieldMate Outlet", "outlet_name",
	               {r.get("outlet") for r in [*orders, *fences]})
	for r in [*outlets, *orders, *expenses, *fences]:
		who = r.get("field_user") or r.get("created_by_rep")
		r["rep_name"] = people.get(who, who)
		if r.get("outlet"):
			r["outlet_name"] = shops.get(r["outlet"], r["outlet"])

	result = {"outlets": outlets, "orders": orders, "expenses": expenses, "geo_fence": fences}
	counts = {kind: len(result[kind]) for kind in INBOX_KINDS}
	return {"counts": counts, "total": sum(counts.values()), **result}


def _names(doctype: str, field: str, names: set) -> dict:
	names = {n for n in names if n}
	if not names:
		return {}
	return dict(frappe.get_all(doctype, filters={"name": ["in", list(names)]},
	                           fields=["name", field], as_list=True))


# --------------------------------------------------------------------------------------
# the geo-fence decision
# --------------------------------------------------------------------------------------


def decide_geo_fence(name: str, decision: str, notes: str | None = None,
                     user: str | None = None) -> dict:
	"""Excuse a check-in made outside a shop's fence, or refuse to.

	Until now this was a Desk-only act: set the status, then submit. The phone does both in one
	call, held to the same team line as every other decision a manager makes from it.
	"""
	if decision not in ("Approved", "Rejected"):
		frappe.throw(frappe._("A geo-fence exception is either Approved or Rejected."))

	user = user or frappe.session.user
	doc = frappe.get_doc("FieldMate Geo Fence Exception", name)
	if doc.docstatus != 0 or doc.status != "Pending":
		frappe.throw(frappe._("This exception has already been decided."))
	if doc.field_user == field_user_service.for_user(user):
		frappe.throw(frappe._("You cannot excuse your own check-in."), frappe.PermissionError)
	field_user_service.assert_in_team(doc.field_user, user)
	if decision == "Rejected" and not notes:
		frappe.throw(frappe._("Say why. A refused exception with no reason is a grievance."))

	doc.status = decision
	if notes:
		doc.decision_notes = notes
	doc.flags.ignore_permissions = True
	doc.submit()
	return {"name": doc.name, "status": doc.status, "approved_by": doc.approved_by,
	        "decided_on": str(doc.decided_on)}
