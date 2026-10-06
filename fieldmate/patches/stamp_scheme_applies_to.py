"""Say out loud what every existing scheme already was: a retailer scheme.

`FieldMate Scheme` grew `applies_to` so that a scheme written for a shop cannot fire on a
distributor's own purchase (Phase 1, step 8). Every scheme written before that is a retailer
scheme - there was no other kind - and a Select column added by a migration is empty, not
defaulted.

Left empty it would still behave correctly: `covers_sale` reads a blank as Secondary, for exactly
this reason. The column is filled in anyway, because a manager filtering Schemes by Applies To
would otherwise see none of the ones that already exist, and a filter that silently excludes
everything written so far is worse than one that errors.

One statement rather than a save apiece: these are submitted documents, the column is being
stated rather than decided, and re-running a scheme's controller would recompile every spec on
the site against today's prices.
"""

import frappe


def execute():
	if not frappe.db.has_column("FieldMate Scheme", "applies_to"):
		return

	frappe.db.sql("""
		update `tabFieldMate Scheme`
		set applies_to = 'Secondary'
		where applies_to is null or applies_to = ''
	""")
	print(f"  FieldMate: {frappe.db.count('FieldMate Scheme', {'applies_to': 'Secondary'})} "
	      f"scheme(s) are for orders at a shop")
