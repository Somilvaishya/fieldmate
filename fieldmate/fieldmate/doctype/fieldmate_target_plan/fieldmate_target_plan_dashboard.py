from frappe import _


def get_data():
	return {
		"fieldname": "target_plan",
		"non_standard_fieldnames": {
			"FieldMate Target Plan": "parent_plan",
		},
		"transactions": [
			{"label": _("Performance"), "items": ["FieldMate Achievement", "FieldMate Incentive Payout"]},
			{"label": _("Targets"), "items": ["FieldMate Target Plan"]},
		],
	}
