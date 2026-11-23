from frappe import _


def get_data():
	return {
		"fieldname": "catalogue",
		"transactions": [
			{"label": _("Sales"), "items": ["FieldMate Share Link"]},
		],
	}
