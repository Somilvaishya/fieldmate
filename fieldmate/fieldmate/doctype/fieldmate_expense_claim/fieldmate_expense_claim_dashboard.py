from frappe import _


def get_data():
	return {
		"fieldname": "expense_claim",
		"internal_links": {
			"FieldMate Day": "day",
		},
		"transactions": [
			{"label": _("Source"), "items": ["FieldMate Day"]},
		],
	}
