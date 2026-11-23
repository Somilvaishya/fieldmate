from frappe import _


def get_data():
	return {
		"fieldname": "scheme",
		"transactions": [
			{"label": _("Payouts"), "items": ["FieldMate Incentive Payout"]},
		],
	}
