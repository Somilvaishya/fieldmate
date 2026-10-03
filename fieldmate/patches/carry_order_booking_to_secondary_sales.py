"""Carry `enable_order_booking` onto `enable_secondary_sales`.

The old field named the one thing the app did: a rep books, the distributor delivers. That is
what we now call a secondary sale, and the setting is renamed to say so - with a second one
beside it for the primary sales Phase 1 adds.

Without this every existing site would come up with secondary sales **off**, because a field
that has just been created holds its default and nothing has told it otherwise. The DocType
default is 1, which covers a fresh site; a site that had deliberately turned order booking off
would be silently turned back on. So the old value is read and carried, and only a site with no
old value at all falls back to the default.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "FieldMate Settings"):
		return

	# Read the column directly. `frappe.get_single` would hand back a document built from the
	# current DocType, which no longer has the old field on it at all.
	old = frappe.db.sql(
		"""
		select value from `tabSingles`
		 where doctype = 'FieldMate Settings' and field = 'enable_order_booking'
		""",
		pluck=True,
	)
	if not old:
		return

	frappe.db.set_single_value("FieldMate Settings", "enable_secondary_sales", int(old[0] or 0))

	# The old row is left in `tabSingles`. Frappe ignores a value whose field is not on the
	# DocType, and keeping it means a site that rolls back to the previous version still has its
	# setting rather than a default.
	frappe.cache().delete_value("fieldmate_settings")
