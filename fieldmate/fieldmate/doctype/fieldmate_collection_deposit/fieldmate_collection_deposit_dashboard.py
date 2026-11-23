from frappe import _


def get_data():
	return {
		"fieldname": "deposit",
		"internal_links": {
			"FieldMate Collection": ["lines", "collection"],
		},
		"transactions": [
			{"label": _("Money"), "items": ["FieldMate Collection"]},
		],
	}
