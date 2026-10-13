import frappe
from frappe.utils import add_days, getdate

from fieldmate.services import field_user as field_user_service
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


class TestHowManyCallsAreExpected(JourneyFixture):
	"""`field_user.call_target` — the number on the rep's own screen.

	**The route answers first.** A journey plan already says which beat is walked today and how
	many shops are on it, so on a planned day the target is a fact rather than a figure somebody
	typed once. It moves with the plan: a short Thursday beat asks for less than a long Monday one,
	which a flat number can never say.

	It used to be a single Int on the Field User, shipped with a default of **25**. Every rep on
	every site was therefore asked for 25 calls a day whether their beat held 12 shops or 60, and
	nobody had ever chosen that number.
	"""

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

	def plan(self):
		name = journey_service.generate(self.rep.name, self.from_date, self.to_date)
		self.track("FieldMate Journey Plan", name)
		doc = frappe.get_doc("FieldMate Journey Plan", name)
		doc.flags.ignore_permissions = True
		doc.submit()
		return doc

	def typed(self, calls):
		frappe.db.set_value("FieldMate Field User", self.rep.name,
		                    "daily_target_calls", calls, update_modified=False)
		frappe.clear_document_cache("FieldMate Field User", self.rep.name)

	def test_a_planned_day_asks_for_the_shops_on_that_route(self):
		self.plan()
		answer = field_user_service.call_target(self.rep.name, self.monday())
		self.assertEqual(answer["daily_target_calls"], 4)
		self.assertEqual(answer["daily_target_basis"], "route")

	def test_it_names_the_beat_so_the_rep_can_check_it(self):
		self.plan()
		answer = field_user_service.call_target(self.rep.name, self.monday())
		self.assertTrue(answer["daily_target_beat"])

	def test_the_route_beats_a_number_typed_on_the_profile(self):
		"""Otherwise the dynamic figure would never be seen: the field shipped with a default, so
		every rep had one whether anybody meant it or not."""
		self.plan()
		self.typed(25)
		answer = field_user_service.call_target(self.rep.name, self.monday())
		self.assertEqual(answer["daily_target_calls"], 4)

	def test_a_day_with_no_route_falls_back_to_the_profile(self):
		"""Tuesday has no beat in this plan. A rep still gets an expectation where somebody has
		set one."""
		self.plan()
		self.typed(12)
		answer = field_user_service.call_target(self.rep.name, add_days(self.monday(), 1))
		self.assertEqual(answer["daily_target_calls"], 12)
		self.assertEqual(answer["daily_target_basis"], "profile")

	def test_neither_is_an_honest_dash(self):
		"""Better a dash on the screen than a number nobody stands behind."""
		self.plan()
		self.typed(0)
		answer = field_user_service.call_target(self.rep.name, add_days(self.monday(), 1))
		self.assertIsNone(answer["daily_target_calls"])
		self.assertIsNone(answer["daily_target_basis"])

	def test_a_rep_with_no_plan_at_all_still_gets_an_answer(self):
		self.typed(20)
		answer = field_user_service.call_target(self.rep.name, self.monday())
		self.assertEqual(answer["daily_target_calls"], 20)

	def test_the_profile_payload_carries_it(self):
		"""This is what the phone reads; a number with no basis beside it is the old flat
		figure wearing a new name."""
		self.plan()
		payload = field_user_service.profile(self.rep.user)
		self.assertIn("daily_target_calls", payload)
		self.assertIn("daily_target_basis", payload)
