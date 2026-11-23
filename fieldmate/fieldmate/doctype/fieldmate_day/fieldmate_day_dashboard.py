from frappe import _


def get_data():
	return {
		"fieldname": "day",
		"internal_links": {
			"FieldMate Journey Plan": "journey_plan",
			"FieldMate Beat": "planned_beat",
		},
		"transactions": [
			{
				"label": _("Field work"),
				"items": ["FieldMate Visit", "FieldMate Attendance Summary", "FieldMate Location Trail"],
			},
			{"label": _("Money"), "items": ["FieldMate Expense Claim"]},
			{"label": _("Planning"), "items": ["FieldMate Journey Plan", "FieldMate Beat"]},
		],
	}
