"""Everything a rep does, done AS THE REP.

Every gate so far ran as Administrator, and Administrator can do anything. That hid a defect
that made the app unusable for its only real user: a FieldMate Field Rep holds `create` and
`read` on their own records and neither `write` nor `submit`, so every `doc.submit()` in the
services and in the sync push failed with a permission error. A rep could not start a day,
could not finish a visit, could not end a day.

The permission model itself is correct and deliberate (ADR-004): a rep never holds write on
a submittable record, which is what keeps generic endpoints like frappe.client.save closed to
them. The server checks who is asking and then acts on their behalf. These tests exist so
that the "acts on their behalf" half is never quietly lost again.
"""

import frappe
from frappe.utils import add_to_date, now_datetime, today

from fieldmate.services import day as day_service
from fieldmate.services import sync as sync_service
from fieldmate.services import visit as visit_service
from fieldmate.tests.test_day import DELHI, DayFixture

PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class AsTheRep(DayFixture):
	def setUp(self):
		super().setUp()
		self.outlet = self.make_outlet(
			territory=self.territory, approval_status="Approved",
			latitude=DELHI[0], longitude=DELHI[1],
		)
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def as_rep(self, fn, *args, **kwargs):
		frappe.set_user(self.rep.user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")


class TestARepCanWorkTheirDay(AsTheRep):
	def test_a_rep_holds_no_submit_right_of_their_own(self):
		"""The premise. If this ever changes, the tests below stop proving anything."""
		frappe.set_user(self.rep.user)
		try:
			self.assertTrue(frappe.has_permission("FieldMate Visit", "create"))
			self.assertFalse(frappe.has_permission("FieldMate Visit", "write"))
			self.assertFalse(frappe.has_permission("FieldMate Visit", "submit"))
		finally:
			frappe.set_user("Administrator")

	def test_a_rep_can_start_their_day(self):
		result = self.as_rep(day_service.start, self.rep.name, {
			"latitude": DELHI[0], "longitude": DELHI[1], "accuracy_m": 8,
			"selfie": PIXEL, "device_id": self.device.name,
		})
		self.assertTrue(result["created"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Day", result["day"], "docstatus"), 1,
			"the day must be submitted, not left a draft",
		)

	def test_a_rep_can_finish_a_visit(self):
		self.as_rep(day_service.start, self.rep.name, {
			"latitude": DELHI[0], "longitude": DELHI[1],
			"selfie": PIXEL, "device_id": self.device.name,
		})
		opened = self.as_rep(visit_service.check_in, self.rep.name, {
			"outlet": self.outlet.name, "latitude": DELHI[0], "longitude": DELHI[1],
			"client_uuid": self.uid("VIS"),
		})
		self.track("FieldMate Visit", opened["visit"])

		closed = self.as_rep(visit_service.check_out, opened["visit"],
		                     {"visit_outcome": "Order Taken"})
		self.assertTrue(closed["checked_out_at"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Visit", opened["visit"], "docstatus"), 1
		)

	def test_a_rep_can_end_their_day(self):
		self.as_rep(day_service.start, self.rep.name, {
			"latitude": DELHI[0], "longitude": DELHI[1],
			"selfie": PIXEL, "device_id": self.device.name,
		})
		result = self.as_rep(day_service.end, self.rep.name,
		                     {"latitude": DELHI[0], "longitude": DELHI[1]})
		self.assertTrue(result["created"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Day", result["day"], "status"), "Closed"
		)


class TestARepCanSyncTheirOfflineDay(AsTheRep):
	"""The payload the app actually sends, pushed by the rep who captured it."""

	def push(self, records):
		return self.as_rep(sync_service.push, self.rep.user, self.device,
		                   self.uid("BATCH"), records)

	def test_the_payload_the_app_sends_is_accepted(self):
		"""The client never sends field_user - the phone has no reason to know that id.

		It was rejected as a missing mandatory field until the server started filling it
		from the session, which is the same fix pattern as the outlet's distributor.
		"""
		day_uuid = self.uid("DAY")
		result = self.push([{
			"doctype": "FieldMate Day",
			"client_uuid": day_uuid,
			"data": {
				"docstatus": 1,
				"day_date": today(),
				"start_time": add_to_date(now_datetime(), hours=-4),
				"status": "Open",
				"start_latitude": DELHI[0], "start_longitude": DELHI[1],
				"selfie": PIXEL,
				"created_offline": 1,
			},
		}])["results"][0]

		self.assertEqual(result["status"], "created",
		                 f"rejected: {result.get('code')} {result.get('message')}")
		self.track("FieldMate Day", result["name"])

		doc = frappe.get_doc("FieldMate Day", result["name"])
		self.assertEqual(doc.docstatus, 1, "submit_on_push must work for a real rep")
		self.assertEqual(doc.field_user, self.rep.name, "filled from the session")

	def test_a_device_cannot_push_work_onto_a_colleague(self):
		"""field_user comes from the session, so naming someone else changes nothing."""
		colleague = self.make_field_user(territory=self.territory)
		frappe.db.commit()

		result = self.push([{
			"doctype": "FieldMate Day",
			"client_uuid": self.uid("DAY"),
			"data": {
				"docstatus": 1,
				"field_user": colleague.name,        # the device asking nicely
				"day_date": today(),
				"start_time": now_datetime(),
				"status": "Open",
				"start_latitude": DELHI[0], "start_longitude": DELHI[1],
			},
		}])["results"][0]
		self.track("FieldMate Day", result.get("name"))

		self.assertEqual(result["status"], "created")
		self.assertEqual(
			frappe.db.get_value("FieldMate Day", result["name"], "field_user"),
			self.rep.name,
		)

	def test_an_offline_day_end_closes_its_day(self):
		"""Without this the day stays Open and reports as one the rep forgot to finish."""
		day = self.push([{
			"doctype": "FieldMate Day",
			"client_uuid": self.uid("DAY"),
			"data": {
				"docstatus": 1, "day_date": today(),
				"start_time": add_to_date(now_datetime(), hours=-5),
				"status": "Open", "start_latitude": DELHI[0], "start_longitude": DELHI[1],
			},
		}])["results"][0]
		self.track("FieldMate Day", day["name"])

		end = self.push([{
			"doctype": "FieldMate Day",
			"client_uuid": self.uid("END"),
			"data": {
				"closes": day["name"], "end_time": now_datetime(),
				"end_latitude": DELHI[0], "end_longitude": DELHI[1],
			},
		}])["results"][0]
		self.assertEqual(end["status"], "updated",
		                 f"rejected: {end.get('code')} {end.get('message')}")

		self.assertEqual(
			frappe.db.get_value("FieldMate Day", day["name"], "status"), "Closed"
		)
		self.assertIsNone(day_service.current(self.rep.name),
		                  "a closed day must not still read as open")

	def test_a_whole_offline_day_lands_in_one_batch(self):
		day_uuid = self.uid("DAY")
		pushed = self.push([
			{
				"doctype": "FieldMate Day",
				"client_uuid": day_uuid,
				"data": {
					"docstatus": 1, "day_date": today(),
					"start_time": add_to_date(now_datetime(), hours=-6),
					"status": "Open", "start_latitude": DELHI[0],
					"start_longitude": DELHI[1],
					"created_offline": 1,
				},
			},
			{
				"doctype": "FieldMate Visit",
				"client_uuid": self.uid("VIS"),
				"data": {
					"docstatus": 1,
					"outlet": self.outlet.name,
					"visit_date": today(),
					"day": day_uuid,
					"check_in_time": add_to_date(now_datetime(), minutes=-50),
					"check_in_latitude": DELHI[0], "check_in_longitude": DELHI[1],
					"check_out_time": add_to_date(now_datetime(), minutes=-20),
					"visit_outcome": "Order Taken",
					"created_offline": 1,
				},
			},
		])["results"]

		day, visit = pushed[0], pushed[1]
		self.track("FieldMate Day", day.get("name"))
		self.track("FieldMate Visit", visit.get("name"))

		self.assertEqual(day["status"], "created",
		                 f"day rejected: {day.get('code')} {day.get('message')}")
		self.assertEqual(visit["status"], "created",
		                 f"visit rejected: {visit.get('code')} {visit.get('message')}")
		self.assertEqual(
			frappe.db.get_value("FieldMate Visit", visit["name"], "day"), day["name"]
		)
		self.assertEqual(
			frappe.db.get_value("FieldMate Visit", visit["name"], "field_user"), self.rep.name
		)
