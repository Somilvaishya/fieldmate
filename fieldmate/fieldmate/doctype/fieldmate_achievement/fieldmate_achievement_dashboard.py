from frappe import _


def get_data():
	return {
		"fieldname": "achievement",
		"internal_links": {
			"FieldMate Target Plan": "target_plan",
		},
		"transactions": [
			{"label": _("Payouts"), "items": ["FieldMate Incentive Payout"]},
			{"label": _("Targets"), "items": ["FieldMate Target Plan"]},
		],
	}
