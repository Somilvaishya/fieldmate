from frappe import _


def get_data():
	return {
		"fieldname": "field_user",
		"non_standard_fieldnames": {
			"FieldMate Beat": "assigned_to",
			"FieldMate Outlet": "created_by_rep",
			"FieldMate Field User": "reports_to",
		},
		"transactions": [
			{
				"label": _("Planning"),
				"items": ["FieldMate Beat", "FieldMate Journey Plan", "FieldMate Target Plan"],
			},
			{
				"label": _("Field work"),
				"items": [
					"FieldMate Day",
					"FieldMate Visit",
					"FieldMate Attendance Summary",
					"FieldMate Location Trail",
					"FieldMate Geo Fence Exception",
				],
			},
			{
				"label": _("Sales"),
				"items": [
					"FieldMate Order",
					"FieldMate Outlet",
					"FieldMate Retailer Stock",
					"FieldMate Merchandising Audit",
					"FieldMate Share Link",
				],
			},
			{
				"label": _("Money"),
				"items": [
					"FieldMate Collection",
					"FieldMate Collection Deposit",
					"FieldMate Expense Claim",
					"FieldMate Scheme Ledger",
				],
			},
			{
				"label": _("Performance"),
				"items": [
					"FieldMate KPI Snapshot",
					"FieldMate Achievement",
					"FieldMate Incentive Payout",
					"FieldMate Alert Log",
				],
			},
			{"label": _("Team"), "items": ["FieldMate Field User"]},
		],
	}
