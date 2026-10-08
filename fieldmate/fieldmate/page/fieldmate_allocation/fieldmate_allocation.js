// Season allocation — preview, then apply.
//
// A short season is a commercial decision: one distributor is told they are getting two thirds of
// what they asked for, and another is not. Nobody should make that by pressing a button and
// seeing what happened, so this page shows the whole split first and the same arithmetic runs
// again when it is applied.
//
// Everything on the screen is read back from ERPNext. "Available" is its figure, and what is
// "held" is its Stock Reservation Entries - this page keeps no numbers of its own, because a
// number kept here would be a claim rather than a record.

const METHOD = 'fieldmate.fieldmate.page.fieldmate_allocation.fieldmate_allocation';

const RULES = [
	{ value: 'Advance First', label: __('Advance First'),
	  hint: __('Whoever has paid the largest share of their own booking is served first.') },
	{ value: 'First Booked', label: __('First Booked'),
	  hint: __('The queue, in the order the orders were taken.') },
	{ value: 'Pro Rata', label: __('Pro Rata'),
	  hint: __('Everybody is cut by the same proportion.') },
];

frappe.pages['fieldmate-allocation'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Season Allocation'),
		single_column: true,
	});

	const state = { season: null, rule: 'Advance First', plan: null };

	const season_field = page.add_field({
		fieldname: 'season', label: __('Season'), fieldtype: 'Select', options: [],
		change: () => { state.season = season_field.get_value(); render_plan(null); },
	});

	const rule_field = page.add_field({
		fieldname: 'rule', label: __('Rule'), fieldtype: 'Select',
		options: RULES.map((r) => ({ value: r.value, label: r.label })),
		default: state.rule,
		change: () => { state.rule = rule_field.get_value(); render_plan(null); },
	});

	const $body = $('<div class="fm-alloc"></div>').appendTo(page.main);

	page.set_primary_action(__('Preview'), () => run('preview'));
	page.add_button(__('Apply'), () => confirm_then('apply'), { btn_class: 'btn-default' });
	page.add_button(__('Revert'), () => confirm_then('revert'), { btn_class: 'btn-default' });

	load_seasons();

	function load_seasons() {
		frappe.call(`${METHOD}.seasons`).then((r) => {
			const rows = r.message || [];
			if (!rows.length) {
				$body.html(blank(__('No season has a released booking against it yet. A booking '
					+ 'waiting for its advance has no Sales Order, so there is nothing to reserve.')));
				return;
			}
			season_field.df.options = rows.map((row) => ({
				value: row.name,
				label: `${row.season_name} — ${row.bookings} ${row.bookings === 1 ? 'booking' : 'bookings'}`,
			}));
			season_field.refresh();
			season_field.set_value(rows[0].name);
		});
	}

	function run(action) {
		if (!state.season) {
			frappe.msgprint(__('Choose a season first.'));
			return;
		}
		const args = action === 'revert'
			? { season: state.season }
			: { season: state.season, rule: state.rule };

		frappe.dom.freeze(__('Working…'));
		frappe.call(`${METHOD}.${action}`, args)
			.then((r) => {
				if (action === 'revert') {
					frappe.show_alert({
						message: __('Released {0} reservation(s) across {1} order(s).',
							[r.message.released, r.message.sales_orders]),
						indicator: 'blue',
					});
					run('preview');
					return;
				}
				render_plan(r.message);
				if (action === 'apply') {
					frappe.show_alert({
						message: __('Reserved {0} line(s).', [r.message.reserved_entries]),
						indicator: 'green',
					});
				}
			})
			.always(() => frappe.dom.unfreeze());
	}

	// Two steps for anything that moves stock. Apply reserves against real Sales Orders and
	// revert takes it back; neither is something a thumb should do by brushing past.
	function confirm_then(action) {
		const words = action === 'apply'
			? __('This reserves stock against every booking of this season, in ERPNext. '
				+ 'Reverting gives it back, except anything already delivered.')
			: __('This cancels every reservation this season is holding, except anything '
				+ 'already delivered. The stock goes back to being available to anyone.');
		frappe.confirm(words, () => run(action));
	}

	function render_plan(plan) {
		state.plan = plan;
		if (!plan) {
			$body.html(blank(__('Choose a season and a rule, then press Preview. '
				+ 'Nothing is reserved until you press Apply.')));
			return;
		}
		if (!plan.items.length) {
			$body.html(blank(__('This season has released bookings but none of them has a line '
				+ 'to reserve against.')));
			return;
		}

		const rule = RULES.find((r) => r.value === plan.rule);
		const parts = [
			`<p class="text-muted">${frappe.utils.escape_html(rule ? rule.hint : '')}</p>`,
			summary(plan),
		];
		plan.items.forEach((item) => parts.push(item_table(item)));
		$body.html(parts.join(''));
	}

	function summary(plan) {
		const short = plan.items.filter((i) => i.short > 0).length;
		const tone = short ? 'orange' : 'green';
		const words = short
			? __('{0} of {1} item(s) cannot be met in full.', [short, plan.items.length])
			: __('Every booking can be met in full.');
		const held = plan.already_reserved
			? ` ${__('{0} reservation(s) are already held against this season — revert before '
				+ 'allocating again, or this preview is of what is left.',
			[plan.already_reserved])}`
			: '';
		return `<div class="mb-3"><span class="indicator-pill ${tone}">`
			+ `${frappe.utils.escape_html(words)}</span>`
			+ `<span class="text-muted">${frappe.utils.escape_html(held)}</span></div>`;
	}

	function item_table(item) {
		const head = `<h5 class="mt-4">${frappe.utils.escape_html(item.item_code)}`
			+ ` <span class="text-muted small">${frappe.utils.escape_html(item.warehouse || '')}`
			+ `</span></h5>`
			+ `<p class="text-muted small">`
			+ __('Asked {0}, available {1}, allocating {2}{3}',
				[fmt(item.asked), fmt(item.available), fmt(item.allocated),
					item.short ? __(', short by {0}', [fmt(item.short)]) : ''])
			+ ` ${frappe.utils.escape_html(item.uom || '')}</p>`;

		const rows = item.lines.map((line) => {
			const cut = line.allocated < line.asked;
			return `<tr>
				<td>${frappe.utils.escape_html(line.customer || '')}</td>
				<td>${frappe.utils.escape_html(line.order)}</td>
				<td>${frappe.utils.escape_html(String(line.order_date || ''))}</td>
				<td class="text-right">${fmt(line.advance_share * 100)}%</td>
				<td class="text-right">${fmt(line.asked)}</td>
				<td class="text-right ${cut ? 'text-danger' : ''}">${fmt(line.allocated)}</td>
			</tr>`;
		}).join('');

		return head + `<table class="table table-bordered table-sm">
			<thead><tr>
				<th>${__('Party')}</th><th>${__('Booking')}</th><th>${__('Booked')}</th>
				<th class="text-right">${__('Advance paid')}</th>
				<th class="text-right">${__('Asked')}</th>
				<th class="text-right">${__('Gets')}</th>
			</tr></thead><tbody>${rows}</tbody></table>`;
	}

	function fmt(value) {
		return frappe.format(value || 0, { fieldtype: 'Float', precision: 2 });
	}

	function blank(words) {
		return `<div class="text-muted" style="padding:32px 0">`
			+ `${frappe.utils.escape_html(words)}</div>`;
	}
};
