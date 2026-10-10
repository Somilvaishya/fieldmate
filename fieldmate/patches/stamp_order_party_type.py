"""Say out loud what every existing order already was: an order on a shop.

`FieldMate Order` grew a `party_type` so that a primary order can name a Customer instead of an
outlet (Phase 1, step 5c). Every order written before that has an outlet and no idea it needed to
say so, and a Select column added by a migration is empty, not defaulted.

Left empty, those orders would read as neither kind. The controller infers the type where a
caller did not send one, so nothing breaks in the app - but a report filtering on Party Type
would quietly show none of them, and a filter that silently excludes history is worse than one
that errors.

Written with one statement rather than a document save per order: this touches every order on the
site, the column is being filled in rather than decided, and re-running the controller over a
submitted document to set one Select would reprice every one of them against today's price list.
"""

import frappe


def execute():
	if not frappe.db.has_column("FieldMate Order", "party_type"):
		return

	frappe.db.sql("""
		update `tabFieldMate Order`
		set party_type = 'Outlet'
		where (party_type is null or party_type = '') and outlet is not null
	""")

	orphans = frappe.db.count("FieldMate Order", {"party_type": ["in", ("", None)]})
	print(f"  FieldMate: {frappe.db.count('FieldMate Order', {'party_type': 'Outlet'})} order(s) "
	      f"are on a shop")
	if orphans:
		# An order with neither a party type nor an outlet. Reported rather than guessed at:
		# there is nothing to infer from, and inventing a party on a submitted order is worse
		# than leaving one row for somebody to look at.
		print(f"    - {orphans} order(s) have no outlet and no party type. Left alone.")
