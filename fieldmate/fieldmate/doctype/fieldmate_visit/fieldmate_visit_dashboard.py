from frappe import _


def get_data():
	return {
		"fieldname": "visit",
		"internal_links": {
			"FieldMate Day": "day",
			"FieldMate Outlet": "outlet",
			"FieldMate Geo Fence Exception": "geo_fence_exception",
		},
		"transactions": [
			{
				"label": _("Sales"),
				"items": ["FieldMate Order", "FieldMate Retailer Stock", "FieldMate Merchandising Audit"],
			},
			{"label": _("Money"), "items": ["FieldMate Collection"]},
			{
				"label": _("Source"),
				"items": ["FieldMate Day", "FieldMate Outlet", "FieldMate Geo Fence Exception"],
			},
		],
	}
