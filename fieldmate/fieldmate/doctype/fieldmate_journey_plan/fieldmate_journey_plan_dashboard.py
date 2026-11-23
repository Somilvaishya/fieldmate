from frappe import _


def get_data():
	return {
		"fieldname": "journey_plan",
		"internal_links": {
			"FieldMate Beat": ["days", "beat"],
		},
		"transactions": [
			{"label": _("Field work"), "items": ["FieldMate Day", "FieldMate Visit"]},
			{"label": _("Planning"), "items": ["FieldMate Beat"]},
		],
	}
