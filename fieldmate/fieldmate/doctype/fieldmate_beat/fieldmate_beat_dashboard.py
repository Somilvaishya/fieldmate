from frappe import _


def get_data():
	return {
		"fieldname": "beat",
		"non_standard_fieldnames": {
			"FieldMate Outlet": "primary_beat",
			"FieldMate Day": "planned_beat",
		},
		"internal_links": {
			"FieldMate Outlet": ["outlets", "outlet"],
		},
		"transactions": [
			{"label": _("Shops"), "items": ["FieldMate Outlet"]},
			{"label": _("Field work"), "items": ["FieldMate Day", "FieldMate Visit"]},
			{"label": _("Planning"), "items": ["FieldMate Checklist Template"]},
			{"label": _("Performance"), "items": ["FieldMate KPI Snapshot"]},
		],
	}
