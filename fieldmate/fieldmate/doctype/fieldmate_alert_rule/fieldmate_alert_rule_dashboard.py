from frappe import _


def get_data():
	return {
		"fieldname": "rule",
		"transactions": [
			{"label": _("Alerts"), "items": ["FieldMate Alert Log"]},
		],
	}
