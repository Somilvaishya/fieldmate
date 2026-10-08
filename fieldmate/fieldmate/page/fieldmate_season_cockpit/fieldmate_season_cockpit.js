// Season cockpit — booked, allocated, delivered, paid.
//
// Three cuts of the same bookings: by state, so the shape of the season is visible at a glance;
// by party, because the next question is always "and which distributor is that"; and by SKU,
// because the one after that is "what are we short of".
//
// Everything is read from the documents that hold it. This page keeps no numbers, which is why
// it is safe to leave open and refresh.

const METHOD = 'fieldmate.fieldmate.page.fieldmate_season_cockpit.fieldmate_season_cockpit';

frappe.pages['fieldmate-season-cockpit'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Season Cockpit'),
		single_column: true,
	});

	const state = { season: null };

	const season_field = page.add_field({
		fieldname: 'season', label: __('Season'), fieldtype: 'Select', options: [],
		change: () => { state.season = season_field.get_value(); load(); },
	});

	const $body = $('<div class="fm-cockpit"></div>').appendTo(page.main);

	page.set_primary_action(__('Refresh'), () => load());
	page.add_menu_item(__('Who is late'), () => show_overdue());

	load_seasons();

	function load_seasons() {
		frappe.call(`${METHOD}.seasons`).then((r) => {
			const rows = r.message || [];
			if (!rows.length) {
				$body.html(blank(__('No season has been set up yet.')));
				return;
			}
			season_field.df.options = rows.map((row) => ({
				value: row.name,
				label: `${row.season_name}${row.locked ? ' · ' + __('locked') : ''}`
					+ ` — ${row.bookings} ${row.bookings === 1 ? 'booking' : 'bookings'}`,
			}));
			season_field.refresh();
			season_field.set_value(rows[0].name);
		});
	}

	function load() {
		if (!state.season) return;
		frappe.dom.freeze(__('Reading…'));
		frappe.call(`${METHOD}.summary`, { season: state.season })
			.then((r) => render(r.message))
			.always(() => frappe.dom.unfreeze());
	}

	function render(s) {
		if (!s) return;
		if (!s.bookings) {
			$body.html(blank(__('{0} has no bookings against it yet.', [s.season_name])));
			return;
		}
		$body.html([headline(s), states(s), parties(s), skus(s)].join(''));
	}

	function headline(s) {
		// The cutoff, said out loud. "Why can nobody change this booking" is a support call
		// that should be answerable from the page it is asked about.
		const lock = s.locked
			? `<span class="indicator-pill orange">${__('Book closed for changes')}</span>`
			: `<span class="indicator-pill green">${__('Open until {0}',
				[frappe.datetime.str_to_user(s.change_cutoff || s.booking_to)])}</span>`;

		return `<div class="mb-4">
			<h4>${esc(s.season_name)} ${lock}</h4>
			<p class="text-muted">
				${__('Festival {0} · delivery {1} to {2} · advance {3}%', [
					frappe.datetime.str_to_user(s.festival_date),
					frappe.datetime.str_to_user(s.delivery_from),
					frappe.datetime.str_to_user(s.delivery_to),
					s.advance_pct || 0])}
			</p>
			<div class="row">
				${tile(__('Bookings'), s.bookings)}
				${tile(__('Parties'), s.parties)}
				${tile(__('Booked value'), money(s.value))}
				${tile(__('Still owing'), money(s.owing), s.owing > 0 ? 'text-danger' : '')}
			</div>
		</div>`;
	}

	function tile(label, value, cls = '') {
		return `<div class="col-sm-3"><div class="card p-3 mb-2">
			<div class="text-muted small">${esc(label)}</div>
			<div class="h5 mb-0 ${cls}">${esc(String(value))}</div>
		</div></div>`;
	}

	function states(s) {
		// Every state, including the empty ones: a row missing from a summary reads as a state
		// that does not exist, and "nothing has been delivered yet" is an answer somebody needs.
		const rows = s.by_state.map((row) => `<tr>
			<td>${esc(row.state)}</td>
			<td class="text-right">${row.bookings}</td>
			<td class="text-right">${money(row.value)}</td>
			<td class="text-right">${money(row.paid)}</td>
		</tr>`).join('');

		return section(__('By state'), `<thead><tr>
			<th>${__('State')}</th><th class="text-right">${__('Bookings')}</th>
			<th class="text-right">${__('Value')}</th><th class="text-right">${__('Paid')}</th>
		</tr></thead><tbody>${rows}</tbody>`);
	}

	function parties(s) {
		const rows = s.by_party.map((row) => `<tr>
			<td>${esc(row.customer_name || row.customer)}</td>
			<td>${esc(row.state)}</td>
			<td class="text-right">${row.bookings}</td>
			<td class="text-right">${money(row.value)}</td>
			<td class="text-right">${money(row.paid)}</td>
			<td class="text-right ${row.owing > 0 ? 'text-danger' : ''}">${money(row.owing)}</td>
		</tr>`).join('');

		return section(__('By party'), `<thead><tr>
			<th>${__('Party')}</th><th>${__('Furthest back')}</th>
			<th class="text-right">${__('Bookings')}</th><th class="text-right">${__('Value')}</th>
			<th class="text-right">${__('Paid')}</th><th class="text-right">${__('Owing')}</th>
		</tr></thead><tbody>${rows}</tbody>`, __('Largest owing first — this is the list you '
			+ 'telephone from. "Furthest back" is the party\'s least advanced booking, because '
			+ 'that is the one holding them up.'));
	}

	function skus(s) {
		const rows = s.by_sku.map((row) => `<tr>
			<td>${esc(row.item_code)}</td>
			<td>${esc(row.item_name || '')}</td>
			<td class="text-right">${qty(row.booked_qty)}</td>
			<td class="text-right">${qty(row.reserved_qty)}</td>
			<td class="text-right">${qty(row.delivered_qty)}</td>
			<td class="text-right ${row.short > 0 ? 'text-danger' : ''}">${qty(row.short)}</td>
		</tr>`).join('');

		return section(__('By SKU'), `<thead><tr>
			<th>${__('Item')}</th><th>${__('Name')}</th>
			<th class="text-right">${__('Booked')}</th><th class="text-right">${__('Reserved')}</th>
			<th class="text-right">${__('Delivered')}</th><th class="text-right">${__('Short')}</th>
		</tr></thead><tbody>${rows}</tbody>`, __('Quantities are in stock units throughout — '
			+ 'what the warehouse counts in and what a reservation is held in.'));
	}

	function show_overdue() {
		if (!state.season) return frappe.msgprint(__('Choose a season first.'));
		frappe.call(`${METHOD}.overdue`, { season: state.season }).then((r) => {
			const rows = r.message || [];
			if (!rows.length) {
				frappe.msgprint(__('Nothing is overdue on this season.'));
				return;
			}
			const body = rows.map((row) => `<tr>
				<td>${esc(row.customer_name || row.customer)}</td>
				<td>${esc(row.order)}</td>
				<td class="text-right">${row.days_late}</td>
				<td class="text-right">${money(row.short)}</td>
			</tr>`).join('');
			frappe.msgprint({
				title: __('Overdue'),
				message: `<table class="table table-bordered table-sm"><thead><tr>
					<th>${__('Party')}</th><th>${__('Booking')}</th>
					<th class="text-right">${__('Days late')}</th>
					<th class="text-right">${__('Short')}</th>
				</tr></thead><tbody>${body}</tbody></table>
				<p class="text-muted small">${__('Read from the Sales Order\\'s own payment '
					+ 'schedule, which ERPNext built from the season\\'s payment terms. The rep '
					+ 'and their manager are told once a day by the scheduled reminder.')}</p>`,
			});
		});
	}

	function section(title, table, note = '') {
		return `<h5 class="mt-4">${esc(title)}</h5>`
			+ (note ? `<p class="text-muted small">${esc(note)}</p>` : '')
			+ `<table class="table table-bordered table-sm">${table}</table>`;
	}

	function money(v) { return frappe.format(v || 0, { fieldtype: 'Currency' }); }
	function qty(v) { return frappe.format(v || 0, { fieldtype: 'Float', precision: 2 }); }
	function esc(v) { return frappe.utils.escape_html(String(v == null ? '' : v)); }
	function blank(words) {
		return `<div class="text-muted" style="padding:32px 0">${esc(words)}</div>`;
	}
};
