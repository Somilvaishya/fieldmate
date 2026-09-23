import frappe
from frappe.utils import add_days, getdate, today

from fieldmate.services import day as day_service
from fieldmate.services import journey as journey_service
from fieldmate.tests.test_day import DELHI, DayFixture


class TestDaySummary(DayFixture):
	"""The Finish Day screen shows a rep what they are about to close.

	It reads the same figures `end()` writes, so the screen cannot show one number and the
	Day End record keep another.
	"""

	def setUp(self):
		super().setUp()
		self.shops = [self.make_outlet(territory=self.territory, approval_status="Approved")
		              for _ in range(3)]
		self.beat = self.make_beat(territory=self.territory, assigned_to=self.rep.name,
		                           outlets=[o.name for o in self.shops])

	def plan_today(self):
		plan = frappe.get_doc({
			"doctype": "FieldMate Journey Plan",
			"field_user": self.rep.name, "from_date": today(), "to_date": today(),
			"days": [{
				"plan_date": today(), "beat": self.beat.name, "status": "Planned",
				"is_working_day": 1, "outlet_count": 3,
				"day_of_week": getdate(today()).strftime("%A"),
			}],
		}).insert(ignore_permissions=True)
		self.track("FieldMate Journey Plan", plan.name)
		plan.submit()
		return plan

	def test_summary_does_not_close_the_day(self):
		"""Reading the summary must never be the thing that ends a rep's day."""
		started = self.start_day()
		day_service.summary(self.rep.name)
		self.assertEqual(
			frappe.db.get_value("FieldMate Day Start", started["day_start"], "status"), "Open"
		)
		self.assertTrue(day_service.current(self.rep.name))

	def test_it_reports_time_on_route(self):
		self.start_day()
		summary = day_service.summary(self.rep.name)
		self.assertTrue(summary["open"])
		self.assertIsNotNone(summary["minutes_on_route"])
		self.assertGreaterEqual(summary["minutes_on_route"], 0)

	def test_unvisited_shops_are_named_not_counted(self):
		"""'2 shops pending' tells a rep nothing they can act on in the last ten minutes."""
		self.plan_today()
		self.start_day()

		summary = day_service.summary(self.rep.name)
		pending = {s["outlet_name"] for s in summary["pending_shops"]}
		self.assertEqual(pending, {o.outlet_name for o in self.shops})
		self.assertEqual(summary["planned_visits"], 3)
		self.assertEqual(summary["actual_visits"], 0)

	def test_a_visited_shop_drops_off_the_pending_list(self):
		from fieldmate.services import visit as visit_service

		self.plan_today()
		self.start_day()
		opened = visit_service.check_in(self.rep.name, {
			"outlet": self.shops[0].name, "latitude": DELHI[0], "longitude": DELHI[1],
			"client_uuid": self.uid("VIS"),
		})
		self.track("FieldMate Visit", opened["visit"])
		visit_service.check_out(opened["visit"], {"visit_outcome": "Order Taken"})

		summary = day_service.summary(self.rep.name)
		names = {s["outlet_name"] for s in summary["pending_shops"]}
		self.assertNotIn(self.shops[0].outlet_name, names)
		self.assertEqual(len(summary["pending_shops"]), 2)
		self.assertEqual(summary["actual_visits"], 1)

	def test_no_beat_means_no_pending_list_rather_than_an_error(self):
		self.start_day()
		summary = day_service.summary(self.rep.name)
		self.assertEqual(summary["pending_shops"], [])

	def test_summary_works_before_the_day_is_started(self):
		"""A rep can open the screen at any time; it must not need an open day."""
		summary = day_service.summary(self.rep.name)
		self.assertFalse(summary["open"])
		self.assertIsNone(summary["minutes_on_route"])
		self.assertEqual(summary["actual_visits"], 0)


class TestMyBeats(DayFixture):
	def setUp(self):
		super().setUp()
		self.shops = [self.make_outlet(territory=self.territory).name for _ in range(2)]

	def test_a_rep_with_no_route_gets_an_empty_list_not_an_error(self):
		self.assertEqual(journey_service.my_beats(self.rep.name), [])

	def test_todays_route_is_flagged_and_comes_first(self):
		weekday = getdate(today()).strftime("%A")
		later = getdate(add_days(today(), 3)).strftime("%A")

		self.make_beat(territory=self.territory, assigned_to=self.rep.name,
		               outlets=self.shops, visit_day=later, frequency="Weekly")
		mine = self.make_beat(territory=self.territory, assigned_to=self.rep.name,
		                      visit_day=weekday, frequency="Weekly")

		beats = journey_service.my_beats(self.rep.name)
		self.assertEqual(len(beats), 2)
		self.assertEqual(beats[0]["name"], mine.name, "today's route must sort first")
		self.assertTrue(beats[0]["runs_today"])
		self.assertEqual(beats[0]["days_away"], 0)
		self.assertFalse(beats[1]["runs_today"])
		self.assertGreater(beats[1]["days_away"], 0)

	def test_next_run_is_a_real_upcoming_date(self):
		weekday = getdate(add_days(today(), 2)).strftime("%A")
		beat = self.make_beat(territory=self.territory, assigned_to=self.rep.name,
		                      visit_day=weekday, frequency="Weekly")

		beats = journey_service.my_beats(self.rep.name)
		row = next(b for b in beats if b["name"] == beat.name)
		self.assertEqual(getdate(row["next_run"]), getdate(add_days(today(), 2)))
		self.assertEqual(row["days_away"], 2)

	def test_an_inactive_route_is_not_listed(self):
		beat = self.make_beat(territory=self.territory, assigned_to=self.rep.name)
		beat.is_active = 0
		beat.save(ignore_permissions=True)
		self.assertEqual(journey_service.my_beats(self.rep.name), [])
