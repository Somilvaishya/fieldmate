"""Bring existing reps into line with the company their Employee record says.

The rule asked for is that HR owns which company somebody is employed by, and the controller now
applies it on every save. That only reaches a record when somebody saves it, so a rep created
last year sits on whatever company the session default happened to be when their record was made
- which on a single-company site is the same answer, and on a multi-company site is a rep filed
against the wrong one until a human opens the form.

Only rows where the Employee says something different are touched, and only rows that have an
Employee at all. A rep with no Employee link is left exactly as they are: there is nothing to
take the answer from, and guessing is worse than the stale value.

One statement, not a save per rep. The column is being corrected rather than decided, and running
the controller over each one would re-run territory permission syncing for every rep on the site
to change a single field - which is the lesson `stamp_order_kind` records about patches that save.

Safe to re-run: after it runs there is nothing left that disagrees.
"""

import frappe


def execute():
	if not frappe.db.has_column("FieldMate Field User", "employee"):
		return

	wrong = frappe.db.sql("""
		select fu.name, fu.company as was, e.company as should_be
		from `tabFieldMate Field User` fu
		join `tabEmployee` e on e.name = fu.employee
		where ifnull(e.company, '') != ''
		  and ifnull(fu.company, '') != e.company
	""", as_dict=True)

	if not wrong:
		print("  FieldMate: every rep with an Employee already sits in that employee's company")
		return

	frappe.db.sql("""
		update `tabFieldMate Field User` fu
		join `tabEmployee` e on e.name = fu.employee
		set fu.company = e.company
		where ifnull(e.company, '') != ''
		  and ifnull(fu.company, '') != e.company
	""")

	for row in wrong:
		print(f"  FieldMate: {row.name} moved from {row.was or 'no company'} to {row.should_be} "
		      f"(their Employee record's company)")
	print(f"  FieldMate: {len(wrong)} rep(s) brought into line with HR")
