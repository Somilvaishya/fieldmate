"""The Plan tab: a manager builds and approves the team's month, and shapes their beats.

The route itself is `journey.build_days`, tested in test_journey.py. What is tested here is the
reach: that an Area Manager can now do from the phone what they did in Desk, and only for the
people who report to them.
"""

import frappe

from fieldmate.services import plan as plan_service
from fieldmate.tests.test_team import TeamLine
from fieldmate.tests.test_visit import VisitFixture

# October 2026: the fixture beat runs on Mondays, and the 5th is the first one.
MONTH = "2026-10-05"


class PlanFixture(TeamLine, VisitFixture):
	def setUp(self):
		super().setUp()
		self.build_line()

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("FieldMate Journey Plan",
		                           filters={"field_user": self.rep.name}, pluck="name"):
			self._drop("FieldMate Journey Plan", name)
		frappe.db.commit()
		super().tearDown()

	def row(self, user):
		board = self.as_user(user, plan_service.overview, MONTH)
		return next((m for m in board["members"] if m["field_user"] == self.rep.name), None)


class TestTheMonth(PlanFixture):
	def test_the_manager_sees_the_rep_with_no_plan_yet(self):
		row = self.row(self.am.user)
		self.assertIsNone(row["plan"])
		self.assertEqual(row["beats"], 1)

	def test_another_manager_does_not(self):
		self.assertIsNone(self.row(self.other_am.user))

	def test_building_makes_a_draft_with_the_beat_on_its_day(self):
		built = self.as_user(self.am.user, plan_service.build, self.rep.name, MONTH)
		self.assertEqual(built["state"], "Draft")
		self.assertEqual(len(built["days"]), 31)
		monday = next(d for d in built["days"] if d["plan_date"] == MONTH)
		self.assertEqual(monday["beat"], self.beat.name)
		self.assertEqual(monday["beat_name"], self.beat.beat_name)

	def test_a_draft_does_not_reach_the_rep_until_approved(self):
		from fieldmate.services import journey as journey_service

		built = self.as_user(self.am.user, plan_service.build, self.rep.name, MONTH)
		self.assertIsNone(journey_service.day_for(self.rep.name, MONTH))

		approved = self.as_user(self.am.user, plan_service.approve, built["name"])
		self.assertEqual(approved["state"], "Approved")
		self.assertEqual(journey_service.day_for(self.rep.name, MONTH)["beat"], self.beat.name)
		self.assertEqual(self.row(self.am.user)["plan"]["state"], "Approved")

	def test_building_twice_replaces_the_draft(self):
		"""Counted, not named: deleting the last of a naming series winds the counter back, so
		the second draft routinely takes the first one's name."""
		self.as_user(self.am.user, plan_service.build, self.rep.name, MONTH)
		self.as_user(self.am.user, plan_service.build, self.rep.name, MONTH)
		self.assertEqual(frappe.db.count("FieldMate Journey Plan",
		                                 {"field_user": self.rep.name, "docstatus": 0}), 1)

	def test_an_approved_month_is_not_rebuilt_over(self):
		built = self.as_user(self.am.user, plan_service.build, self.rep.name, MONTH)
		self.as_user(self.am.user, plan_service.approve, built["name"])
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.am.user, plan_service.build, self.rep.name, MONTH)

	def test_another_manager_cannot_build_it(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other_am.user, plan_service.build, self.rep.name, MONTH)


class TestWithdrawingAnApprovedMonth(PlanFixture):
	"""Desk gave cancel to the Regional Manager and above, not the Area Manager. So does this."""

	def setUp(self):
		super().setUp()
		built = self.as_user(self.am.user, plan_service.build, self.rep.name, MONTH)
		self.plan = self.as_user(self.am.user, plan_service.approve, built["name"])["name"]

	def test_the_area_manager_may_not(self):
		self.assertFalse(self.as_user(self.am.user, plan_service.days, self.plan)["can_cancel"])
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.am.user, plan_service.cancel, self.plan)

	def test_the_regional_manager_may(self):
		self.assertTrue(self.as_user(self.rm.user, plan_service.days, self.plan)["can_cancel"])
		self.as_user(self.rm.user, plan_service.cancel, self.plan)
		self.assertEqual(frappe.db.get_value("FieldMate Journey Plan", self.plan, "docstatus"), 2)


class TestBeatsFromThePhone(PlanFixture):
	def spare_shop(self):
		return self.make_outlet(territory=self.territory, approval_status="Approved")

	def test_the_team_beats_are_listed_with_the_rep_named(self):
		rows = self.as_user(self.am.user, plan_service.beats)
		row = next(r for r in rows if r["name"] == self.beat.name)
		self.assertEqual(row["rep_name"], self.rep.full_name or self.rep.name)

	def test_and_not_another_teams(self):
		self.assertEqual(self.as_user(self.other_am.user, plan_service.beats), [])

	def test_a_shop_already_on_a_beat_is_not_offered(self):
		spare = self.spare_shop()
		free = [r["name"] for r in self.as_user(self.am.user, plan_service.free_outlets,
		                                        self.territory)]
		self.assertIn(spare.name, free)
		self.assertNotIn(self.outlet.name, free)

	def test_a_new_beat_from_the_phone(self):
		spare = self.spare_shop()
		saved = self.as_user(self.am.user, plan_service.save_beat, {
			"beat_name": "Thursday Market", "assigned_to": self.rep.name,
			"visit_day": "Thursday", "frequency": "Weekly", "outlets": [spare.name]})
		self.track("FieldMate Beat", saved["name"])
		self.assertEqual(saved["outlet_count"], 1)
		self.assertEqual(saved["territory"], self.rep.territory)
		self.assertEqual(frappe.db.get_value("FieldMate Outlet", spare.name, "primary_beat"),
		                 saved["name"])

	def test_a_weekly_beat_drops_a_week_pattern_rather_than_refusing(self):
		saved = self.as_user(self.am.user, plan_service.save_beat, {
			"beat_name": "Odd Friday", "assigned_to": self.rep.name,
			"visit_day": "Friday", "frequency": "Weekly", "week_pattern": "W2"})
		self.track("FieldMate Beat", saved["name"])
		self.assertEqual(saved["week_pattern"], "All")

	def test_reordering_the_shops_is_kept(self):
		spare = self.spare_shop()
		saved = self.as_user(self.am.user, plan_service.save_beat, {
			"name": self.beat.name, "outlets": [spare.name, self.outlet.name]})
		self.assertEqual([o["outlet"] for o in saved["outlets"]], [spare.name, self.outlet.name])

	def test_a_shop_on_another_beat_is_still_refused(self):
		"""The controller's rule, reached from the phone - not reimplemented beside it."""
		with self.assertRaises(frappe.ValidationError):
			saved = self.as_user(self.am.user, plan_service.save_beat, {
				"beat_name": "Thief", "assigned_to": self.rep.name, "outlets": [self.outlet.name]})
			self.track("FieldMate Beat", saved["name"])

	def test_another_manager_cannot_edit_it(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.other_am.user, plan_service.save_beat,
			             {"name": self.beat.name, "beat_name": "Mine now"})

	def test_nor_hand_a_beat_to_somebody_outside_the_team(self):
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.am.user, plan_service.save_beat,
			             {"name": self.beat.name, "assigned_to": self.other_am.name})


class TestTheWindowAndWhatItIsPlannedAgainst(PlanFixture):
	"""A range rather than only a month, a territory from the manager's permission, and a
	holiday list the manager is allowed to read."""

	def test_the_manager_plans_inside_their_territory_permission(self):
		self.assertIn(self.territory, self.as_user(self.am.user, plan_service.territories))

	def test_and_not_outside_it(self):
		elsewhere = self.make_territory()
		self.assertNotIn(elsewhere, self.as_user(self.am.user, plan_service.territories))
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.am.user, plan_service.overview, MONTH, territory=elsewhere)

	def test_a_territory_filters_the_reps(self):
		elsewhere = self.make_territory()
		self.assertEqual(
			self.as_user("Administrator", plan_service.overview, MONTH, territory=elsewhere)["members"], [])
		names = [m["field_user"] for m in self.as_user(
			self.am.user, plan_service.overview, MONTH, territory=self.territory)["members"]]
		self.assertIn(self.rep.name, names)

	def test_a_range_rather_than_a_month(self):
		built = self.as_user(self.am.user, plan_service.build, self.rep.name,
		                     from_date="2026-10-05", to_date="2026-10-18")
		self.assertEqual(len(built["days"]), 14)
		self.assertEqual(built["from_date"], "2026-10-05")

	def test_a_reversed_range_is_refused_in_words(self):
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.am.user, plan_service.build, self.rep.name,
			             from_date="2026-10-18", to_date="2026-10-05")

	def test_a_new_range_replaces_an_overlapping_draft(self):
		self.as_user(self.am.user, plan_service.build, self.rep.name, MONTH)
		self.as_user(self.am.user, plan_service.build, self.rep.name,
		             from_date="2026-10-10", to_date="2026-10-20")
		self.assertEqual(frappe.db.count("FieldMate Journey Plan",
		                                 {"field_user": self.rep.name, "docstatus": 0}), 1)

	def test_a_holiday_list_the_manager_can_read_takes_the_days_off(self):
		holidays = self.make_holiday_list(["2026-10-05"])
		built = self.as_user("Administrator", plan_service.build, self.rep.name, MONTH,
		                     holiday_list=holidays)
		first_monday = next(d for d in built["days"] if d["plan_date"] == MONTH)
		self.assertEqual(first_monday["status"], "Holiday")
		self.assertEqual(built["holiday_list"], holidays)

	def test_a_holiday_list_the_manager_cannot_read_is_neither_offered_nor_taken(self):
		holidays = self.make_holiday_list(["2026-10-05"])
		readable = frappe.has_permission("Holiday List", "read", user=self.am.user)
		offered = self.as_user(self.am.user, plan_service.holiday_lists, self.rep.name)["options"]
		self.assertEqual(holidays in offered, bool(readable))
		if not readable:
			with self.assertRaises(frappe.PermissionError):
				self.as_user(self.am.user, plan_service.build, self.rep.name, MONTH,
				             holiday_list=holidays)


class TestWhatABeatMayBeSetTo(PlanFixture):
	def test_the_options_are_the_managers_territory_and_the_reps_distributors(self):
		options = self.as_user(self.am.user, plan_service.beat_options, self.rep.name)
		self.assertIn(self.territory, options["territories"])
		self.assertEqual(options["default_territory"], self.rep.territory)
		self.assertIn(self.outlet.distributor, [d["name"] for d in options["distributors"]])

	def test_a_distributor_and_a_start_date_are_kept(self):
		saved = self.as_user(self.am.user, plan_service.save_beat, {
			"beat_name": "With a depot", "assigned_to": self.rep.name,
			"distributor": self.outlet.distributor, "effective_from": "2026-11-01",
			"notes": "Start from the chowk"})
		self.track("FieldMate Beat", saved["name"])
		self.assertEqual(saved["distributor"], self.outlet.distributor)
		self.assertEqual(saved["effective_from"], "2026-11-01")
		self.assertEqual(saved["notes"], "Start from the chowk")

	def test_a_distributor_the_rep_does_not_reach_is_refused(self):
		stranger = self.make_distributor()
		with self.assertRaises(frappe.ValidationError):
			self.as_user(self.am.user, plan_service.save_beat, {
				"beat_name": "Wrong depot", "assigned_to": self.rep.name, "distributor": stranger})

	def test_a_territory_outside_the_managers_permission_is_refused(self):
		elsewhere = self.make_territory()
		with self.assertRaises(frappe.PermissionError):
			self.as_user(self.am.user, plan_service.save_beat, {
				"beat_name": "Far away", "assigned_to": self.rep.name, "territory": elsewhere})
