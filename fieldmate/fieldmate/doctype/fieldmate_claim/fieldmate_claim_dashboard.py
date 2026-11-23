from frappe import _


def get_data():
	return {
		"fieldname": "claim",
		"internal_links": {
			"FieldMate Order": ["items", "order"],
			"FieldMate Outlet": ["items", "outlet"],
		},
		"transactions": [
			{"label": _("Money"), "items": ["FieldMate Scheme Ledger"]},
			{"label": _("Source"), "items": ["FieldMate Order", "FieldMate Outlet"]},
		],
	}
