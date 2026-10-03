from unittest.mock import patch

import frappe

from fieldmate import compat
from fieldmate.setup import install
from fieldmate.tests.base import FieldMateTestCase


class TestVersionGuard(FieldMateTestCase):
	"""The guard exists so an unsupported host fails loudly at install time rather than
	quietly at month end. Untested, it is just a comment."""

	def test_supported_host_passes(self):
		install.check_host_versions()  # must not raise on this bench

	def test_host_below_minimum_is_refused(self):
		with patch.dict(compat.REQUIRED_APPS, {"erpnext": (99, 0)}, clear=False):
			with self.assertRaises(frappe.ValidationError) as ctx:
				install.check_host_versions()
		message = str(ctx.exception)
		self.assertIn("erpnext", message)
		self.assertIn("99.0", message)

	def test_missing_required_app_is_refused(self):
		with patch.dict(compat.REQUIRED_APPS, {"not_a_real_app": (1, 0)}, clear=False):
			with self.assertRaises(frappe.ValidationError) as ctx:
				install.check_host_versions()
		self.assertIn("not installed", str(ctx.exception))

	def test_message_names_what_was_detected(self):
		"""A refusal that does not say what it found makes the operator guess."""
		with patch.dict(compat.REQUIRED_APPS, {"erpnext": (99, 0)}, clear=False):
			with self.assertRaises(frappe.ValidationError) as ctx:
				install.check_host_versions()
		self.assertIn("Detected", str(ctx.exception))
		self.assertIn("frappe", str(ctx.exception))

	def test_absent_optional_app_is_fine(self):
		"""hrms may be missing entirely. That must not block an install."""
		with patch.object(compat, "is_installed", lambda app: app == "erpnext"):
			install.check_host_versions()

	def test_optional_app_present_but_too_old_is_refused(self):
		"""Absent is fine; present-but-ancient is not, because we would call into it
		expecting behaviour it does not have."""
		if not compat.is_installed("hrms"):
			self.skipTest("hrms not installed on this site")
		with patch.dict(compat.OPTIONAL_APPS, {"hrms": (99, 0)}, clear=False):
			with self.assertRaises(frappe.ValidationError):
				install.check_host_versions()


class TestRoles(FieldMateTestCase):
	def test_all_six_roles_exist(self):
		for role_name, _ in install.ROLES:
			self.assertTrue(frappe.db.exists("Role", role_name), f"{role_name} missing")

	def test_field_roles_have_no_desk_access(self):
		"""Rep and Distributor live in the PWA and the portal, never in Desk."""
		for role_name in ("FieldMate Field Rep", "FieldMate Distributor"):
			self.assertEqual(frappe.db.get_value("Role", role_name, "desk_access"), 0)

	def test_creating_roles_twice_is_safe(self):
		before = frappe.db.count("Role", {"role_name": ["like", "FieldMate%"]})
		install.create_roles()
		self.assertEqual(frappe.db.count("Role", {"role_name": ["like", "FieldMate%"]}), before)

	def test_no_field_role_can_touch_accounting(self):
		"""The check finance will ask about."""
		for doctype in ("Payment Entry", "Sales Invoice", "Journal Entry", "GL Entry"):
			for role in ("FieldMate Field Rep", "FieldMate Distributor"):
				perms = frappe.get_all(
					"Custom DocPerm",
					filters={"parent": doctype, "role": role},
					fields=["create", "write", "submit"],
				) + frappe.get_all(
					"DocPerm",
					filters={"parent": doctype, "role": role},
					fields=["create", "write", "submit"],
				)
				for p in perms:
					self.assertFalse(
						p.get("create") or p.get("write") or p.get("submit"),
						f"{role} has write access to {doctype}",
					)


class TestCustomerChannelFields(FieldMateTestCase):
	"""A party we bill is an ERPNext Customer with a tier, not a record of our own."""

	def test_every_field_is_on_customer(self):
		for spec in install.CUSTOMER_FIELDS:
			self.assertTrue(
				frappe.db.exists("Custom Field",
				                 {"dt": "Customer", "fieldname": spec["fieldname"]}),
				f"{spec['fieldname']} missing from Customer",
			)

	def test_running_it_twice_adds_nothing(self):
		before = frappe.db.count("Custom Field", {"dt": "Customer",
		                                          "fieldname": ["like", "fm_%"]})
		install.create_customer_fields()
		self.assertEqual(
			frappe.db.count("Custom Field", {"dt": "Customer", "fieldname": ["like", "fm_%"]}),
			before,
		)

	def test_a_changed_description_is_carried_across(self):
		"""Updated rather than skipped. Options and wording will grow, and a field created once
		and never revisited is how a site ends up with a tier list the code does not know."""
		name = frappe.db.get_value("Custom Field",
		                           {"dt": "Customer", "fieldname": "fm_tier"}, "name")
		frappe.db.set_value("Custom Field", name, "description", "stale wording")
		install.create_customer_fields()
		wanted = next(s for s in install.CUSTOMER_FIELDS if s["fieldname"] == "fm_tier")
		self.assertEqual(frappe.db.get_value("Custom Field", name, "description"),
		                 wanted["description"])

	def test_credit_is_not_duplicated_onto_customer(self):
		"""Credit limit, payment terms and price list stay the Customer's own. A second copy of
		a credit limit is a second number to disagree with the first."""
		ours = {s["fieldname"] for s in install.CUSTOMER_FIELDS}
		for banned in ("fm_credit_limit", "fm_credit_days", "fm_payment_terms",
		               "fm_price_list", "fm_territory", "fm_gstin"):
			self.assertNotIn(banned, ours)

	def test_a_tier_the_code_does_not_know_is_not_offered(self):
		"""The option list is the contract between this field and `channel.resolve`."""
		spec = next(s for s in install.CUSTOMER_FIELDS if s["fieldname"] == "fm_tier")
		offered = {t for t in spec["options"].split("\n") if t}
		self.assertEqual(offered, {"CFA", "Super Stockist", "Distributor", "Sub-stockist",
		                           "Wholesaler", "Modern Trade"})
