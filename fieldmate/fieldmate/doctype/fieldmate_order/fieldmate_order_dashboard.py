from frappe import _


def get_data():
	return {
		"fieldname": "order",
		"non_standard_fieldnames": {
			"FieldMate Order": "tops_up",
		},
		"internal_links": {
			"Sales Order": "sales_order",
			"FieldMate Visit": "visit",
			"FieldMate Outlet": "outlet",
		},
		"transactions": [
			{"label": _("Sales"), "items": ["Sales Order", "FieldMate Order"]},
			{"label": _("Money"), "items": ["FieldMate Scheme Ledger"]},
			{"label": _("Sync"), "items": ["FieldMate Order Ingest Log"]},
			{"label": _("Source"), "items": ["FieldMate Visit", "FieldMate Outlet"]},
		],
	}
