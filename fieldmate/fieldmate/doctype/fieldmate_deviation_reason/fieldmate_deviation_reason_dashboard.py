from frappe import _


def get_data():
	return {
		"fieldname": "deviation_reason",
		"transactions": [
			{"label": _("Field work"), "items": ["FieldMate Visit"]},
		],
	}
