// Deciding an order that stopped for approval.
//
// The hold has existed since the credit rules did, and the notification telling a manager about
// it was added this month - but nothing anywhere could release one. There is no Desk button, no
// screen on the phone and no page on the portal that calls `order.approve`; the endpoint existed
// and only a hand-written API call reached it. So an order parked in the queue stayed parked, the
// rep's screen read "Waiting on your manager" indefinitely, and the manager who followed the
// notification arrived at a document with nothing to do on it.
//
// A rep never sees this. `FieldMate Field Rep` has `desk_access = 0`, which is what keeps them
// out of `/app` - so everyone reading this form is a manager, an admin, or somebody who will be
// refused by `order.assert_may_approve` with a sentence that explains itself.

const APPROVE = 'fieldmate.api.order.approve';

frappe.ui.form.on('FieldMate Order', {
	refresh(frm) {
		if (frm.doc.order_status !== 'Pending Approval') return;

		// Why it stopped, said once at the top. A manager deciding an order needs the reason in
		// front of them, not in a field further down the form they have to go looking for.
		frm.dashboard.add_comment(
			__('This order is waiting on a decision. It was stopped by {0}.',
				[frm.doc.approval_rule || __('an approval rule')]),
			'orange', true,
		);

		frm.add_custom_button(__('Approve'), () => decide(frm, 'Approved'));
		frm.change_custom_button_type(__('Approve'), null, 'primary');
		frm.add_custom_button(__('Reject'), () => decide(frm, 'Rejected'));
	},
});

function decide(frm, decision) {
	const approving = decision === 'Approved';

	const dialog = new frappe.ui.Dialog({
		title: approving ? __('Approve this order?') : __('Reject this order?'),
		fields: [
			{
				fieldtype: 'HTML',
				options: `<p class="text-muted">${
					approving
						? __('It goes to the distributor the moment you approve it, and any offer it earned is taken off the scheme budget.')
						: __('The rep sees this on their phone as refused. Nothing is sent to the distributor.')
				}</p>`,
			},
			{
				fieldname: 'remarks',
				fieldtype: 'Small Text',
				label: approving ? __('Note (optional)') : __('Why?'),
				// Required on a refusal, and only here. The server will accept a rejection with
				// no reason at all, which leaves the rep reading "Refused" on their phone with
				// nothing to act on - the same argument the no-order reasons make. Worth pushing
				// into the service, but a UI that quietly allows it is the part we control today.
				reqd: approving ? 0 : 1,
			},
		],
		primary_action_label: approving ? __('Approve') : __('Reject'),
		primary_action(values) {
			dialog.hide();
			send(frm, decision, values.remarks);
		},
	});
	dialog.show();
}

function send(frm, decision, remarks) {
	frappe.call({
		method: APPROVE,
		// Spelled out because the endpoint is `@frappe.whitelist(methods=["POST"])`: a decision
		// writes, and a GET of it would be refused by the framework rather than by us.
		type: 'POST',
		args: { order: frm.doc.name, decision, remarks: remarks || null },
		freeze: true,
		freeze_message: decision === 'Approved'
			? __('Sending it to the distributor…')
			: __('Recording the refusal…'),
		callback(r) {
			// `api.*` answers in an envelope: `{ok: true, data: {...}}` on success, and
			// `{ok: false, code, message}` where the server refused for a reason the person
			// reading this can act on - "an order cannot be approved by the person who booked
			// it", or the list of who may decide it. Those are not exceptions and do not reach
			// the error handler, so they are read here or they are not read at all.
			const answer = r.message || {};
			if (answer.ok === false) {
				frappe.msgprint({
					title: __('Not done'),
					message: answer.message || __('That did not work.'),
					indicator: 'red',
				});
				return;
			}
			frm.reload_doc();
			frappe.show_alert(
				{
					message: decision === 'Approved'
						? __('Approved. It is on its way to the distributor.')
						: __('Refused. The rep will see it on their next sync.'),
					indicator: decision === 'Approved' ? 'green' : 'orange',
				},
				5,
			);
		},
	});
}
