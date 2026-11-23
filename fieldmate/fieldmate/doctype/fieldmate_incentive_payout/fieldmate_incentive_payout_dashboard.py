from frappe import _


def get_data():
	return {
		"fieldname": "incentive_payout",
		"internal_links": {
			"FieldMate Target Plan": "target_plan",
			"FieldMate Achievement": "achievement",
			"FieldMate Incentive Scheme": "scheme",
		},
		"transactions": [
			{
				"label": _("Source"),
				"items": ["FieldMate Target Plan", "FieldMate Achievement", "FieldMate Incentive Scheme"],
			},
		],
	}
