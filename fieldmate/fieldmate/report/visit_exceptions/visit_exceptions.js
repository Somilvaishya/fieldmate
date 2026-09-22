// eslint-disable-next-line
frappe.query_reports["Visit Exceptions"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -7),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "field_user",
			label: __("Rep"),
			fieldtype: "Link",
			options: "FieldMate Field User",
		},
		{
			fieldname: "outlet",
			label: __("Shop"),
			fieldtype: "Link",
			options: "FieldMate Outlet",
		},
		{
			fieldname: "include_deviations",
			label: __("Include off-beat visits"),
			fieldtype: "Check",
			// Off-beat on its own is ordinary. Listing every one of them by default would
			// bury the visits that actually need a look.
			default: 0,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "reasons" && data && data.reasons) {
			value = `<span style="color: var(--orange-600)">${value}</span>`;
		}
		return value;
	},
};
