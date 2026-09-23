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

	Without Day Start in the registry, an offline start kept nothing: the call failed, the
	selfie and fix were discarded, and every check-in afterwards was refused because the
	server had no open day. The visit's `day_start` link resolves through `depends_on`, so
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
			"latitude": DELHI[0], "longitude": DELHI[1], "accuracy_m": 9,
			"selfie": PIXEL,
			"created_offline": 1,
		}
		data.update(overrides)
		return {"doctype": "FieldMate Day Start", "client_uuid": client_uuid, "data": data}

	def test_day_start_is_pushable(self):
		self.assertTrue(registry.is_pushable("FieldMate Day Start"))
		self.assertTrue(registry.is_pushable("FieldMate Day End"))

	def test_an_offline_day_lands_open_and_submitted(self):
		uuid = self.uid("DAY")
		result = self.push([self.day_record(uuid)])["results"][0]
		self.assertEqual(result["status"], "created")
		self.track("FieldMate Day Start", result["name"])

		doc = frappe.get_doc("FieldMate Day Start", result["name"])
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.status, "Open")
		self.assertEqual(day_service.current(self.rep.name)["day_start"], doc.name)

	def test_the_selfie_is_stored_as_a_file_not_a_blob(self):
		"""Same varchar(140) trap as every other Attach Image on this project."""
		result = self.push([self.day_record(self.uid("DAY"))])["results"][0]
		self.track("FieldMate Day Start", result["name"])
		selfie = frappe.db.get_value("FieldMate Day Start", result["name"], "selfie")
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
					"day_start": day_uuid,          # the client id, not a server name
					"check_in_time": add_to_date(now_datetime(), minutes=-40),
					"check_in_latitude": DELHI[0], "check_in_longitude": DELHI[1],
					"check_out_time": now_datetime(),
					"visit_outcome": "Order Taken",
					"created_offline": 1,
				},
			},
		])

		day, visit = pushed["results"][0], pushed["results"][1]
		self.track("FieldMate Day Start", day["name"])
		self.track("FieldMate Visit", visit["name"])

		self.assertEqual(visit["status"], "created")
		self.assertEqual(
			frappe.db.get_value("FieldMate Visit", visit["name"], "day_start"), day["name"],
			"the visit must point at the real Day Start, not the client id",
		)

	def test_a_visit_whose_day_has_not_arrived_is_held_not_lost(self):
		pushed = self.push([{
			"doctype": "FieldMate Visit",
			"client_uuid": self.uid("VIS"),
			"data": {
				"docstatus": 1,
				"outlet": self.outlet.name, "field_user": self.rep.name,
				"visit_date": today(), "day_start": self.uid("NOTHERE"),
				"check_in_time": now_datetime(), "visit_outcome": "Order Taken",
			},
		}])["results"][0]
		self.assertEqual(pushed["status"], "held")
		self.assertEqual(pushed["code"], "MISSING_PARENT")

	def test_an_offline_day_end_counts_what_the_records_say(self):
		"""The phone has been offline all day; it cannot know what finally synced."""
		day = self.push([self.day_record(self.uid("DAY"))])["results"][0]
		self.track("FieldMate Day Start", day["name"])

		end = self.push([{
			"doctype": "FieldMate Day End",
			"client_uuid": self.uid("END"),
			"data": {
				"docstatus": 1,
				"day_start": day["name"],
				"end_time": now_datetime(),
				# The device claims a day it did not have.
				"actual_visits": 99, "order_value": 500000,
				"created_offline": 1,
			},
		}])["results"][0]
		self.track("FieldMate Day End", end["name"])

		doc = frappe.get_doc("FieldMate Day End", end["name"])
		self.assertEqual(doc.actual_visits, 0, "counted from the records, not the phone")
		self.assertEqual(doc.order_value, 0)
		self.assertEqual(doc.field_user, self.rep.name)
		self.assertGreater(doc.duration_hours, 0)


class TestCoverageCountsTheRoute(DayFixture):
	def test_coverage_counts_only_shops_on_the_route(self):
		"""An off-beat visit is real work, but it is not coverage of the planned route."""
		counts = day_service.day_counts(self.rep.name, today())
		self.assertIn("planned_covered", counts)
		self.assertEqual(counts["planned_covered"], 0)
