"""The nine, per rep, for a window. The dataset everything else in Insights builds on.

Reads `FieldMate KPI Snapshot` and nothing else, and does not compute a single metric for
itself - `services/kpi.aggregate` does that, the same function the phone and the manager's
summary call. That is the whole point of Gate 8 criterion 3: one definition of "strike rate",
in one place, however it is being looked at.
"""

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, getdate, today

from fieldmate.services import kpi as kpi_service


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "field_user", "label": _("Rep"), "fieldtype": "Link",
		 "options": "FieldMate Field User", "width": 150},
		{"fieldname": "full_name", "label": _("Name"), "fieldtype": "Data", "width": 150},
		{"fieldname": "territory", "label": _("Territory"), "fieldtype": "Link",
		 "options": "Territory", "width": 130},
		{"fieldname": "days_worked", "label": _("Days Out"), "fieldtype": "Int", "width": 85},
		{"fieldname": "order_value", "label": _("Value Sold"), "fieldtype": "Currency",
		 "width": 120},
		{"fieldname": "order_qty", "label": _("Volume"), "fieldtype": "Float",
		 "precision": 0, "width": 90},
		{"fieldname": "outlets_covered", "label": _("Shops Covered"), "fieldtype": "Int",
		 "width": 110},
		{"fieldname": "coverage_pct", "label": _("Coverage"), "fieldtype": "Percent",
		 "width": 95},
		{"fieldname": "productive_pct", "label": _("Strike Rate"), "fieldtype": "Percent",
		 "width": 100},
		{"fieldname": "visit_compliance_pct", "label": _("Plan Compliance"),
		 "fieldtype": "Percent", "width": 125},
		{"fieldname": "lines_per_call", "label": _("Lines / Call"), "fieldtype": "Float",
		 "precision": 2, "width": 100},
		{"fieldname": "avg_order_value", "label": _("Average Order"), "fieldtype": "Currency",
		 "width": 120},
		{"fieldname": "collection_efficiency_pct", "label": _("Collection"),
		 "fieldtype": "Percent", "width": 100},
		{"fieldname": "new_outlets", "label": _("New Shops"), "fieldtype": "Int", "width": 95},
	]


def data(filters):
	to_date = getdate(filters.get("to_date") or today())
	from_date = getdate(filters.get("from_date") or get_first_day(to_date))

	conditions = {"snapshot_date": ["between", [from_date, to_date]]}
	if filters.get("field_user"):
		conditions["field_user"] = filters["field_user"]
	if filters.get("territory"):
		conditions["territory"] = filters["territory"]

	# get_list, not get_all: a manager sees their own team and a rep sees themselves, which the
	# permission hooks in hooks.py decide. get_all would hand everybody everybody.
	rows = frappe.get_list("FieldMate KPI Snapshot", filters=conditions, fields=["*"],
	                       limit_page_length=0)

	by_rep = {}
	for row in rows:
		by_rep.setdefault(row.field_user, []).append(row)

	if not by_rep:
		return []

	names = dict(frappe.get_all("FieldMate Field User",
	                            filters={"name": ["in", list(by_rep)]},
	                            fields=["name", "full_name"], as_list=True,
	                            limit_page_length=0))

	out = []
	for rep, days in by_rep.items():
		# The service aggregates, so a ratio is the ratio of the totals rather than the average
		# of the daily ratios - which is a different and usually wrong number.
		summary = kpi_service.aggregate(days)
		covered = _distinct_shops(rep, from_date, to_date)
		out.append({
			"field_user": rep,
			"full_name": names.get(rep) or rep,
			"territory": days[0].get("territory"),
			"outlets_covered": covered,
			"coverage_pct": kpi_service.pct(covered, summary["outlets_in_scope"]),
			**{k: summary.get(k) for k in (
				"days_worked", "order_value", "order_qty", "productive_pct",
				"visit_compliance_pct", "lines_per_call", "avg_order_value",
				"collection_efficiency_pct", "new_outlets")},
		})

	out.sort(key=lambda r: flt(r["order_value"]), reverse=True)
	return out


def _distinct_shops(field_user, from_date, to_date) -> int:
	"""Shops covered across the window, which the daily sum cannot give.

	A shop billed on Monday and again on Friday is one covered shop. This is the only place in
	the report that touches an order document, and it touches it for a count the snapshot is
	not shaped to answer - not for a metric.
	"""
	return kpi_service.distinct_outlets_billed(field_user, from_date, to_date)
