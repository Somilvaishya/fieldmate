"""The Connections tab on every FieldMate form, as Customer and Sales Order have theirs.

Each tab is a `<doctype>_dashboard.py`. Frappe counts a connection by filtering the other DocType
on one field (`fieldname`, or the per-DocType `non_standard_fieldnames`), or reads it off this
document's own field or child table (`internal_links`). A field name that is wrong does not fail
anywhere: the count quietly comes back 0, and the tab says a rep has no visits. So every name is
checked here against the DocType it claims to be on.
"""

import frappe
from frappe.desk.notifications import get_open_count

from fieldmate.tests.test_outlet import OutletFixture

# Fields whose only job is bookkeeping: an amendment, or the stock count before this one.
NOT_A_CONNECTION = ("amended_from", "previous_stock")


def module_doctypes():
	return frappe.get_all("DocType", {"module": "FieldMate", "istable": 0, "issingle": 0}, pluck="name")


def tab(doctype):
	return frappe.get_meta(doctype).get_dashboard_data()


class TestEveryConnectionResolves(OutletFixture):
	def test_every_item_is_counted_by_a_field_that_exists(self):
		for doctype in module_doctypes():
			data = tab(doctype)
			own = frappe.get_meta(doctype)
			for group in data.transactions:
				for item in group["items"]:
					where = f"{doctype} -> {item}"
					self.assertTrue(frappe.db.exists("DocType", item), where)
					internal = (data.get("internal_links") or {}).get(item)
					if isinstance(internal, str):
						self.assertTrue(own.has_field(internal), where)
					elif internal:
						table, field = internal
						self.assertTrue(own.has_field(table), where)
						self.assertTrue(frappe.get_meta(own.get_field(table).options).has_field(field), where)
					else:
						field = (data.get("non_standard_fieldnames") or {}).get(item, data.fieldname)
						linked = frappe.get_meta(item).get_field(field)
						self.assertTrue(linked, f"{where} by {field}")
						self.assertEqual(linked.options, doctype, f"{where} by {field}")

	def test_every_doctype_something_points_at_has_a_tab(self):
		pointed_at = set(
			frappe.get_all(
				"DocField",
				filters={
					"fieldtype": "Link",
					"parent": ["in", module_doctypes()],
					"fieldname": ["not in", NOT_A_CONNECTION],
				},
				pluck="options",
			)
		)
		missing = sorted(d for d in pointed_at & set(module_doctypes()) if not tab(d).transactions)
		self.assertEqual(missing, [])

	def test_the_counts_run_for_a_real_rep_and_shop(self):
		rep = self.make_field_user()
		outlet = self.make_outlet()
		for doctype, name in (("FieldMate Field User", rep.name), ("FieldMate Outlet", outlet.name)):
			counts = get_open_count(doctype, name)["count"]
			found = {row["doctype"] for row in counts["external_links_found"]}
			self.assertIn("FieldMate Visit", found, doctype)
