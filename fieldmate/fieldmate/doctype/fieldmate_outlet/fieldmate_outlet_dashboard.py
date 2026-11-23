from frappe import _


def get_data():
	return {
		"fieldname": "outlet",
		"internal_links": {
			"FieldMate Beat": "primary_beat",
		},
		"transactions": [
			{
				"label": _("Field work"),
				"items": [
					"FieldMate Visit",
					"FieldMate Merchandising Audit",
					"FieldMate Geo Fence Exception",
					"FieldMate Retailer Stock",
				],
			},
			{
				"label": _("Sales"),
				"items": ["FieldMate Order", "FieldMate Share Link", "FieldMate Scheme Ledger"],
			},
			{"label": _("Money"), "items": ["FieldMate Collection", "FieldMate Outstanding Snapshot"]},
			{"label": _("Planning"), "items": ["FieldMate Beat"]},
		],
	}
