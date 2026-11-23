from frappe import _


def get_data():
	return {
		"fieldname": "batch",
		"transactions": [
			{"label": _("Sync"), "items": ["FieldMate Sync Conflict"]},
		],
	}
