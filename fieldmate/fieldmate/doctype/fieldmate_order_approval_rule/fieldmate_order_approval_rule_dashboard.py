from frappe import _


def get_data():
	return {
		"fieldname": "approval_rule",
		"transactions": [
			{"label": _("Sales"), "items": ["FieldMate Order"]},
		],
	}
