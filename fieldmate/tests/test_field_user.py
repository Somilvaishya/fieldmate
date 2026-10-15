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


class TestFillingFromTheMasters(FieldUserFixture):
	"""What an admin should not have to type twice.

	The request was "autofill fields from the master doctypes". The part that decides whether
	that is a help or a nuisance is the overwrite: a plain `fetch_from` refills on **every**
	save, which was checked against a real save rather than assumed. So a number an admin
	deliberately typed, because the rep's work phone is not the one on their login, would be
	replaced the next time anybody opened the record and saved it. Only blanks are filled.
	"""

	def a_login_with(self, **values):
		"""A FieldMate login carrying some contact details."""
		email = self.make_user()
		doc = frappe.get_doc("User", email)
		for key, value in values.items():
			doc.set(key, value)
		doc.save(ignore_permissions=True)
		return email

	def an_employee(self, **values):
		data = {
			"doctype": "Employee",
			"first_name": "Mastered",
			"last_name": "Rep",
			"gender": frappe.db.get_value("Gender", {}, "name"),
			"date_of_birth": "1990-01-01",
			"date_of_joining": "2021-04-01",
			"status": "Active",
			"company": frappe.db.get_value("Company", {}, "name"),
		}
		data.update(values)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("Employee", doc.name)
		return doc

	# ------------------------------------------------------------------ the mobile number

	def test_the_mobile_number_comes_off_the_login(self):
		login = self.a_login_with(mobile_no="9811111111")
		rep = self.make_field_user(user=login)
		self.assertEqual(rep.mobile_no, "9811111111")

	def test_the_employee_answers_when_the_login_has_no_number(self):
		"""A FieldMate login is often created just to sign in and carries no phone at all,
		while the HR record almost always has one."""
		employee = self.an_employee(cell_number="9822222222")
		rep = self.make_field_user(user=self.a_login_with(), employee=employee.name)
		self.assertEqual(rep.mobile_no, "9822222222")

	def test_a_typed_number_is_never_overwritten(self):
		"""The one that decides whether this feature helps. A rep's work phone is not always
		the number on their login, and the admin who corrected it must keep their correction
		through every later save - not only the first."""
		login = self.a_login_with(mobile_no="9811111111")
		rep = self.make_field_user(user=login, mobile_no="9899999999")
		self.assertEqual(rep.mobile_no, "9899999999")

		rep.notes = "edited for some unrelated reason"
		rep.save(ignore_permissions=True)
		self.assertEqual(rep.mobile_no, "9899999999")

	def test_no_number_anywhere_stays_empty_rather_than_guessing(self):
		rep = self.make_field_user(user=self.a_login_with())
		self.assertFalse(rep.mobile_no)

	# ------------------------------------------------------- company and the joining date

	def test_the_joining_date_comes_off_the_employee(self):
		employee = self.an_employee(date_of_joining="2019-07-15")
		rep = self.make_field_user(user=self.a_login_with(), employee=employee.name)
		self.assertEqual(str(rep.joining_date), "2019-07-15")

	def test_a_joining_date_set_by_hand_survives_later_saves(self):
		employee = self.an_employee(date_of_joining="2019-07-15")
		rep = self.make_field_user(
			user=self.a_login_with(), employee=employee.name, joining_date="2022-01-10")
		self.assertEqual(str(rep.joining_date), "2022-01-10")

		rep.notes = "saved again"
		rep.save(ignore_permissions=True)
		self.assertEqual(str(rep.joining_date), "2022-01-10")

	def test_no_employee_leaves_the_joining_date_alone(self):
		rep = self.make_field_user(user=self.a_login_with())
		self.assertFalse(rep.joining_date)

	def a_second_company(self):
		"""A company that is not the site's default, so the two answers can be told apart.

		Expensive - about five seconds, because ERPNext builds a chart of accounts, cost centres
		and warehouses behind it - and it **commits**, so the per-class rollback will not take it
		away. Hence created once, on demand, and deleted by hand.
		"""
		if getattr(self, "_second_company", None):
			return self._second_company

		doc = frappe.get_doc({
			"doctype": "Company",
			"company_name": f"FM Other {frappe.generate_hash(length=5)}",
			"abbr": f"FM{frappe.generate_hash(length=3).upper()}",
			"default_currency": frappe.db.get_value(
				"Company", frappe.db.get_default("company"), "default_currency") or "INR",
			"country": frappe.db.get_value(
				"Company", frappe.db.get_default("company"), "country") or "India",
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		self._second_company = doc.name
		self.addCleanup(self._drop_company, doc.name)
		return doc.name

	def _drop_company(self, name):
		frappe.db.rollback()
		try:
			frappe.delete_doc("Company", name, force=True, ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			# Leaving one behind is untidy but not a failing test; the next run makes its own.
			frappe.db.rollback()
		self._second_company = None

	def test_the_company_comes_off_the_employee(self):
		"""The company HR employs them under, not the one whoever opened the form sits in."""
		other = self.a_second_company()
		self.assertNotEqual(other, frappe.db.get_default("company"))

		employee = self.an_employee(company=other)
		rep = self.make_field_user(user=self.a_login_with(), employee=employee.name)
		self.assertEqual(rep.company, other)

	def test_the_employee_wins_over_a_company_set_by_hand(self):
		"""Asked for explicitly: HR owns this, so it overwrites - every save, not only the first.

		The cost is on the field's own description: while an Employee is linked, a company chosen
		here does not survive. There is no way to tell a deliberate choice from the value Frappe
		puts in from the session default during insert.
		"""
		other = self.a_second_company()
		employee = self.an_employee(company=other)

		rep = self.make_field_user(
			user=self.a_login_with(), employee=employee.name,
			company=frappe.db.get_default("company"))
		self.assertEqual(rep.company, other)

		rep.company = frappe.db.get_default("company")
		rep.save(ignore_permissions=True)
		self.assertEqual(rep.company, other)

	def test_no_employee_falls_back_to_the_default_company(self):
		rep = self.make_field_user(user=self.a_login_with())
		self.assertEqual(rep.company, frappe.db.get_default("company"))

	def test_an_employee_with_no_company_does_not_blank_it(self):
		"""An Employee is not allowed to have no company, but a stale link or a half-imported
		record can read as one, and a rep landing in no company at all would drop out of every
		report that scopes by it."""
		rep = self.make_field_user(user=self.a_login_with(), employee=None)
		before = rep.company
		rep.employee = None
		rep.save(ignore_permissions=True)
		self.assertEqual(rep.company, before)

	def test_the_patch_corrects_reps_created_before_the_rule(self):
		"""A rep made last year sits on whatever the session default was at the time.

		The controller only reaches a record when somebody saves it, so without the patch a rep
		on a multi-company site stays filed against the wrong company until a human opens their
		form. Written straight to the column here, which is exactly the state the patch is for.
		"""
		from fieldmate.patches.company_from_the_employee import execute

		other = self.a_second_company()
		employee = self.an_employee(company=other)
		rep = self.make_field_user(user=self.a_login_with(), employee=employee.name)

		# Back to how the record would have looked before the rule existed.
		frappe.db.set_value("FieldMate Field User", rep.name, "company",
		                    frappe.db.get_default("company"), update_modified=False)
		self.assertEqual(
			frappe.db.get_value("FieldMate Field User", rep.name, "company"),
			frappe.db.get_default("company"))

		execute()

		self.assertEqual(
			frappe.db.get_value("FieldMate Field User", rep.name, "company"), other)

	def test_the_patch_leaves_a_rep_with_no_employee_alone(self):
		"""Nothing to take the answer from, and guessing beats nothing only in the wrong way."""
		from fieldmate.patches.company_from_the_employee import execute

		rep = self.make_field_user(user=self.a_login_with())
		before = frappe.db.get_value("FieldMate Field User", rep.name, "company")
		execute()
		self.assertEqual(
			frappe.db.get_value("FieldMate Field User", rep.name, "company"), before)
