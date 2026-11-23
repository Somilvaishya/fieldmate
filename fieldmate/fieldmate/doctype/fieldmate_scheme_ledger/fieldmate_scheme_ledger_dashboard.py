from frappe import _


def get_data():
	return {
		"fieldname": "scheme_ledger",
		"internal_links": {
			"FieldMate Scheme": "scheme",
			"FieldMate Order": "order",
			"FieldMate Claim": "claim",
			"FieldMate Outlet": "outlet",
		},
		"transactions": [
			{
				"label": _("Source"),
				"items": ["FieldMate Scheme", "FieldMate Order", "FieldMate Claim", "FieldMate Outlet"],
			},
		],
	}
