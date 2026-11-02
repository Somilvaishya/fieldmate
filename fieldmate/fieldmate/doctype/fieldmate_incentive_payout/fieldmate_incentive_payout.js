// A payout's last two steps, as buttons.
//
// Submit is Desk's own and moves a draft to Pending Approval. Deciding it, and recording where
// it was paid, were console-only. Drawn for whoever may submit a payout - the Sales Head and
// Admin - which is the right the server checks.

const M = 'fieldmate.fieldmate.doctype.fieldmate_incentive_payout.fieldmate_incentive_payout.';

frappe.ui.form.on('FieldMate Incentive Payout', {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frappe.perm.has_perm(frm.doctype, 0, 'submit')) return;

		if (frm.doc.payout_status === 'Pending Approval') {
			frm.add_custom_button(__('Approve'), () => decide(frm, 'Approved')).addClass('btn-primary');
			frm.add_custom_button(__('Reject'), () => decide(frm, 'Rejected'));
		}
		if (frm.doc.payout_status === 'Approved') {
			frm.add_custom_button(__('Record payment'), () => mark_paid(frm)).addClass('btn-primary');
		}
	},
});

function decide(frm, decision) {
	const rejecting = decision === 'Rejected';
	const d = new frappe.ui.Dialog({
		title: rejecting ? __('Reject this payout') : __('Approve {0}', [format_currency(frm.doc.payout_amount)]),
		fields: [{
			fieldname: 'remarks',
			fieldtype: 'Small Text',
			label: rejecting ? __('Why? The rep will read this.') : __('Remarks'),
			// A rejected incentive with no reason is a grievance; the server refuses it too.
			reqd: rejecting ? 1 : 0,
		}],
		primary_action_label: rejecting ? __('Reject') : __('Approve'),
		primary_action(values) {
			frappe.call({
				method: M + 'decide',
				args: { name: frm.doc.name, decision, remarks: values.remarks },
				freeze: true,
			}).then(() => {
				d.hide();
				frappe.show_alert({ message: rejecting ? __('Rejected.') : __('Approved.'),
					indicator: rejecting ? 'red' : 'green' });
				frm.reload_doc();
			});
		},
	});
	d.show();
}

// FieldMate pays nobody. It says what is owed and records where the payment was made - payroll,
// a bank transfer - so the reference is the whole point of this step.
function mark_paid(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Record the payment of {0}', [format_currency(frm.doc.payout_amount)]),
		fields: [
			{ fieldname: 'reference', fieldtype: 'Data', reqd: 1,
				label: __('Where it was paid'),
				description: __('A salary slip, a bank reference, a payroll run.') },
			{ fieldname: 'paid_on', fieldtype: 'Date', label: __('Paid on'),
				default: frappe.datetime.get_today() },
		],
		primary_action_label: __('Record payment'),
		primary_action(values) {
			frappe.call({
				method: M + 'mark_paid',
				args: { name: frm.doc.name, reference: values.reference, paid_on: values.paid_on },
				freeze: true,
			}).then(() => {
				d.hide();
				frappe.show_alert({ message: __('Recorded as paid.'), indicator: 'green' });
				frm.reload_doc();
			});
		},
	});
	d.show();
}
