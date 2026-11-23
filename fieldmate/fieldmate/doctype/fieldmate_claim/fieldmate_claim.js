// A distributor's scheme claim, decided from its own form.
//
// Approving it, raising the credit note it is settled by, and reversing that credit note were
// reachable only through the API - the Sales Head typed them into the browser console. Drawn for
// whoever may submit a claim, the Sales Head and Admin, which is the right the server checks.

const M = 'fieldmate.fieldmate.doctype.fieldmate_claim.fieldmate_claim.';

frappe.ui.form.on('FieldMate Claim', {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || !frappe.perm.has_perm(frm.doctype, 0, 'submit')) return;

		const status = frm.doc.claim_status;
		if (status === 'Pending Approval') {
			frm.add_custom_button(__('Approve'), () => approve(frm)).addClass('btn-primary');
			frm.add_custom_button(__('Reject'), () => reject(frm));
		}
		// Approved earlier without settling - the credit note is still to be raised.
		if (status === 'Approved' && !frm.doc.credit_note) {
			frm.add_custom_button(__('Raise credit note'), () => raise(frm)).addClass('btn-primary');
		}
		if (status === 'Settled' && frm.doc.credit_note) {
			frm.add_custom_button(__('Reverse credit note'), () => reverse(frm));
		}
	},
});

function call(method, args, done) {
	return frappe.call({ method: M + method, args, freeze: true }).then((r) => done(r.message || {}));
}

function approve(frm) {
	const d = new frappe.ui.Dialog({
		title: __('Approve claim {0}', [frm.doc.name]),
		fields: [
			{ fieldname: 'approved_amount', fieldtype: 'Currency', label: __('Approve at'), reqd: 1,
				default: frm.doc.claimed_amount,
				description: __('Claimed {0}. You may approve less, never more.',
					[format_currency(frm.doc.claimed_amount)]) },
			{ fieldname: 'remarks', fieldtype: 'Small Text', label: __('Remarks') },
			// On by default: approving and paying are one decision for most claims, and a claim
			// approved but never settled is money the distributor is still waiting for.
			{ fieldname: 'settle', fieldtype: 'Check', default: 1,
				label: __('Raise the credit note now') },
		],
		primary_action_label: __('Approve'),
		primary_action(values) {
			call('decide', {
				name: frm.doc.name, decision: 'Approved', approved_amount: values.approved_amount,
				remarks: values.remarks, settle: values.settle ? 1 : 0,
			}, (res) => {
				d.hide();
				frappe.show_alert({
					message: res.credit_note
						? __('Approved. Credit note {0} raised.', [res.credit_note])
						: __('Approved. Raise the credit note when you are ready.'),
					indicator: 'green',
				});
				frm.reload_doc();
			});
		},
	});
	d.show();
}

function reject(frm) {
	frappe.prompt(
		{ fieldname: 'remarks', fieldtype: 'Small Text', reqd: 1,
			label: __('Why? The distributor will read this.') },
		(values) => call('decide', { name: frm.doc.name, decision: 'Rejected', remarks: values.remarks },
			() => { frappe.show_alert({ message: __('Rejected.'), indicator: 'red' }); frm.reload_doc(); }),
		__('Reject claim {0}', [frm.doc.name]),
		__('Reject'),
	);
}

function raise(frm) {
	frappe.prompt(
		{ fieldname: 'posting_date', fieldtype: 'Date', label: __('Posting date'),
			default: frappe.datetime.get_today() },
		(values) => call('raise_credit_note', { name: frm.doc.name, posting_date: values.posting_date },
			(res) => {
				frappe.show_alert({ message: __('Credit note {0} raised.', [res.credit_note]), indicator: 'green' });
				frm.reload_doc();
			}),
		__('Raise the credit note for {0}', [format_currency(frm.doc.approved_amount)]),
		__('Raise'),
	);
}

function reverse(frm) {
	frappe.confirm(
		__('Cancel credit note {0} and put this claim back to approved? The distributor\'s balance goes back up by {1}.',
			[frm.doc.credit_note, format_currency(frm.doc.approved_amount)]),
		() => call('reverse_credit_note', { name: frm.doc.name }, () => {
			frappe.show_alert({ message: __('Credit note reversed.'), indicator: 'orange' });
			frm.reload_doc();
		}),
	);
}
