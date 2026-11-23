from frappe import _


def get_data():
	return {
		"fieldname": "collection",
		"internal_links": {
			"FieldMate Visit": "visit",
			"FieldMate Outlet": "outlet",
			"FieldMate Collection Deposit": "deposit",
		},
		"transactions": [
			{
				"label": _("Source"),
				"items": ["FieldMate Visit", "FieldMate Outlet", "FieldMate Collection Deposit"],
			},
		],
	}
