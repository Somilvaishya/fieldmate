from frappe import _


def get_data():
	return {
		"fieldname": "geo_fence_exception",
		"transactions": [
			{"label": _("Field work"), "items": ["FieldMate Visit"]},
		],
	}
