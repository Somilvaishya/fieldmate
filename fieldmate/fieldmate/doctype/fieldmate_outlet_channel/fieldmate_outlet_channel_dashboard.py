from frappe import _


def get_data():
	return {
		"fieldname": "channel",
		"transactions": [
			{"label": _("Shops"), "items": ["FieldMate Outlet"]},
			{
				"label": _("Rules"),
				"items": [
					"FieldMate Product Catalogue",
					"FieldMate Must Sell List",
					"FieldMate Checklist Template",
					"FieldMate Order Approval Rule",
				],
			},
		],
	}
