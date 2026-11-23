from frappe import _


def get_data():
	return {
		"fieldname": "device_id",
		"non_standard_fieldnames": {
			"FieldMate Sync Batch": "device",
			"FieldMate Sync Conflict": "device",
		},
		"transactions": [
			{
				"label": _("Field work"),
				"items": ["FieldMate Day", "FieldMate Visit", "FieldMate Location Trail"],
			},
			{"label": _("Sales"), "items": ["FieldMate Order"]},
			{"label": _("Money"), "items": ["FieldMate Collection"]},
			{"label": _("Sync"), "items": ["FieldMate Sync Batch", "FieldMate Sync Conflict"]},
		],
	}
