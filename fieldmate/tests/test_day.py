import frappe
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime, today

from fieldmate.services import day as day_service
from fieldmate.services import trail as trail_service
from fieldmate.tests.test_journey import JourneyFixture

DELHI = (28.6139, 77.2090)


class DayFixture(JourneyFixture):
	def setUp(self):
		super().setUp()
		self.territory = self.make_territory()
		self.rep = self.make_field_user(territory=self.territory)
		self.device = frappe.get_doc({
			"doctype": "FieldMate Device Registry",
			"device_uuid": self.uid("DEV"),
			"user": self.rep.user,
			"platform": "Android",
		}).insert(ignore_permissions=True)
		self.track("FieldMate Device Registry", self.device.name)

	def tearDown(self):
		for dt in ("FieldMate Day", "FieldMate Attendance Summary",
		           "FieldMate Location Trail"):
			for name in frappe.get_all(dt, filters={"field_user": self.rep.name}, pluck="name"):
				try:
					doc = frappe.get_doc(dt, name)
					if doc.meta.is_submittable and doc.docstatus == 1:
						doc.flags.ignore_permissions = True
						doc.cancel()
					frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
				except Exception:
					pass
		frappe.db.commit()
		super().tearDown()

	def start_day(self, **kwargs):
		payload = {"latitude": DELHI[0], "longitude": DELHI[1], "accuracy_m": 8,
		           "selfie": "/files/test.jpg", "device_id": self.device.name}
		payload.update(kwargs)
		return day_service.start(self.rep.name, payload)


class TestDayStart(DayFixture):
	def test_starting_opens_a_day(self):
		result = self.start_day()
		self.assertTrue(result["created"])
		self.assertEqual(result["day_date"], today())
		self.assertTrue(result["day"].startswith("FM-DAY-"))

	def test_starting_twice_returns_the_same_day(self):
		"""A rep tapping start again, or a retried offline push, must not open a second day."""
		first = self.start_day()
		second = self.start_day()
		self.assertFalse(second["created"])
		self.assertEqual(first["day"], second["day"])

	def test_current_resumes_after_an_app_restart(self):
		started = self.start_day()
		self.assertEqual(day_service.current(self.rep.name)["day"], started["day"])

	def test_no_open_day_reads_as_none(self):
		self.assertIsNone(day_service.current(self.rep.name))

	def test_selfie_is_required_when_settings_say_so(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.start_day(selfie=None)
		self.assertIn("start-of-day photo", str(ctx.exception))

	def test_mock_location_is_recorded_not_blocked(self):
		"""Blocking pushes a rep to stop using the app rather than to stop faking."""
		result = self.start_day(is_mock_location=1)
		self.assertTrue(result["created"])
		self.assertTrue(frappe.db.get_value("FieldMate Day", result["day"],
		                                    "is_mock_location"))

	def test_impossible_coordinates_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.start_day(latitude=200)

	def test_a_second_open_day_is_refused_at_the_doctype(self):
		self.start_day()
		doc = frappe.get_doc({
			"doctype": "FieldMate Day",
			"field_user": self.rep.name,
			"day_date": today(),
			"start_time": now_datetime(),
			"status": "Open",
		})
		doc.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError) as ctx:
			doc.submit()
		self.assertIn("already has a day open", str(ctx.exception))
		frappe.delete_doc("FieldMate Day", doc.name, force=True, ignore_permissions=True)

	def test_picks_up_the_planned_beat(self):
		shops = [self.make_outlet(territory=self.territory).name for _ in range(3)]
		beat = self.make_beat(territory=self.territory, assigned_to=self.rep.name,
		                      outlets=shops, visit_day=self.weekday_today())
		from fieldmate.services import journey as journey_service
		plan_name = journey_service.generate(self.rep.name, today(), today())
		self.track("FieldMate Journey Plan", plan_name)
		frappe.get_doc("FieldMate Journey Plan", plan_name).submit()

		result = self.start_day()
		self.assertEqual(result["planned_beat"], beat.name)

	def weekday_today(self):
		from fieldmate.services.journey import WEEKDAYS
		return WEEKDAYS[frappe.utils.getdate(today()).weekday()]


class TestDayEnd(DayFixture):
	def test_ending_closes_the_day(self):
		started = self.start_day()
		result = day_service.end(self.rep.name, {"latitude": DELHI[0], "longitude": DELHI[1]})
		self.assertTrue(result["created"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Day", started["day"], "status"), "Closed"
		)

	def test_ending_without_a_day_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			day_service.end(self.rep.name, {})
		self.assertIn("No day is open", str(ctx.exception))

	def test_a_finished_day_cannot_be_restarted(self):
		"""Otherwise one day's work splits across two records and coverage double-counts."""
		self.start_day()
		day_service.end(self.rep.name, {})
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.start_day()
		self.assertIn("already finished today", str(ctx.exception))

	def test_distance_comes_from_the_trail_not_the_payload(self):
		"""Expense claims read this figure, so it is computed, not typed."""
		self.start_day()
		trail_service.append(self.rep.name, [
			{"t": "2026-09-22 09:00:00", "lat": 28.6139, "lon": 77.2090},
			{"t": "2026-09-22 09:30:00", "lat": 28.7041, "lon": 77.1025},
		])
		result = day_service.end(self.rep.name, {"odometer_end": 99999})
		self.assertGreater(result["distance_km"], 5)
		self.assertLess(result["distance_km"], 30)

	def test_attendance_summary_is_written(self):
		self.start_day()
		day_service.end(self.rep.name, {})
		summary = frappe.db.get_value(
			"FieldMate Attendance Summary",
			{"field_user": self.rep.name, "summary_date": today()},
			["status", "working_hours"], as_dict=True,
		)
		self.assertIsNotNone(summary)
		self.assertEqual(summary.status, "Present")


class TestAutoClose(DayFixture):
	def test_a_forgotten_day_is_auto_closed(self):
		started = self.start_day()
		frappe.db.set_value("FieldMate Day", started["day"], "start_time",
		                    add_to_date(now_datetime(), hours=-40), update_modified=False)

		closed = day_service.auto_close_stale_days()
		self.assertGreaterEqual(closed, 1)
		self.assertEqual(
			frappe.db.get_value("FieldMate Day", started["day"], "status"),
			"Auto Closed",
		)

	def test_a_fresh_day_is_left_alone(self):
		started = self.start_day()
		day_service.auto_close_stale_days()
		self.assertEqual(
			frappe.db.get_value("FieldMate Day", started["day"], "status"), "Open"
		)


class TestHrmsMirror(DayFixture):
	def test_absent_hrms_is_not_an_error(self):
		"""FieldMate must run on a bench with no HR module."""
		from fieldmate import compat
		if compat.is_installed("hrms"):
			self.skipTest("hrms installed; the absent path is what this covers")
		result = self.start_day()
		self.assertTrue(result["created"])
		self.assertFalse(
			frappe.db.get_value("FieldMate Day", result["day"], "start_checkin")
		)


class TestADayBelongsToItsDate(DayFixture):
	"""A day started yesterday and never ended was still being handed back as today's day.

	`start` is idempotent on `current`, so the rep got yesterday back with `created: False`, and
	`visit.check_in` takes `visit_date` from that answer - so today's visits, orders and
	collections all landed on yesterday's record and yesterday's date. Coverage, attendance and
	the day counts were wrong from the first check-in and nothing on the screen said so.

	`close_stale_days` is scheduled for this and could not be the guarantee: it waits out
	`auto_close_day_after_hours`, so an evening start is still Open the next morning - and on a
	site whose scheduler is not running it never fires at all, which is how this was found.
	"""

	def stale_day(self) -> str:
		"""A day opened yesterday and never ended."""
		started = self.start_day()
		frappe.db.set_value("FieldMate Day", started["day"], {
			"day_date": add_days(today(), -1),
			"start_time": add_to_date(now_datetime(), days=-1),
		}, update_modified=False)
		frappe.clear_document_cache("FieldMate Day", started["day"])
		return started["day"]

	def test_yesterdays_day_is_not_todays_day(self):
		self.stale_day()
		self.assertIsNone(day_service.current(self.rep.name))

	def test_it_is_closed_rather_than_left_open_to_be_found_again(self):
		name = self.stale_day()
		day_service.current(self.rep.name)
		self.assertEqual(
			frappe.db.get_value("FieldMate Day", name, "status"), "Auto Closed",
			"Auto Closed, not Closed: a forgotten day is not a finished one")

	def test_it_gets_the_closing_a_real_day_end_gets(self):
		"""The old auto-close flipped a status and stopped. No closing meant no counts, no
		distance, no attendance and no OUT in HRMS - the record of a forgotten day was a day
		that produced nothing, which is not what happened."""
		name = self.stale_day()
		day_service.current(self.rep.name)
		row = frappe.db.get_value("FieldMate Day", name,
		                          ["status", "end_time"], as_dict=True)
		self.assertEqual(row.status, "Auto Closed")
		self.assertIsNotNone(row.end_time, "a forgotten day still records when it ended")
		self.assertTrue(
			frappe.db.exists("FieldMate Attendance Summary", {"day": name}),
			"and the attendance row a real closing writes",
		)

	def test_it_is_not_closed_at_whatever_time_it_is_found(self):
		"""Closing at `now` would book a twenty-hour day and an attendance row to match. Nobody
		knows when the rep stopped, so the last thing the day recorded stands in for it."""
		name = self.stale_day()
		day_service.current(self.rep.name)
		started_at, ended_at = frappe.db.get_value(
			"FieldMate Day", name, ["start_time", "end_time"])
		self.assertEqual(get_datetime(ended_at), get_datetime(started_at),
		                 "a day that recorded nothing ends when it began")

	def test_starting_today_opens_a_new_day_rather_than_returning_yesterdays(self):
		stale = self.stale_day()
		fresh = self.start_day()
		self.assertTrue(fresh["created"], "yesterday is not today, whatever its status says")
		self.assertNotEqual(fresh["day"], stale)
		self.assertEqual(str(fresh["day_date"]), str(today()))

	def test_a_day_opened_today_is_still_the_open_day(self):
		"""The guard is on the date, not on how long ago the day started. A rep who kills the
		app mid-morning must come back to the same day."""
		started = self.start_day()
		self.assertEqual(day_service.current(self.rep.name)["day"], started["day"])

	def test_ending_a_day_that_was_already_auto_closed_says_so(self):
		"""Rather than closing it twice or reporting a success over a day that is already over."""
		self.stale_day()
		with self.assertRaises(frappe.ValidationError):
			day_service.end(self.rep.name, {})
