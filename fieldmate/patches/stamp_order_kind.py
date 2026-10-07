"""Say out loud what every existing order already was.

`FieldMate Order` grew an `order_kind` so that Phase 2 can tell a booking of a season from an
ordinary primary order. The kind was always derivable - an order on an outlet is secondary, an
order on a customer is primary - but it was never written down, and a Select column added by a
migration is empty, not defaulted.

No existing order can be a Booking. `FieldMate Season` arrives in the same migration as this
field, so on the day it runs there are no seasons and nothing to have booked into. An order that
*does* carry a season is left alone, so this stays safe to re-run on a site that has since taken
bookings.

Why the field at all, when `party_type` already implies it: a booking is a primary order that
also carries a season, so the kind is no longer a function of the party alone. Making it a stored
field rather than a property means a report, a filter and a KPI read the same answer the order
service wrote, rather than three places each re-deriving it.

One statement, not a save per order. The column is being filled in rather than decided, and
running the controller over a submitted document would reprice every one of them against today's
price list - the lesson `stamp_order_party_type` records.
"""

import frappe


def execute():
	if not frappe.db.has_column("FieldMate Order", "order_kind"):
		return

	# Every row, not only the empty ones. The first version of this patch guarded on
	# `order_kind is null or = ''` and stamped nothing, because the field carried a Select
	# default and **Frappe backfills every existing row with it when the column is added**. By
	# the time a post_model_sync patch runs there is nothing empty left to find, and two primary
	# orders on testerp2 were recorded as secondary. The default is gone and this derives.
	#
	# Safe to re-run: it writes what the party already says, and a Booking cannot exist yet.
	frappe.db.sql("""
		update `tabFieldMate Order`
		set order_kind = case when party_type = 'Customer' then 'Primary' else 'Secondary' end
		where season is null or season = ''
	""")

	counts = frappe.db.sql("""
		select order_kind, count(*) from `tabFieldMate Order` group by order_kind
	""")
	for kind, n in counts:
		print(f"  FieldMate: {n} order(s) are {kind or 'of no kind at all'}")
