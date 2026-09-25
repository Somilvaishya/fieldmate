"""Gate 2 criterion 2: Day Start mirrors into HRMS attendance with the right coordinates.

These skip cleanly when HRMS is absent, because FieldMate must run on a bench with no HR module
and a missing mirror is not a reason to refuse a rep their day. When HRMS is present they are the
evidence that the compat layer actually writes what it claims to.
"""

import frappe
from frappe.utils import add_days, today

from fieldmate import compat
from fieldmate.services import day as day_service
from fieldmate.tests.test_day import DELHI, DayFixture

MODEL_TOWN = (28.7041, 77.1025)


class TestHrmsAttendanceMirror(DayFixture):
	def setUp(self):
		super().setUp()
		if not compat.is_installed("hrms"):
			self.skipTest("hrms not installed on this site")

		self._started_at = frappe.utils.now_datetime()
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no company on this site")

		self.employee = self.make_employee()
		self.rep.employee = self.employee
		self.rep.flags.ignore_permissions = True
		self.rep.save()
		frappe.db.commit()

	def make_employee(self):
		doc = frappe.get_doc({
			"doctype": "Employee",
			"first_name": "Mirror",
			"last_name": self.uid("Test"),
			"company": self.company,
			"gender": frappe.db.get_value("Gender", {}, "name") or "Male",
			"date_of_birth": add_days(today(), -365 * 30),
			"date_of_joining": add_days(today(), -365),
			"status": "Active",
		}).insert(ignore_permissions=True)
		self.track("Employee", doc.name)
		return doc.name

	def checkins(self):
		"""Only the checkins this test made.

		Filtering on the employee alone is not enough. tearDown deletes the Employee, and
		Frappe's naming series then hands the same id back to the next test - so every test
		in this class is really looking at `HR-EMP-00001`, and a row left behind by an
		interrupted run counts as one of this test's own. The window matches what tearDown
		cleans, so the test says the same thing on a dirty site as on a fresh one.
		"""
		return frappe.get_all(
			"Employee Checkin",
			filters={"employee": self.employee, "creation": [">=", self._started_at]},
			fields=["name", "log_type", "latitude", "longitude", "time"],
			order_by="creation asc",
		)

	def tearDown(self):
		# Everything created during the test, not only rows for this employee: a test that
		# deliberately breaks the link would otherwise leave orphans on a shared site.
		for name in frappe.get_all(
			"Employee Checkin",
			filters={"creation": [">", self._started_at]},
			pluck="name",
		):
			try:
				frappe.delete_doc("Employee Checkin", name, force=True, ignore_permissions=True)
			except Exception:
				pass
		super().tearDown()

	# ------------------------------------------------------------------ the criterion

	def test_capabilities_report_hrms_geo_support(self):
		caps = compat.capabilities()
		self.assertTrue(caps["has_hrms"])
		self.assertTrue(caps["checkin_has_geo"], "Employee Checkin has no lat/long columns")

	def test_day_start_creates_an_in_checkin_with_coordinates(self):
		"""Gate 2, criterion 2."""
		result = self.start_day()
		rows = self.checkins()

		self.assertEqual(len(rows), 1, "expected exactly one checkin")
		checkin = rows[0]
		self.assertEqual(checkin.log_type, "IN")
		self.assertAlmostEqual(float(checkin.latitude), DELHI[0], places=4)
		self.assertAlmostEqual(float(checkin.longitude), DELHI[1], places=4)

		# and the day records which checkin it produced, so the link is traceable both ways
		self.assertEqual(
			frappe.db.get_value("FieldMate Day Start", result["day_start"], "employee_checkin"),
			checkin.name,
		)

	def test_day_end_creates_an_out_checkin(self):
		self.start_day()
		end = day_service.end(self.rep.name, {"latitude": MODEL_TOWN[0], "longitude": MODEL_TOWN[1]})

		rows = self.checkins()
		self.assertEqual([r.log_type for r in rows], ["IN", "OUT"])
		self.assertAlmostEqual(float(rows[1].latitude), MODEL_TOWN[0], places=4)
		self.assertEqual(
			frappe.db.get_value("FieldMate Day End", end["day_end"], "employee_checkin"),
			rows[1].name,
		)

	def test_a_rep_with_no_employee_still_gets_their_day(self):
		"""Not every field user is an HR employee. The mirror is a bonus, not a gate."""
		self.rep.employee = None
		self.rep.flags.ignore_permissions = True
		self.rep.save()
		frappe.db.commit()

		result = self.start_day()
		self.assertTrue(result["created"])
		self.assertEqual(self.checkins(), [])
		self.assertFalse(
			frappe.db.get_value("FieldMate Day Start", result["day_start"], "employee_checkin")
		)

	def test_a_broken_hr_link_degrades_to_silence_not_garbage(self):
		"""A stale employee link must neither block the rep nor invent an attendance row.

		An Employee Checkin pointing at an employee that does not exist reads as a real
		attendance record in HR reporting that nobody can trace back to a person.
		"""
		self.rep.db_set("employee", "EMP-DOES-NOT-EXIST", update_modified=False)
		frappe.db.commit()

		result = self.start_day()
		self.assertTrue(result["created"], "a broken HR link must not stop a rep working")

		orphans = frappe.get_all(
			"Employee Checkin", filters={"employee": "EMP-DOES-NOT-EXIST"}, pluck="name"
		)
		self.assertEqual(orphans, [], "mirror created an untraceable attendance row")
		self.assertFalse(
			frappe.db.get_value("FieldMate Day Start", result["day_start"], "employee_checkin")
		)
