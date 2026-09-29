// Changing when a beat runs does not move a plan that was already generated from it.
//
// The plan holds dates, the beat holds a rule, and generating is a one-way copy. So a beat
// moved from Saturday to Monday keeps running on Saturday for every rep whose plan was built
// before the change - and the phone, which reads the plan, shows no route on the Monday and a
// route on the Saturday nobody is working. Saying so at the moment of the edit is cheaper than
// a rep finding out in a market.

function warn_plans_are_stale(frm) {
	// A beat being created has no plans built from it yet.
	if (frm.is_new()) return;

	frm.dashboard.clear_comment();
	frm.dashboard.add_comment(
		__('Journey plans already generated from this beat keep their old dates. After saving, regenerate the plan for each rep on this route.'),
		'orange',
		true,
	);
}

frappe.ui.form.on('FieldMate Beat', {
	refresh(frm) {
		frm.dashboard.clear_comment();
	},
	visit_day: warn_plans_are_stale,
	frequency: warn_plans_are_stale,
	week_pattern: warn_plans_are_stale,
});
