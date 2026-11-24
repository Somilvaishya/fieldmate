"""`before_uninstall` clears what FieldMate left on other apps' records, and only that.

Every destructive step runs inside a savepoint and is rolled back, so the site keeps its
permissions, jobs and fields. File deletion is never run for real: it removes the file from
disk, which no rollback brings back, so it is checked through the calls it makes.
"""

from unittest.mock import patch

import frappe

from fieldmate import uninstall
from fieldmate.tests.test_field_user import FieldUserFixture


class TestUninstall(FieldUserFixture):
	def undo(self, savepoint):
		frappe.db.rollback(save_point=savepoint)
		frappe.clear_cache()

	def test_the_hook_is_wired(self):
		self.assertIn(
			"fieldmate.uninstall.before_uninstall",
			frappe.get_hooks("before_uninstall", app_name="fieldmate"),
		)

	def test_every_fm_custom_field_is_on_the_list(self):
		# A field added to install.py and forgotten here would outlive the app.
		listed = {(dt, f) for dt, fields in uninstall.custom_fields().items() for f in fields}
		on_site = {
			(r.dt, r.fieldname)
			for r in frappe.get_all(
				"Custom Field", filters={"fieldname": ("like", "fm\\_%")}, fields=["dt", "fieldname"]
			)
		}
		self.assertFalse(on_site - listed, f"not removed on uninstall: {sorted(on_site - listed)}")

	def test_custom_fields_go_and_their_columns_stay(self):
		self.assertTrue(frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": "fm_tier"}))
		frappe.db.savepoint("fm_uninstall_fields")
		try:
			self.assertGreater(uninstall.remove_custom_fields(), 0)
			self.assertFalse(frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": "fm_tier"}))
			self.assertFalse(frappe.get_meta("Customer").has_field("fm_tier"))
			# The data a site typed in is still there for a reinstall.
			self.assertTrue(frappe.db.has_column("Customer", "fm_tier"))
		finally:
			self.undo("fm_uninstall_fields")
		self.assertTrue(frappe.get_meta("Customer").has_field("fm_tier"))

	def test_only_the_territory_permissions_fieldmate_wrote_are_removed(self):
		field_user = self.make_field_user()
		user, territory = frappe.db.get_value("FieldMate Field User", field_user.name, ["user", "territory"])
		ours = {"user": user, "allow": "Territory", "for_value": territory}
		self.assertTrue(frappe.db.exists("User Permission", ours))

		# Somebody with no field user record, restricted by hand.
		stranger = self.make_user(role=None)
		theirs = frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": stranger,
				"allow": "Territory",
				"for_value": self.make_territory(),
				"apply_to_all_doctypes": 1,
			}
		).insert(ignore_permissions=True)

		frappe.db.savepoint("fm_uninstall_perms")
		try:
			self.assertGreaterEqual(uninstall.remove_territory_permissions(), 1)
			self.assertFalse(frappe.db.exists("User Permission", ours))
			self.assertTrue(frappe.db.exists("User Permission", theirs.name))
		finally:
			self.undo("fm_uninstall_perms")
		frappe.delete_doc("User Permission", theirs.name, force=True, ignore_permissions=True)

	def test_scheduled_jobs_go_and_nobody_elses(self):
		self.assertTrue(frappe.db.exists("Scheduled Job Type", {"method": ("like", "fieldmate.%")}))
		frappe.db.savepoint("fm_uninstall_jobs")
		try:
			uninstall.remove_scheduled_jobs()
			self.assertFalse(frappe.db.exists("Scheduled Job Type", {"method": ("like", "fieldmate.%")}))
			self.assertTrue(frappe.db.exists("Scheduled Job Type", {"method": ("like", "frappe.%")}))
		finally:
			self.undo("fm_uninstall_jobs")

	def test_files_on_fieldmate_documents_are_deleted_through_the_controller(self):
		field_user = self.make_field_user()
		ours = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{self.uid('sel')}.txt",
				"content": b"selfie",
				"is_private": 1,
				"attached_to_doctype": "FieldMate Field User",
				"attached_to_name": field_user.name,
			}
		).insert(ignore_permissions=True)
		theirs = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{self.uid('oth')}.txt",
				"content": b"other",
				"is_private": 1,
				"attached_to_doctype": "User",
				"attached_to_name": field_user.user,
			}
		).insert(ignore_permissions=True)
		self.track("File", ours.name)
		self.track("File", theirs.name)

		with patch("frappe.delete_doc") as delete_doc:
			uninstall.remove_attached_files()
		deleted = {c.args[1] for c in delete_doc.call_args_list if c.args[0] == "File"}
		self.assertIn(ours.name, deleted)
		self.assertNotIn(theirs.name, deleted)

	def test_it_runs_end_to_end(self):
		frappe.db.savepoint("fm_uninstall_all")
		try:
			with patch("fieldmate.uninstall.remove_attached_files", return_value=0):
				uninstall.before_uninstall()
		finally:
			self.undo("fm_uninstall_all")
