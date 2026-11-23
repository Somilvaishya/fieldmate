from frappe import _


def get_data():
	return {
		"fieldname": "merchandising_audit",
		"transactions": [
			{"label": _("Field work"), "items": ["FieldMate Visit"]},
		],
	}
