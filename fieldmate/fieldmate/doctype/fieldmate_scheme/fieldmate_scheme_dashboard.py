from frappe import _


def get_data():
	return {
		"fieldname": "scheme",
		"transactions": [
			{"label": _("Money"), "items": ["FieldMate Scheme Ledger", "FieldMate Claim"]},
		],
	}
