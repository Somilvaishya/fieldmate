// The Sales Head's month, as buttons.
//
// Cascading a plan down the tree, measuring it before the nightly job does, checking the leaves
// still add up, and turning the month into incentive payouts: every one of these was a
// `frappe.call` typed into the browser console. A Sales Head will not do that, and should not
// have to. The buttons are drawn for whoever holds the right the server checks, so nobody is
// offered a button that will only refuse them.

const M = 'fieldmate.fieldmate.doctype.fieldmate_target_plan.fieldmate_target_plan.';

frappe.ui.form.on('FieldMate Target Plan', {
	refresh(frm) {
		// A draft is still being written, and a cancelled plan is history.
		if (frm.doc.docstatus !== 1) return;

		const group = __('Targets');
		const can_run = frappe.perm.has_perm(frm.doctype, 0, 'submit');

		if (can_run) {
			frm.add_custom_button(__('Cascade to the team'), () => cascade(frm), group);
			frm.add_custom_button(__('Measure now'), () => measure(frm), group);
		}
		frm.add_custom_button(__('Check the totals'), () => check_totals(frm), group);

		// Payouts are worked out over a whole period, for every rep with a plan in it - so from
		// the plan at the top, where the period is set, not from each rep's.
		if (frm.doc.is_root && frappe.perm.has_perm('FieldMate Incentive Payout', 0, 'create')) {
			frm.add_custom_button(__('Work out payouts'), () => payouts(frm), group);
		}
	},
});

function cascade(frm) {
	frappe.confirm(
		__('Split this plan to everyone below {0}? Plans already made below are updated, not duplicated.',
			[frm.doc.sales_person]),
		() => frappe.call({
			method: M + 'cascade_plan',
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message: __('Splitting the targets…'),
		}).then((r) => {
			const made = (r.message && r.message.children) || [];
			frappe.show_alert({
				message: made.length
					? __('Split to {0} plans below this one.', [made.length])
					: __('Nobody below this plan to split to.'),
				indicator: 'green',
			});
			frm.reload_doc();
		}),
	);
}

function measure(frm) {
	frappe.call({
		method: M + 'measure_now',
		args: { name: frm.doc.name },
		freeze: true,
		freeze_message: __('Measuring…'),
	}).then((r) => {
		frappe.show_alert({
			message: __('Measured {0} plans. The achievement figures are up to date.',
				[(r.message && r.message.measured) || 0]),
			indicator: 'green',
		});
	});
}

function check_totals(frm) {
	frappe.call({ method: M + 'check_totals', args: { name: frm.doc.name } }).then((r) => {
		const res = r.message || {};
		const rows = Object.entries(res.types || {}).map(([type, t]) => `
			<tr>
				<td>${frappe.utils.escape_html(type)}</td>
				<td class="text-right">${t.additive ? format_number(t.root) : frappe.utils.escape_html(String(t.root))}</td>
				<td class="text-right">${t.additive ? format_number(t.leaves) : frappe.utils.escape_html(String(t.leaves))}</td>
				<td>${t.matches
					? `<span class="indicator-pill green">${__('Adds up')}</span>`
					: `<span class="indicator-pill red">${__('Off by {0}', [format_number(t.difference)])}</span>`}</td>
			</tr>`).join('');
		frappe.msgprint({
			title: res.matches ? __('The plans below add up') : __('The plans below do not add up'),
			indicator: res.matches ? 'green' : 'red',
			message: `
				<p>${__('{0} plans at the bottom of this one.', [res.leaf_count || 0])}</p>
				<table class="table table-bordered table-sm">
					<thead><tr><th>${__('Target')}</th><th class="text-right">${__('This plan')}</th>
					<th class="text-right">${__('Below it')}</th><th></th></tr></thead>
					<tbody>${rows}</tbody>
				</table>`,
		});
	});
}

// A dry run first. Working out payouts writes one draft per rep and scheme; saying how many
// before doing it is cheaper than a Sales Head finding two hundred drafts they did not expect.
function payouts(frm) {
	frappe.call({
		method: M + 'compute_payouts',
		args: { name: frm.doc.name, dry_run: 1 },
		freeze: true,
		freeze_message: __('Working out what each rep has earned…'),
	}).then((r) => {
		const res = r.message || {};
		if (!res.payouts) {
			frappe.msgprint({
				title: __('Nothing to pay'),
				indicator: 'orange',
				message: __('{0} plans in {1} to {2}, and no incentive scheme gives anybody anything for them yet.',
					[res.plans || 0, frappe.datetime.str_to_user(frm.doc.from_date),
						frappe.datetime.str_to_user(frm.doc.to_date)]),
			});
			return;
		}
		frappe.confirm(
			__('This makes {0} draft payouts across {1} plans for {2} to {3}. Drafts already there are updated; anything already submitted is left as it is. Go ahead?',
				[res.payouts, res.plans, frappe.datetime.str_to_user(frm.doc.from_date),
					frappe.datetime.str_to_user(frm.doc.to_date)]),
			() => frappe.call({
				method: M + 'compute_payouts',
				args: { name: frm.doc.name, dry_run: 0 },
				freeze: true,
				freeze_message: __('Writing the payouts…'),
			}).then((done) => {
				const out = done.message || {};
				frappe.msgprint({
					title: __('Payouts ready to check'),
					indicator: out.failed && out.failed.length ? 'orange' : 'green',
					message: __('{0} payouts written as drafts. Open each, check it, and submit it for approval.',
						[out.payouts || 0])
						+ (out.failed && out.failed.length
							? `<br><br>${__('These plans could not be worked out and are in the Error Log: {0}', [out.failed.join(', ')])}`
							: ''),
				});
				frappe.set_route('List', 'FieldMate Incentive Payout', {
					from_date: frm.doc.from_date, to_date: frm.doc.to_date,
				});
			}),
		);
	});
}
