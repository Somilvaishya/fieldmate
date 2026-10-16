import frappe
from frappe.utils import add_to_date, now_datetime, today

from fieldmate.services import day as day_service
from fieldmate.services import registry
from fieldmate.services import sync as sync_service
from fieldmate.tests.test_day import DELHI, DayFixture

PIXEL = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
         "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


class TestOfflineDay(DayFixture):
	"""A whole day captured with no signal has to land intact.

	Without the day in the registry, an offline start kept nothing: the call failed, the
	selfie and fix were discarded, and every check-in afterwards was refused because the
	server had no open day. The visit's `day` link resolves through `depends_on`, so
	the day and the visits that hang off it travel together.
	"""

	def setUp(self):
		super().setUp()
		self.outlet = self.make_outlet(territory=self.territory, approval_status="Approved",
		                               latitude=DELHI[0], longitude=DELHI[1])

	def push(self, records):
		return sync_service.push("Administrator", self.device, self.uid("BATCH"), records)

	def day_record(self, client_uuid, **overrides):
		data = {
			"docstatus": 1,
			"field_user": self.rep.name,
			"day_date": today(),
			"start_time": add_to_date(now_datetime(), hours=-6),
			"status": "Open",
			"start_latitude": DELHI[0], "start_longitude": DELHI[1], "start_accuracy_m": 9,
			"selfie": PIXEL,
			"created_offline": 1,
		}
		data.update(overrides)
		return {"doctype": "FieldMate Day", "client_uuid": client_uuid, "data": data}

	def test_the_day_is_pushable(self):
		self.assertTrue(registry.is_pushable("FieldMate Day"))

	def test_an_offline_day_lands_open_and_submitted(self):
		uuid = self.uid("DAY")
		result = self.push([self.day_record(uuid)])["results"][0]
		self.assertEqual(result["status"], "created")
		self.track("FieldMate Day", result["name"])

		doc = frappe.get_doc("FieldMate Day", result["name"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.status, "Open")
		self.assertEqual(day_service.current(self.rep.name)["day"], doc.name)

	def test_the_selfie_is_stored_as_a_file_not_a_blob(self):
		"""Same varchar(140) trap as every other Attach Image on this project."""
		result = self.push([self.day_record(self.uid("DAY"))])["results"][0]
		self.track("FieldMate Day", result["name"])
		selfie = frappe.db.get_value("FieldMate Day", result["name"], "selfie")
		self.assertTrue(selfie.startswith(("/files/", "/private/files/")), selfie[:40])

	def test_a_visit_queued_against_the_queued_day_resolves_in_one_batch(self):
		"""The day and its visits arrive together, and the link is rebuilt server-side."""
		day_uuid = self.uid("DAY")
		visit_uuid = self.uid("VIS")

		pushed = self.push([
			self.day_record(day_uuid),
			{
				"doctype": "FieldMate Visit",
				"client_uuid": visit_uuid,
				"data": {
					"docstatus": 1,
					"outlet": self.outlet.name,
					"field_user": self.rep.name,
					"visit_date": today(),
					"day": day_uuid,          # the client id, not a server name
					"check_in_time": add_to_date(now_datetime(), minutes=-40),
					"check_in_latitude": DELHI[0], "check_in_longitude": DELHI[1],
					"check_out_time": now_datetime(),
					"visit_outcome": "Order Taken",
					"created_offline": 1,
				},
			},
		])

		day, visit = pushed["results"][0], pushed["results"][1]
		self.track("FieldMate Day", day["name"])
		self.track("FieldMate Visit", visit["name"])

		self.assertEqual(visit["status"], "created")
		self.assertEqual(
			frappe.db.get_value("FieldMate Visit", visit["name"], "day"), day["name"],
			"the visit must point at the real the day, not the client id",
		)

	def test_a_visit_whose_day_has_not_arrived_is_held_not_lost(self):
		pushed = self.push([{
			"doctype": "FieldMate Visit",
			"client_uuid": self.uid("VIS"),
			"data": {
				"docstatus": 1,
				"outlet": self.outlet.name, "field_user": self.rep.name,
				"visit_date": today(), "day": self.uid("NOTHERE"),
				"check_in_time": now_datetime(), "visit_outcome": "Order Taken",
			},
		}])["results"][0]
		self.assertEqual(pushed["status"], "held")
		self.assertEqual(pushed["code"], "MISSING_PARENT")

	def test_an_offline_close_updates_the_day_it_closes(self):
		"""The close is a second push of the same day, not a second document.

		`_apply` could only insert, so with one document it saw a record it already had and
		reported "duplicate" - the close was accepted and silently dropped, and the day stayed
		Open until the scheduler marked it a day the rep forgot to finish.
		"""
		day = self.push([self.day_record(self.uid("DAY"))])["results"][0]
		self.track("FieldMate Day", day["name"])

		end = self.push([{
			"doctype": "FieldMate Day",
			"client_uuid": self.uid("END"),
			"data": {
				"closes": day["name"],
				"end_time": now_datetime(),
				# The device claims a day it did not have. Neither field is in `update_fields`,
				# so neither reaches the record at all.
				"actual_visits": 99, "order_value": 500000,
			},
		}])["results"][0]
		self.assertEqual(end["status"], "updated",
		                 f"rejected: {end.get('code')} {end.get('message')}")
		self.assertEqual(end["name"], day["name"], "one day, not two")

		doc = frappe.get_doc("FieldMate Day", day["name"])
		self.assertEqual(doc.status, "Closed")
		self.assertEqual(doc.actual_visits, 0, "counted from the records, not the phone")
		self.assertEqual(doc.order_value, 0)
		self.assertEqual(doc.field_user, self.rep.name)
		self.assertGreater(doc.duration_hours, 0)

	def test_a_replayed_close_is_not_applied_twice(self):
		"""The outbox retries, so this is the ordinary case on a market connection."""
		day = self.push([self.day_record(self.uid("DAY"))])["results"][0]
		self.track("FieldMate Day", day["name"])

		close = {
			"doctype": "FieldMate Day",
			"client_uuid": self.uid("END"),
			"data": {"closes": day["name"], "end_time": now_datetime()},
		}
		self.push([close])
		again = sync_service.push("Administrator", self.device, self.uid("BATCH2"),
		                          [close])["results"][0]
		self.assertEqual(again["status"], "duplicate")
		self.assertEqual(again["name"], day["name"])

	def test_a_close_for_a_day_that_has_not_arrived_is_held_not_lost(self):
		held = self.push([{
			"doctype": "FieldMate Day",
			"client_uuid": self.uid("END"),
			"data": {"closes": self.uid("NOTHERE"), "end_time": now_datetime()},
		}])["results"][0]
		self.assertEqual(held["status"], "held")
		self.assertEqual(held["code"], "MISSING_PARENT")


class TestCoverageCountsTheRoute(DayFixture):
	def test_coverage_counts_only_shops_on_the_route(self):
		"""An off-beat visit is real work, but it is not coverage of the planned route."""
		counts = day_service.day_counts(self.rep.name, today())
		self.assertIn("planned_covered", counts)
		self.assertEqual(counts["planned_covered"], 0)
