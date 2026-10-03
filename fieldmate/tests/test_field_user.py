import frappe

from fieldmate.services import field_user as svc
from fieldmate.tests.base import FieldMateTestCase


class FieldUserFixture(FieldMateTestCase):
	"""Builds its own territories and logins. Nothing here leans on site data, so the suite
	behaves the same on a fresh CI site as it does on testerp2."""

	def make_territory(self, parent=None):
		name = self.uid("TERR")
		doc = frappe.get_doc({
			"doctype": "Territory",
			"territory_name": name,
			"parent_territory": parent or "All Territories",
			"is_group": 1 if parent is None else 0,
		}).insert(ignore_permissions=True)
		self.track("Territory", doc.name)
		return doc.name

	def make_user(self, role="FieldMate Field Rep", enabled=1):
		email = f"{self.uid('fm').lower()}@fieldmate.test"
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": "Test",
			"last_name": "User",
			"user_type": "System User",
			"send_welcome_email": 0,
			"enabled": enabled,
		}).insert(ignore_permissions=True)
		self.track("User", user.name)
		if role:
			user.add_roles(role)
		if not enabled:
			user.enabled = 0
			user.save(ignore_permissions=True)
		return user.name

	def make_field_user(self, **kwargs):
		data = {
			"doctype": "FieldMate Field User",
			"user": kwargs.pop("user", None) or self.make_user(),
			"territory": kwargs.pop("territory", None) or self.make_territory(),
			"designation": "Field Rep",
			"status": "Active",
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Field User", doc.name)
		return doc

	def permissions_for(self, user):
		return frappe.get_all(
			"User Permission",
			filters={"user": user, "allow": "Territory"},
			fields=["for_value", "hide_descendants"],
		)


class TestFieldUserValidation(FieldUserFixture):
	def test_created_with_a_territory(self):
		doc = self.make_field_user()
		self.assertEqual(doc.status, "Active")
		self.assertEqual(doc.name, doc.user)

	def test_user_without_a_fieldmate_role_is_refused(self):
		plain = self.make_user(role=None)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_field_user(user=plain)
		self.assertIn("no FieldMate role", str(ctx.exception))

	def test_disabled_user_is_refused(self):
		off = self.make_user(enabled=0)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_field_user(user=off)
		self.assertIn("disabled", str(ctx.exception))

	def test_one_field_user_per_login(self):
		doc = self.make_field_user()
		with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
			frappe.get_doc({
				"doctype": "FieldMate Field User",
				"user": doc.user,
				"territory": self.make_territory(),
				"designation": "Field Rep",
			}).insert(ignore_permissions=True)
	def test_cannot_report_to_self(self):
		doc = self.make_field_user()
		doc.reports_to = doc.name
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.save(ignore_permissions=True)
		self.assertIn("report to themselves", str(ctx.exception))

	def test_reporting_loop_is_refused(self):
		"""A cycle would hang every roll-up that walks the chain."""
		a = self.make_field_user()
		# b reports to a
		b = self.make_field_user(reports_to=a.name)
		a.reports_to = b.name
		with self.assertRaises(frappe.ValidationError) as ctx:
			a.save(ignore_permissions=True)
		self.assertIn("loops back", str(ctx.exception))


class TestTerritoryScoping(FieldUserFixture):
	"""The security boundary. A rep in one district must not read another's outlets."""

	def test_user_permission_is_created(self):
		doc = self.make_field_user()
		perms = self.permissions_for(doc.user)
		self.assertEqual(len(perms), 1)
		self.assertEqual(perms[0].for_value, doc.territory)

	def test_descendants_stay_visible(self):
		"""Territory is a tree: a manager on a parent node sees the areas beneath it."""
		doc = self.make_field_user()
		self.assertEqual(self.permissions_for(doc.user)[0].hide_descendants, 0)

	def test_moving_territory_rewrites_the_permission(self):
		"""A stale permission is a rep still reading a district they left months ago."""
		doc = self.make_field_user()
		old_territory = doc.territory
		new_territory = self.make_territory()

		doc.territory = new_territory
		doc.save(ignore_permissions=True)

		perms = self.permissions_for(doc.user)
		self.assertEqual(len(perms), 1, "old permission was left behind")
		self.assertEqual(perms[0].for_value, new_territory)
		self.assertNotEqual(perms[0].for_value, old_territory)

	def test_going_inactive_removes_access_but_keeps_the_record(self):
		doc = self.make_field_user()
		doc.status = "Inactive"
		doc.save(ignore_permissions=True)
		self.assertEqual(self.permissions_for(doc.user), [])
		self.assertTrue(frappe.db.exists("FieldMate Field User", doc.name))

	def test_reactivating_restores_access(self):
		doc = self.make_field_user()
		doc.status = "Inactive"
		doc.save(ignore_permissions=True)
		doc.status = "Active"
		doc.save(ignore_permissions=True)
		self.assertEqual(len(self.permissions_for(doc.user)), 1)

	def test_deleting_the_field_user_removes_access(self):
		doc = self.make_field_user()
		user = doc.user
		frappe.delete_doc("FieldMate Field User", doc.name, force=True, ignore_permissions=True)
		self.assertEqual(self.permissions_for(user), [])

	def test_saving_twice_does_not_stack_permissions(self):
		doc = self.make_field_user()
		doc.save(ignore_permissions=True)
		doc.save(ignore_permissions=True)
		self.assertEqual(len(self.permissions_for(doc.user)), 1)


class TestFieldUserService(FieldUserFixture):
	def test_lookup_by_login(self):
		doc = self.make_field_user()
		self.assertEqual(svc.for_user(doc.user), doc.name)
		self.assertEqual(svc.territory_of(doc.user), doc.territory)

	def test_unknown_login_resolves_to_nothing(self):
		self.assertIsNone(svc.for_user("nobody@fieldmate.test"))
		self.assertEqual(svc.profile("nobody@fieldmate.test"), {})

	def test_profile_is_json_safe_and_leaks_no_document(self):
		import json
		doc = self.make_field_user()
		payload = svc.profile(doc.user)
		json.dumps(payload, default=str)
		self.assertEqual(payload["field_user"], doc.name)
		self.assertNotIn("doctype", payload)
		self.assertNotIn("owner", payload)
	def test_touch_records_activity_without_a_full_save(self):
		doc = self.make_field_user()
		before = frappe.db.get_value("FieldMate Field User", doc.name, "modified")
		svc.touch(doc.user)
		after = frappe.db.get_value("FieldMate Field User", doc.name, "last_active_on")
		self.assertIsNotNone(after)
		self.assertEqual(
			before, frappe.db.get_value("FieldMate Field User", doc.name, "modified")
		)
