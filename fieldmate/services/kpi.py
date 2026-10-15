"""The materialised KPI table, and the nine numbers everything else reads.

One rule holds the phase together: **nothing downstream counts a visit or an order for itself.**
Charts, reports, the manager's summary and the rep's phone all read `FieldMate KPI Snapshot`.
That is Gate 8 criterion 3, and it is not only about speed - two places counting "productive
calls" from raw documents is two places that will eventually disagree, and the argument is
unwinnable because each is right according to its own query.

Daily grain. A month is a set of daily rows added up, so a visit corrected three weeks late
restates the month by recomputing one row. That is criterion 4, and it falls out of the shape
rather than needing machinery.

The one thing that does NOT simply add up is a ratio. Averaging thirty daily strike rates gives
the average of ratios; what anybody means is the ratio of totals. So every ratio is stored with
both its halves, and `aggregate()` re-divides the sums rather than averaging the percentages.
"""

from __future__ import annotations

import hashlib
import json

import frappe
from frappe.utils import cint, flt, get_first_day, get_last_day, getdate, now_datetime, nowdate

from fieldmate.fieldmate.doctype.fieldmate_kpi_snapshot.fieldmate_kpi_snapshot import (
	CORE_METRICS,
	RATIO_METRICS,
)

# An order in one of these never happened, as far as any number here is concerned. A cancelled
# order that still counted would let a rep book, take the credit, and cancel next month.
DEAD_ORDER_STATES = ("Cancelled", "Rejected")

# Percentages are capped for display only where they are genuinely bounded. Coverage above 100
# means a rep billed a shop outside their own territory, which is worth seeing rather than
# clipping, so nothing here caps anything - the raw ratio is stored and the screen decides.


def pct(numerator, denominator) -> float:
	"""A percentage, or zero where there is no base.

	Zero rather than None because every consumer would otherwise have to decide what a missing
	percentage looks like, and they would decide differently. Where the difference matters, the
	denominator is on the row beside it: a strike rate of 0% over 0 calls and over 12 calls are
	not the same fact, and `outlets_in_scope`, `actual_visits` and `billable_base` are stored so
	a reader can tell them apart.
	"""
	denominator = flt(denominator)
	if not denominator:
		return 0.0
	return round(flt(numerator) / denominator * 100, 2)


def ratio(numerator, denominator, places: int = 2) -> float:
	denominator = flt(denominator)
	if not denominator:
		return 0.0
	return round(flt(numerator) / denominator, places)


# --------------------------------------------------------------------------------------
# counting one rep-day
# --------------------------------------------------------------------------------------


def measure(field_user: str, on_date) -> dict:
	"""Count one rep's day from the documents. No document is written here.

	Deliberately a plain function over plain queries: Gate 8 criterion 1 asks that every metric
	be reproducible by hand for a rep-week, and a reader checking that has to be able to see
	exactly which rows were counted.
	"""
	on_date = getdate(on_date)
	rep = frappe.db.get_value(
		"FieldMate Field User", field_user,
		["territory", "sales_person", "company"], as_dict=True) or frappe._dict()

	visits = frappe.get_all(
		"FieldMate Visit",
		filters={"field_user": field_user, "visit_date": on_date, "docstatus": 1},
		fields=["name", "outlet", "is_planned", "is_deviation", "duration_minutes",
		        "is_short_visit", "is_geo_fence_breach", "order_value", "lines_sold",
		        "check_in_time", "beat"],
		limit_page_length=0,
	)

	orders = frappe.get_all(
		"FieldMate Order",
		filters={"field_user": field_user, "order_date": on_date, "docstatus": 1,
		         "order_status": ["not in", DEAD_ORDER_STATES]},
		fields=["name", "outlet", "net_total", "total_qty", "total_lines"],
		limit_page_length=0,
	)

	day_start = frappe.db.get_value(
		"FieldMate Day Start", {"field_user": field_user, "day_date": on_date, "docstatus": 1},
		["name", "planned_beat", "journey_plan"], as_dict=True)
	day_end = frappe.db.get_value(
		"FieldMate Day End", {"field_user": field_user, "day_date": on_date, "docstatus": 1},
		["name", "duration_hours", "distance_km", "planned_visits"], as_dict=True)

	collections = frappe.get_all(
		"FieldMate Collection",
		filters={"field_user": field_user, "collection_date": on_date, "docstatus": 1,
		         "status": ["not in", ("Cancelled", "Bounced")]},
		fields=["name", "amount"],
		limit_page_length=0,
	)
	deposited = frappe.get_all(
		"FieldMate Collection Deposit",
		filters={"field_user": field_user, "deposit_date": on_date, "docstatus": 1,
		         "status": ["in", ("Declared", "Confirmed")]},
		fields=["total_amount"],
		limit_page_length=0,
	)

	# Productive is decided by the value the server computed, never by the outcome the rep
	# chose. A rep who selects "Order Taken" and books nothing is the case this catches.
	productive = [v for v in visits if flt(v.order_value) > 0]
	timed = [flt(v.duration_minutes) for v in visits if flt(v.duration_minutes)]
	stamps = sorted(v.check_in_time for v in visits if v.check_in_time)

	planned = cint(day_end.planned_visits) if day_end else _planned_for(field_user, on_date)
	in_scope = _outlets_in_scope(rep.territory)
	billable = _billable_base(field_user, on_date, orders)

	row = {
		"field_user": field_user,
		"snapshot_date": on_date,
		"territory": rep.territory,
		"sales_person": rep.sales_person,
		"company": rep.company,
		"beat": (day_start.planned_beat if day_start else None)
		        or (visits[0].beat if visits else None),

		"day_started": 1 if day_start else 0,
		"day_closed": 1 if day_end else 0,
		"duration_hours": flt(day_end.duration_hours) if day_end else 0,
		"distance_km": flt(day_end.distance_km) if day_end else 0,
		"first_visit_at": stamps[0] if stamps else None,
		"last_visit_at": stamps[-1] if stamps else None,

		"planned_visits": planned,
		"actual_visits": len(visits),
		"productive_visits": len(productive),
		"unplanned_visits": sum(1 for v in visits if not cint(v.is_planned)),
		"short_visits": sum(1 for v in visits if cint(v.is_short_visit)),
		"geo_breach_visits": sum(1 for v in visits if cint(v.is_geo_fence_breach)),
		"avg_visit_minutes": round(sum(timed) / len(timed), 1) if timed else 0,

		"orders_count": len(orders),
		"order_value": sum(flt(o.net_total) for o in orders),
		"order_qty": sum(flt(o.total_qty) for o in orders),
		"order_lines": sum(cint(o.total_lines) for o in orders),
		"distinct_skus": _distinct_skus([o.name for o in orders]),
		"outlets_billed": len({o.outlet for o in orders if o.outlet}),
		"new_outlets": _new_outlets(field_user, on_date),

		"collection_amount": sum(flt(c.amount) for c in collections),
		"collection_count": len(collections),
		"deposited_amount": sum(flt(d.total_amount) for d in deposited),
		"scheme_benefit_value": _scheme_benefits(field_user, on_date),

		"outlets_in_scope": in_scope,
		"billable_base": billable,
	}

	row.update(derive(row))
	return row


def derive(row: dict) -> dict:
	"""The six ratios, from figures already on the row.

	Split out so `aggregate` can apply exactly the same arithmetic to a month's totals. Two
	copies of this would be two definitions of "strike rate", which is the failure the whole
	snapshot exists to prevent.
	"""
	return {
		"coverage_pct": pct(row.get("outlets_billed"), row.get("outlets_in_scope")),
		"productive_pct": pct(row.get("productive_visits"), row.get("actual_visits")),
		"visit_compliance_pct": pct(row.get("actual_visits"), row.get("planned_visits")),
		"collection_efficiency_pct": pct(row.get("collection_amount"), row.get("billable_base")),
		"lines_per_call": ratio(row.get("order_lines"), row.get("productive_visits")),
		"avg_order_value": ratio(row.get("order_value"), row.get("orders_count")),
	}


def _planned_for(field_user: str, on_date) -> int:
	"""How many shops the plan asked for, where the day was never closed.

	Day End carries the figure once a day is finished. Before that - and on a day a rep forgot
	to close - it comes from the journey plan, so a plan compliance figure exists for today as
	well as for last Tuesday.
	"""
	plans = frappe.get_all("FieldMate Journey Plan",
	                       filters={"field_user": field_user, "docstatus": ["<", 2]},
	                       pluck="name", limit_page_length=0)
	if not plans:
		return 0
	day = frappe.db.get_value("FieldMate Journey Plan Day",
	                          {"parent": ["in", plans], "parenttype": "FieldMate Journey Plan",
	                           "plan_date": on_date, "is_working_day": 1},
	                          "outlet_count")
	return cint(day)


def _outlets_in_scope(territory: str | None) -> int:
	"""The denominator coverage is measured against: shops this rep could have billed.

	Territory rather than beat, because coverage is a monthly question and a rep works several
	beats inside one territory across a month. Measuring against today's beat would report 100%
	coverage every single day and mean nothing.
	"""
	if not territory:
		return 0
	return frappe.db.count("FieldMate Outlet", {
		"territory": territory, "outlet_status": "Active", "approval_status": "Approved",
	})


def _billable_base(field_user: str, on_date, orders: list) -> float:
	"""What could have been collected: what shops already owed, plus what was billed today.

	Collection efficiency against only today's billing would read as several hundred percent on
	a day a rep chased old money, and as zero on a day they billed and collected nothing - both
	of which are the wrong shape for the question being asked.
	"""
	# Outstanding is held per shop, not per rep - a shop owes its distributor, and two reps can
	# call on it. So the base is the shops this rep actually billed today: what each of them was
	# last recorded as owing, plus what was put on the bill in front of them.
	billed_today = sum(flt(o.net_total) for o in orders)
	shops = {o.outlet for o in orders if o.outlet}
	if not shops:
		return billed_today

	# Every shop's latest position at or before the day, in one query. One read per shop was
	# free while nothing wrote this table; now that something does, a rep with forty shops on
	# their day would make forty round trips for one number.
	#
	# Newest first, so the first row seen for a shop is the one that counts - the same answer
	# `order_by="as_of desc"` gave per shop.
	latest: dict[str, float] = {}
	for row in frappe.get_all(
		"FieldMate Outstanding Snapshot",
		filters={"outlet": ["in", list(shops)], "as_of": ["<=", on_date],
		         "docstatus": ["<", 2]},
		fields=["outlet", "outstanding_amount"],
		order_by="as_of desc",
	):
		latest.setdefault(row.outlet, flt(row.outstanding_amount))

	return sum(latest.values()) + billed_today


def _distinct_skus(order_names: list[str]) -> int:
	if not order_names:
		return 0
	rows = frappe.get_all("FieldMate Order Item",
	                      filters={"parent": ["in", order_names],
	                               "parenttype": "FieldMate Order"},
	                      pluck="item_code", limit_page_length=0)
	return len(set(rows))


def _new_outlets(field_user: str, on_date) -> int:
	return frappe.db.count("FieldMate Outlet", {
		"created_by_rep": field_user, "onboarding_date": on_date,
		"approval_status": "Approved",
	})


def _scheme_benefits(field_user: str, on_date) -> float:
	rows = frappe.get_all("FieldMate Scheme Ledger",
	                      filters={"field_user": field_user, "posting_date": on_date,
	                               "docstatus": 1},
	                      pluck="benefit_amount", limit_page_length=0)
	return sum(flt(r) for r in rows)


# --------------------------------------------------------------------------------------
# writing it down
# --------------------------------------------------------------------------------------


def fingerprint(field_user: str, on_date) -> str:
	"""A digest of what the day is made of, cheap enough to check every hour.

	Counts and last-modified stamps, not contents. It does not have to prove two days are
	identical - only to notice when one has moved, so a rollup over a whole month can skip the
	twenty-eight days nobody touched. A backdated correction bumps `modified` on the document it
	corrects, so the day it belongs to stops matching and is recounted (criterion 4).
	"""
	parts = []
	for doctype, date_field in (("FieldMate Visit", "visit_date"),
	                            ("FieldMate Order", "order_date"),
	                            ("FieldMate Collection", "collection_date"),
	                            ("FieldMate Day End", "day_date")):
		rows = frappe.get_all(doctype,
		                      filters={"field_user": field_user, date_field: on_date},
		                      fields=["count(name) as n", "max(modified) as last"],
		                      limit_page_length=0)
		entry = rows[0] if rows else {}
		parts.append(f"{doctype}:{entry.get('n') or 0}:{entry.get('last') or ''}")

	return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def roll_up(field_user: str, on_date, force: bool = False) -> str | None:
	"""Write or rewrite one rep-day. Returns the snapshot name, or None if nothing changed."""
	on_date = getdate(on_date)
	digest = fingerprint(field_user, on_date)

	existing = frappe.db.get_value(
		"FieldMate KPI Snapshot",
		{"field_user": field_user, "snapshot_date": on_date},
		["name", "source_hash"], as_dict=True)

	if existing and existing.source_hash == digest and not force:
		return None

	values = measure(field_user, on_date)
	values["source_hash"] = digest
	values["computed_on"] = now_datetime()

	if existing:
		doc = frappe.get_doc("FieldMate KPI Snapshot", existing.name)
		doc.update(values)
	else:
		doc = frappe.new_doc("FieldMate KPI Snapshot")
		doc.update(values)

	doc.flags.ignore_permissions = True
	doc.save()
	return doc.name


def roll_up_range(field_user: str, from_date, to_date, force: bool = False) -> dict:
	from_date, to_date = getdate(from_date), getdate(to_date)
	written, skipped = [], 0
	day = from_date
	while day <= to_date:
		name = roll_up(field_user, day, force=force)
		if name:
			written.append(name)
		else:
			skipped += 1
		day = frappe.utils.add_days(day, 1)
	return {"written": len(written), "unchanged": skipped}


def roll_up_all(on_date=None, days_back: int = 1, force: bool = False) -> dict:
	"""The scheduled job: every active rep, over a short trailing window.

	A window rather than only today, because a day is corrected after it ends - an order pushed
	from a phone that had no signal, a visit amended by a manager - and a job that only ever
	looked at today would leave those corrections invisible for ever. The fingerprint makes the
	extra days nearly free.
	"""
	on_date = getdate(on_date or nowdate())
	start = frappe.utils.add_days(on_date, -max(days_back - 1, 0))

	reps = frappe.get_all("FieldMate Field User", filters={"status": "Active"},
	                      pluck="name", order_by="name asc")

	written = unchanged = 0
	failed = []
	for rep in reps:
		try:
			result = roll_up_range(rep, start, on_date, force=force)
			written += result["written"]
			unchanged += result["unchanged"]
		except Exception:
			frappe.log_error(title=f"fieldmate kpi.roll_up {rep}")
			failed.append(rep)
		# Committed per rep. A job that rolls back 250 reps because the 249th had a bad row is
		# a job that never finishes on a real site.
		frappe.db.commit()

	return {"from": str(start), "to": str(on_date), "reps": len(reps),
	        "written": written, "unchanged": unchanged, "failed": failed}


# --------------------------------------------------------------------------------------
# reading it back
# --------------------------------------------------------------------------------------

# Everything that adds up. The ratios are deliberately absent: they are recomputed from these.
SUMMABLE = (
	"planned_visits", "actual_visits", "productive_visits", "unplanned_visits",
	"short_visits", "geo_breach_visits", "orders_count", "order_value", "order_qty",
	"order_lines", "outlets_billed", "new_outlets", "collection_amount", "collection_count",
	"deposited_amount", "scheme_benefit_value", "distance_km", "duration_hours",
	"billable_base",
)


def aggregate(rows: list) -> dict:
	"""Add up a set of daily rows and re-derive the ratios from the totals.

	Averaging the daily percentages would answer a different question. A rep who made one call
	and converted it, then twelve calls and converted three, has a strike rate of 4 in 13 - not
	the average of 100% and 25%.

	`outlets_billed` is the one count that is summed here and should not be trusted as a
	distinct count across days: a shop billed on Monday and again on Friday is two. The monthly
	coverage figure below is therefore counted properly rather than taken from the sum.
	"""
	total = dict.fromkeys(SUMMABLE, 0)
	for row in rows:
		for field in SUMMABLE:
			total[field] += flt(row.get(field))

	# Coverage's base is a property of the territory, not something to add across days.
	total["outlets_in_scope"] = max((cint(r.get("outlets_in_scope")) for r in rows), default=0)
	total["days"] = len(rows)
	total["days_worked"] = sum(1 for r in rows if cint(r.get("day_started")))
	total.update(derive(total))
	return total


def period(field_user: str, from_date, to_date) -> dict:
	"""A rep's totals for a window, read from the snapshot and nothing else."""
	rows = frappe.get_all(
		"FieldMate KPI Snapshot",
		filters={"field_user": field_user,
		         "snapshot_date": ["between", [getdate(from_date), getdate(to_date)]]},
		fields=["*"],
		order_by="snapshot_date asc",
		limit_page_length=0,
	)
	summary = aggregate(rows)

	# Distinct shops across the window, which the daily sum cannot give: a shop billed twice in
	# a month is one covered shop, not two.
	summary["outlets_covered"] = distinct_outlets_billed(field_user, from_date, to_date)
	summary["coverage_pct"] = pct(summary["outlets_covered"], summary["outlets_in_scope"])

	return {
		"field_user": field_user,
		"from_date": str(getdate(from_date)),
		"to_date": str(getdate(to_date)),
		"totals": summary,
		"daily": rows,
	}


def distinct_outlets_billed(field_user: str, from_date, to_date) -> int:
	rows = frappe.get_all(
		"FieldMate Order",
		filters={"field_user": field_user,
		         "order_date": ["between", [getdate(from_date), getdate(to_date)]],
		         "docstatus": 1, "order_status": ["not in", DEAD_ORDER_STATES]},
		pluck="outlet", limit_page_length=0)
	return len(set(rows))


def month(field_user: str, on_date=None) -> dict:
	on_date = getdate(on_date or nowdate())
	return period(field_user, get_first_day(on_date), get_last_day(on_date))


def today_for(field_user: str, on_date=None) -> dict:
	"""One day, live.

	This one deliberately measures rather than reading the snapshot. The rep is standing in a
	market looking at what they have done in the last hour, and last night's row is the one
	number they would immediately know to be wrong. Everything historical reads the table;
	today, and only today, is counted fresh.
	"""
	on_date = getdate(on_date or nowdate())
	return measure(field_user, on_date)


def for_team(sales_person: str, from_date, to_date) -> dict:
	"""A manager's roll-up: every rep under a node of the Sales Person tree.

	Reads snapshots only. A manager's summary that re-counted visits would be the second
	definition of every metric on the page (criterion 3).
	"""
	from fieldmate.services import target as target_service

	people = target_service.subtree(sales_person)
	reps = frappe.get_all("FieldMate Field User",
	                      filters={"sales_person": ["in", people], "status": "Active"},
	                      fields=["name", "full_name", "territory"], limit_page_length=0)
	if not reps:
		return {"sales_person": sales_person, "reps": [], "totals": aggregate([])}

	rows = frappe.get_all(
		"FieldMate KPI Snapshot",
		filters={"field_user": ["in", [r.name for r in reps]],
		         "snapshot_date": ["between", [getdate(from_date), getdate(to_date)]]},
		fields=["*"], limit_page_length=0)

	by_rep: dict[str, list] = {}
	for row in rows:
		by_rep.setdefault(row.field_user, []).append(row)

	names = {r.name: r.full_name or r.name for r in reps}
	per_rep = []
	for rep in reps:
		summary = aggregate(by_rep.get(rep.name, []))
		per_rep.append({"field_user": rep.name, "full_name": names[rep.name],
		                "territory": rep.territory, **summary})

	# Sorted by what a manager opens the page to find: who sold the most, and by implication
	# who is at the bottom.
	per_rep.sort(key=lambda r: flt(r["order_value"]), reverse=True)

	return {
		"sales_person": sales_person,
		"from_date": str(getdate(from_date)),
		"to_date": str(getdate(to_date)),
		"rep_count": len(reps),
		"totals": aggregate(rows),
		"reps": per_rep,
	}


def core_metrics(summary: dict) -> list[dict]:
	"""The nine, in the order they are read, with the base each was measured over.

	A percentage without its denominator is a number nobody can argue with or act on, so both
	travel together everywhere they are shown.
	"""
	labels = {
		"coverage_pct": "Coverage",
		"productive_pct": "Strike rate",
		"visit_compliance_pct": "Plan compliance",
		"collection_efficiency_pct": "Collection efficiency",
		"lines_per_call": "Lines per call",
		"avg_order_value": "Average order",
		"order_value": "Value sold",
		"order_qty": "Volume sold",
		"new_outlets": "New shops",
	}
	out = []
	for key, label in labels.items():
		halves = CORE_METRICS.get(key)
		entry = {"key": key, "label": label, "value": flt(summary.get(key)),
		         "is_pct": key in RATIO_METRICS}
		if halves:
			entry["of"] = flt(summary.get(halves[1]))
			entry["got"] = flt(summary.get(
				"outlets_covered" if key == "coverage_pct" else halves[0]))
		out.append(entry)
	return out


def as_json(value) -> str:
	return json.dumps(value, default=str, separators=(",", ":"))
