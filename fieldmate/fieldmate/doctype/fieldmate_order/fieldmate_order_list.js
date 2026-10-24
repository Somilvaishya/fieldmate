// What an order's status looks like in the list.
//
// Frappe's default indicator reads `docstatus`, so every submitted order in this list was the
// same grey "Submitted" - which is true of an order waiting on a manager, one the depot has
// delivered and one that was refused. A manager scanning for the orders that need them had no
// way to see one without opening it.
//
// Pending Approval is the one this list exists to surface, so it is the only orange.

frappe.listview_settings['FieldMate Order'] = {
	add_fields: ['order_status', 'approval_status'],

	get_indicator(doc) {
		const colour = {
			'Pending Approval': 'orange',
			'Awaiting Advance': 'orange',
			Draft: 'grey',
			Rejected: 'red',
			Cancelled: 'red',
			Approved: 'blue',
			'Sent To Distributor': 'blue',
			Accepted: 'blue',
			Invoiced: 'green',
			Delivered: 'green',
		}[doc.order_status] || 'grey';

		// The third element filters the list to that status when the indicator is clicked, which
		// is how a manager gets from "there is an orange one" to "show me all of them".
		return [__(doc.order_status), colour, `order_status,=,${doc.order_status}`];
	},
};
