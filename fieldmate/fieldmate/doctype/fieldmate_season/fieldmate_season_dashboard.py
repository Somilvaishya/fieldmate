from frappe import _


def get_data():
	return {
		"fieldname": "season",
		"transactions": [
			{"label": _("Sales"), "items": ["FieldMate Order", "FieldMate Share Link"]},
			{"label": _("Planning"), "items": ["FieldMate Product Catalogue"]},
		],
	}
