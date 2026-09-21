import frappe

from fieldmate import compat
from fieldmate.tests.base import FieldMateTestCase


class TestCompat(FieldMateTestCase):
	def test_app_version_returns_tuple(self):
		self.assertTrue(compat.app_version("frappe"))
		self.assertIsInstance(compat.app_version("frappe")[0], int)

	def test_absent_app_returns_empty(self):
		self.assertEqual(compat.app_version("definitely_not_an_app"), ())
		self.assertEqual(compat.major("definitely_not_an_app"), 0)

	def test_capabilities_never_raises_without_hrms(self):
		"""A probe must never take the app down.

		frappe.db.has_column throws when the table is absent, which is normal whenever an
		optional app is on the bench but not installed on this site.
		"""
		caps = compat.capabilities()
		self.assertIn("has_hrms", caps)
		self.assertIsInstance(caps["checkin_has_geo"], bool)
		if not caps["has_hrms"]:
			self.assertFalse(caps["checkin_has_geo"])
			self.assertEqual(caps["hrms_major"], 0)

	def test_version_report_distinguishes_installed_from_on_bench(self):
		report = compat.version_report()
		self.assertIn("frappe", report)
		if not compat.is_installed("hrms") and compat.app_version("hrms"):
			self.assertIn("not installed on this site", report["hrms"])

	def test_required_apps_excludes_hrms(self):
		"""hrms is optional by design - create_employee_checkin degrades to None."""
		self.assertIn("erpnext", compat.REQUIRED_APPS)
		self.assertNotIn("hrms", compat.REQUIRED_APPS)
		self.assertIn("hrms", compat.OPTIONAL_APPS)

	def test_employee_checkin_skipped_without_hrms(self):
		if compat.is_installed("hrms"):
			self.skipTest("hrms installed; the absent-path is what this test covers")
		self.assertIsNone(
			compat.create_employee_checkin("nobody@example.com", "IN", frappe.utils.now())
		)

	def test_outstanding_is_zero_for_unknown_party(self):
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("no company on this site")
		self.assertEqual(compat.get_outstanding(self.uid("NOCUST"), company), 0)
