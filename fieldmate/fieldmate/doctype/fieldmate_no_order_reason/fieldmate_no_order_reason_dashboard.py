from frappe import _


def get_data():
	return {
		"fieldname": "no_order_reason",
		"transactions": [
			{"label": _("Field work"), "items": ["FieldMate Visit"]},
		],
	}
