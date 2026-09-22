"""Visits a manager should look at.

Nothing in FieldMate blocks a rep in the field, which is a deliberate choice - a blocked rep
stops using the app, and then there is no data at all. The bargain is that everything unusual is
recorded and surfaced here instead. This report is the other half of that bargain; without it,
the flags are collected and never read.

One row per flagged visit, with every reason it was flagged, so a manager scans a short list
rather than four separate ones.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, today


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), data(filters)


def columns():
	return [
		{"fieldname": "visit", "label": _("Visit"), "fieldtype": "Link",
		 "options": "FieldMate Visit", "width": 130},
		{"fieldname": "visit_date", "label": _("Date"), "fieldtype": "Date", "width": 95},
		{"fieldname": "field_user", "label": _("Rep"), "fieldtype": "Link",
		 "options": "FieldMate Field User", "width": 130},
		{"fieldname": "outlet_name", "label": _("Shop"), "fieldtype": "Data", "width": 180},
		{"fieldname": "reasons", "label": _("Flagged For"), "fieldtype": "Data", "width": 260},
		{"fieldname": "distance_from_outlet_m", "label": _("Distance (m)"),
		 "fieldtype": "Float", "precision": 0, "width": 110},
		{"fieldname": "duration_minutes", "label": _("Minutes"), "fieldtype": "Int",
		 "width": 85},
		{"fieldname": "visit_outcome", "label": _("Outcome"), "fieldtype": "Data", "width": 120},
		{"fieldname": "exception_status", "label": _("Exception"), "fieldtype": "Data",
		 "width": 100},
	]


def data(filters):
	conditions = {"docstatus": 1}
	from_date = filters.get("from_date") or add_days(today(), -7)
	to_date = filters.get("to_date") or today()
	conditions["visit_date"] = ["between", [from_date, to_date]]

	if filters.get("field_user"):
		conditions["field_user"] = filters["field_user"]
	if filters.get("outlet"):
		conditions["outlet"] = filters["outlet"]

	# get_list, not get_all: a manager must see their own team, and nobody else's.
	rows = frappe.get_list(
		"FieldMate Visit",
		filters=conditions,
		fields=["name as visit", "visit_date", "field_user", "outlet", "visit_outcome",
		        "distance_from_outlet_m", "duration_minutes", "is_geo_fence_breach",
		        "is_short_visit", "is_deviation", "is_mock_location", "geo_fence_exception"],
		order_by="visit_date desc, check_in_time desc",
		limit_page_length=0,
	)

	outlet_names = {
		o.name: o.outlet_name
		for o in frappe.get_all(
			"FieldMate Outlet",
			filters={"name": ["in", list({r.outlet for r in rows})]} if rows else {"name": ""},
			fields=["name", "outlet_name"],
			limit_page_length=0,
		)
	}

	out = []
	for row in rows:
		reasons = []
		if cint(row.is_geo_fence_breach):
			reasons.append(_("Outside the shop's range"))
		if cint(row.is_short_visit):
			reasons.append(_("Shorter than expected"))
		if cint(row.is_deviation):
			reasons.append(_("Off the planned beat"))
		if cint(row.is_mock_location):
			reasons.append(_("Location reported as mocked"))

		# A deviation on its own is ordinary - a rep covering for a colleague, an owner calling
		# them in. It is listed only alongside something else, or when asked for directly.
		if not reasons or (reasons == [_("Off the planned beat")]
		                   and not cint(filters.get("include_deviations"))):
			continue

		out.append({
			**row,
			"outlet_name": outlet_names.get(row.outlet, row.outlet),
			"reasons": ", ".join(reasons),
			"exception_status": frappe.db.get_value(
				"FieldMate Geo Fence Exception", row.geo_fence_exception, "status"
			) if row.geo_fence_exception else "",
		})
	return out
