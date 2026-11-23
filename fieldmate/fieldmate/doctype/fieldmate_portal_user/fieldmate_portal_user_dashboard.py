from frappe import _


def get_data():
	return {
		"fieldname": "portal_user",
		"transactions": [
			{"label": _("Sync"), "items": ["FieldMate Order Ingest Log"]},
		],
	}
