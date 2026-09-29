// Confirming a deposit is the moment money reaches the ledger, and it belongs here rather than
// on the phone: the rep declares, somebody else confirms, and a control one person can do both
// halves of is not a control. Until this button existed a declared deposit offered nothing but
// Cancel, so the Payment Entries it should have posted never appeared at all.

const METHOD =
	'fieldmate.fieldmate.doctype.fieldmate_collection_deposit.fieldmate_collection_deposit.confirm';

frappe.ui.form.on('FieldMate Collection Deposit', {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.status === 'Confirmed') return;

		frm.add_custom_button(__('Confirm Deposit'), () => ask(frm));
		frm.change_custom_button_type(__('Confirm Deposit'), null, 'primary');
	},
});

function ask(frm) {
	// Says what it will actually do, in the two halves it does it in. Only the distributor's own
	// money posts anything; a shop's cash was the distributor's from the moment it left the till
	// and passes through without touching our books.
	// `ours_amount` is the field; "Ours To Post" is its label.
	const ours = frm.doc.ours_amount;
	frappe.confirm(
		__('This posts a Payment Entry for {0} — the part collected from distributors. Anything collected at a shop is marked cleared and posts nothing. Continue?',
			[format_currency(ours || 0, frm.doc.currency)]),
		() => run(frm),
	);
}

function run(frm) {
	frappe.call({
		method: METHOD,
		args: { deposit: frm.doc.name },
		freeze: true,
		freeze_message: __('Posting the payments…'),
		callback(r) {
			if (!r.message) return;
			frm.reload_doc();
			frappe.show_alert({ message: __('Deposit confirmed.'), indicator: 'green' }, 5);
		},
	});
}
