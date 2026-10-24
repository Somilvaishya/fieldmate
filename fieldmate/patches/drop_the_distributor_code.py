"""Drop `Customer.fm_distributor_code`. A depot's code is its own id.

The field was a Data column somebody filled in by hand, held `unique`, and described as "what this
party calls itself in their own books". It answered the question the Customer's primary key had
already answered, and two names for one party is a reconciliation somebody does by hand at month
end. Nothing on the portal ever rendered it: `api.portal.whoami` returned it under
`distributor_code`, and no page read that key - it now returns the Customer id under the same name,
so every screen reads the same before and after.

**This destroys whatever was typed into it**, which is why the values are printed before they go.
A Custom Field deleted takes its column with it, and there is no undo short of a restore. The
print is the record: if somebody wants those codes, they are in the migrate log.

Safe to re-run: a site that has already lost the field is left alone.
"""

import frappe

DOCTYPE = "Customer"
FIELD = "fm_distributor_code"


def execute():
	if not frappe.db.exists("DocType", DOCTYPE):
		return

	custom = frappe.db.exists("Custom Field", {"dt": DOCTYPE, "fieldname": FIELD})
	if not custom:
		return

	# Read what is about to be lost, before the column goes. Printed rather than stored: this is a
	# field nobody reads, and a table of dead codes nobody reads either would be the same mistake
	# with an extra step.
	try:
		filled = frappe.db.sql(
			f"select name, `{FIELD}` from `tab{DOCTYPE}` "
			f"where `{FIELD}` is not null and `{FIELD}` != ''",
			as_dict=True)
	except Exception:
		# The column is already gone while the Custom Field row survives - a half-finished delete
		# on some earlier run. Nothing to report, and the row below still needs removing.
		filled = []

	if filled:
		print(f"  FieldMate: dropping {DOCTYPE}.{FIELD}, which held a code on "
		      f"{len(filled)} part{'y' if len(filled) == 1 else 'ies'}:")
		for row in filled:
			print(f"    {row['name']}: {row[FIELD]}")
		print("  FieldMate: each of those parties is now known by its own id, which is the name "
		      "printed first on each line above.")
	else:
		print(f"  FieldMate: dropping {DOCTYPE}.{FIELD}; no party had one.")

	# `delete_doc` on the Custom Field is what removes the column too - dropping the column by
	# hand would leave the Custom Field row behind, and the next migrate would put the column
	# straight back.
	frappe.delete_doc("Custom Field", custom, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype=DOCTYPE)
