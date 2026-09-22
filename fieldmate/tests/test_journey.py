import frappe
from frappe.utils import add_days, getdate

from fieldmate.services import journey as journey_service
from fieldmate.tests.test_beat import BeatFixture


class JourneyFixture(BeatFixture):
	def monday(self, weeks_ahead=0):
		"""A known Monday, so week-of-month assertions are stable."""
		d = getdate("2026-10-05")          # first Monday of October 2026
		return add_days(d, weeks_ahead * 7)

	def make_holiday_list(self, dates):
		name = self.uid("HOL")
		doc = frappe.get_doc({
			"doctype": "Holiday List",
			"holiday_list_name": name,
			"from_date": getdate("2026-10-01"),
			"to_date": getdate("2026-10-31"),
			"holidays": [{"holiday_date": d, "description": "Test holiday"} for d in dates],
		}).insert(ignore_permissions=True)
		self.track("Holiday List", doc.name)
		return doc.name


class TestWeekOfMonth(JourneyFixture):
	def test_first_seven_days_are_week_one(self):
		for day in range(1, 8):
			self.assertEqual(journey_service.week_of_month(f"2026-10-0{day}" if day < 10 else f"2026-10-{day}"), 1)

	def test_week_five_collapses_into_four(self):
		"""A planner writing W4 means the last cycle, not a calendar week that may not exist."""
		self.assertEqual(journey_service.week_of_month("2026-10-29"), 4)
		self.assertEqual(journey_service.week_of_month("2026-10-31"), 4)


class TestBeatScheduling(JourneyFixture):
	def beat(self, **kwargs):
		return {"name": "B1", "visit_day": "Monday", "frequency": "Weekly",
		        "week_pattern": "All", "outlet_count": 10, **kwargs}

	def test_weekly_beat_runs_every_matching_day(self):
		for week in range(4):
			self.assertTrue(journey_service.beat_runs_on(self.beat(), self.monday(week)))

	def test_beat_does_not_run_on_another_weekday(self):
		self.assertFalse(journey_service.beat_runs_on(self.beat(), add_days(self.monday(), 1)))

	def test_monthly_beat_with_a_pattern_runs_once(self):
		b = self.beat(frequency="Monthly", week_pattern="W2")
		self.assertFalse(journey_service.beat_runs_on(b, self.monday(0)))
		self.assertTrue(journey_service.beat_runs_on(b, self.monday(1)))
		self.assertFalse(journey_service.beat_runs_on(b, self.monday(2)))

	def test_fortnightly_beat_alternates(self):
		"""Anchored on odd weeks so two fortnightly beats on one day do not collide weekly."""
		b = self.beat(frequency="Fortnightly", week_pattern="All")
		self.assertTrue(journey_service.beat_runs_on(b, self.monday(0)))
		self.assertFalse(journey_service.beat_runs_on(b, self.monday(1)))
		self.assertTrue(journey_service.beat_runs_on(b, self.monday(2)))


class TestPlanGeneration(JourneyFixture):
	def setUp(self):
		super().setUp()
		self.territory = self.make_territory()
		self.rep = self.make_field_user(territory=self.territory)
		self.shops = [self.make_outlet(territory=self.territory).name for _ in range(4)]
		self.beat_doc = self.make_beat(
			territory=self.territory, assigned_to=self.rep.name, outlets=self.shops
		)
		self.from_date = getdate("2026-10-01")
		self.to_date = getdate("2026-10-31")

	def generate(self, **kwargs):
		name = journey_service.generate(
			self.rep.name, self.from_date, self.to_date, **kwargs
		)
		self.track("FieldMate Journey Plan", name)
		return frappe.get_doc("FieldMate Journey Plan", name)

	def test_plan_covers_every_date_in_the_window(self):
		plan = self.generate()
		self.assertEqual(len(plan.days), 31)
		self.assertEqual(getdate(plan.days[0].plan_date), self.from_date)
		self.assertEqual(getdate(plan.days[-1].plan_date), self.to_date)

	def test_mondays_get_the_beat(self):
		plan = self.generate()
		mondays = [d for d in plan.days if d.day_of_week == "Monday"]
		self.assertTrue(mondays)
		for day in mondays:
			self.assertEqual(day.beat, self.beat_doc.name)
			self.assertEqual(day.outlet_count, 4)

	def test_other_days_get_no_beat_and_say_why(self):
		plan = self.generate()
		tuesday = next(d for d in plan.days if d.day_of_week == "Tuesday")
		self.assertIsNone(tuesday.beat)
		self.assertEqual(tuesday.note, "No beat scheduled")

	def test_totals_are_rolled_up(self):
		plan = self.generate()
		mondays = sum(1 for d in plan.days if d.day_of_week == "Monday")
		self.assertEqual(plan.planned_days, mondays)
		self.assertEqual(plan.planned_visits, mondays * 4)

	def test_holidays_are_not_planned(self):
		holiday = getdate("2026-10-12")          # a Monday
		plan = self.generate(holiday_list=self.make_holiday_list([holiday]))
		row = next(d for d in plan.days if getdate(d.plan_date) == holiday)
		self.assertEqual(row.status, "Holiday")
		self.assertFalse(row.is_working_day)
		self.assertIsNone(row.beat)

	def test_generating_twice_leaves_one_draft(self):
		"""Re-running after a beat change must not leave two drafts for one month.

		Asserted as a count rather than by name: the guarantee is that a planner never has to
		work out which of two drafts is current, not which document id survived.
		"""
		self.generate()
		second = self.generate()

		drafts = frappe.get_all(
			"FieldMate Journey Plan",
			filters={"field_user": self.rep.name, "from_date": self.from_date,
			         "to_date": self.to_date, "docstatus": 0},
			pluck="name",
		)
		self.assertEqual(drafts, [second.name], f"expected one draft, found {drafts}")

	def test_a_plan_longer_than_four_months_is_refused(self):
		"""Almost always a typo, and it would write thousands of rows first."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			journey_service.generate(self.rep.name, "2026-01-01", "2026-12-31")
		self.assertIn("one month at a time", str(ctx.exception))

	def test_overlapping_submitted_plans_are_refused(self):
		"""Two submitted plans covering one date make 'today's beat' ambiguous."""
		plan = self.generate()
		plan.submit()
		with self.assertRaises(frappe.ValidationError) as ctx:
			second = journey_service.generate(
				self.rep.name, add_days(self.from_date, 10), add_days(self.to_date, 10)
			)
			self.track("FieldMate Journey Plan", second)
			frappe.get_doc("FieldMate Journey Plan", second).submit()
		self.assertIn("already covers part of this period", str(ctx.exception))

	def test_day_for_reads_from_a_submitted_plan_only(self):
		plan = self.generate()
		monday = next(getdate(d.plan_date) for d in plan.days if d.day_of_week == "Monday")

		self.assertIsNone(journey_service.day_for(self.rep.name, monday))
		plan.submit()
		found = journey_service.day_for(self.rep.name, monday)
		self.assertEqual(found["beat"], self.beat_doc.name)
		self.assertEqual(found["outlet_count"], 4)

	def test_backwards_window_is_refused(self):
		with self.assertRaises((ValueError, frappe.ValidationError)):
			journey_service.generate(self.rep.name, self.to_date, self.from_date)
