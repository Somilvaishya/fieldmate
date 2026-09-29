// The one way a planner turns beats into dates.
//
// A beat is a rule ("Sharma's route, Mondays"); a journey plan is the calendar that rule
// produces. The app reads the calendar and never the rule, so without this button a rep with a
// perfectly good beat assigned to them opened the phone to "No route planned" every morning.
// The generator had been there since Phase 3 - nothing but the tests ever called it.

const METHOD =
	'fieldmate.fieldmate.doctype.fieldmate_journey_plan.fieldmate_journey_plan.build_days';

frappe.ui.form.on('FieldMate Journey Plan', {
	refresh(frm) {
		// Submitted or cancelled, the days are history and must not move under a rep who is
		// already walking them.
		if (frm.doc.docstatus !== 0) return;

		const empty = !(frm.doc.days || []).length;
		const label = empty ? __('Generate Days') : __('Regenerate Days');

		frm.add_custom_button(label, () => confirm_then_build(frm));
		// Primary while the plan is empty: on a new plan it is the only thing to do, and
		// on_submit refuses a plan with no days anyway.
		frm.change_custom_button_type(label, null, empty ? 'primary' : 'default');
	},
});

function confirm_then_build(frm) {
	const missing = ['field_user', 'from_date', 'to_date'].filter((f) => !frm.doc[f]);
	if (missing.length) {
		frappe.msgprint({
			title: __('Not enough to work with'),
			message: __('Set the field user and both dates first.'),
			indicator: 'orange',
		});
		return;
	}

	// Regenerating throws away hand edits. Planners do edit single days - swapping a route for
	// one morning is normal - so this asks rather than assuming.
	if ((frm.doc.days || []).length) {
		frappe.confirm(
			__('This replaces all {0} day rows, including any you changed by hand. Continue?',
				[frm.doc.days.length]),
			() => build(frm),
		);
		return;
	}

	build(frm);
}

function build(frm) {
	frappe.call({
		method: METHOD,
		args: {
			field_user: frm.doc.field_user,
			from_date: frm.doc.from_date,
			to_date: frm.doc.to_date,
			holiday_list: frm.doc.holiday_list || null,
		},
		freeze: true,
		freeze_message: __('Working out the days…'),
		callback(r) {
			if (!r.message) return;
			const days = r.message.days || [];

			frm.clear_table('days');
			days.forEach((row) => frm.add_child('days', row));
			frm.refresh_field('days');

			// Only filled in, never overwritten: a planner who picked a holiday list on purpose
			// keeps theirs.
			if (r.message.holiday_list && !frm.doc.holiday_list) {
				frm.set_value('holiday_list', r.message.holiday_list);
			}

			report(days);
		},
	});
}

// Says what it found rather than that it ran. "Days generated" looks identical whether the rep
// got a month of routes or a month of blanks, and a plan of blank days is the common failure -
// an inactive beat, or one assigned to somebody else. That should be visible here, on the desk,
// not discovered on a phone at 9am.
function report(days) {
	const planned = days.filter((d) => d.beat).length;
	frappe.show_alert(
		{
			message: planned
				? __('{0} days, {1} with a route.', [days.length, planned])
				: __('{0} days, none with a route. Check which beats are assigned to this rep and active.',
					[days.length]),
			indicator: planned ? 'green' : 'orange',
		},
		7,
	);
}
