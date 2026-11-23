from frappe import _


def get_data():
	return {
		"fieldname": "outlet_class",
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
