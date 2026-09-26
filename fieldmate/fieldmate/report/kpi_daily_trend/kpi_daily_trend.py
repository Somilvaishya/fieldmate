"""One row per day for a team or a rep. The shape a chart wants.

The daily grain the snapshot is stored at, handed straight out - no aggregation and no metric
worked out here, because the ratios on each row were already computed against that day's own
bases when the row was written.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

from fieldmate.services import kpi as kpi_service


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "snapshot_date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{"fieldname": "field_user", "label": _("Rep"), "fieldtype": "Link",
		 "options": "FieldMate Field User", "width": 150},
		{"fieldname": "actual_visits", "label": _("Calls"), "fieldtype": "Int", "width": 75},
		{"fieldname": "productive_visits", "label": _("Productive"), "fieldtype": "Int",
		 "width": 95},
		{"fieldname": "productive_pct", "label": _("Strike Rate"), "fieldtype": "Percent",
		 "width": 100},
		{"fieldname": "orders_count", "label": _("Orders"), "fieldtype": "Int", "width": 80},
		{"fieldname": "order_value", "label": _("Value"), "fieldtype": "Currency",
		 "width": 120},
		{"fieldname": "outlets_billed", "label": _("Shops"), "fieldtype": "Int", "width": 80},
		{"fieldname": "collection_amount", "label": _("Collected"), "fieldtype": "Currency",
		 "width": 110},
		{"fieldname": "distance_km", "label": _("Km"), "fieldtype": "Float", "precision": 1,
		 "width": 75},
	]


def data(filters):
	to_date = getdate(filters.get("to_date") or today())
	from_date = getdate(filters.get("from_date") or add_days(to_date, -29))

	conditions = {"snapshot_date": ["between", [from_date, to_date]]}
	for key in ("field_user", "territory"):
		if filters.get(key):
			conditions[key] = filters[key]

	# get_list, so the permission hooks narrow a rep to their own rows.
	return frappe.get_list(
		"FieldMate KPI Snapshot",
		filters=conditions,
		fields=[c["fieldname"] for c in columns()],
		order_by="snapshot_date desc, field_user asc",
		limit_page_length=0,
	)


def totals_for(filters=None):
	"""The same window, added up. Used by the workspace and by anybody scripting against this.

	Delegates to the service so a ratio is the ratio of the totals rather than the average of
	the daily ratios.
	"""
	return kpi_service.aggregate(data(frappe._dict(filters or {})))
