import frappe
from frappe.utils import today

from fieldmate.services import journey as journey_service
from fieldmate.tests.test_journey import JourneyFixture


class TestDayForCarriesTheRoute(JourneyFixture):
	"""The Start Day screen shows what the route asks of the rep before they commit to it.

	`day_for` returns a plan-day row, which holds only a link to the beat. The shop count,
	travel estimate and expected duration live on the beat itself, so they are fetched here
	rather than left for the screen to guess - and a guessed estimate is worse than none.

	Note which of the two estimates is which: `estimated_duration_min` is **derived** by the
	beat's own roll_up from its outlets' expected durations, so it cannot be typed in.
	`estimated_travel_km` is entered by whoever plans the route.
	"""

	def setUp(self):
		super().setUp()
		self.territory = self.make_territory()
		self.rep = self.make_field_user(territory=self.territory)
		self.shops = [self.make_outlet(territory=self.territory).name for _ in range(3)]

	def plan_today(self, beat=None, status="Planned"):
		day = {
			"plan_date": today(), "status": status, "is_working_day": 1,
			"day_of_week": frappe.utils.getdate(today()).strftime("%A"),
		}
		if beat:
			day.update({"beat": beat.name, "outlet_count": beat.outlet_count})

		plan = frappe.get_doc({
			"doctype": "FieldMate Journey Plan",
			"field_user": self.rep.name,
			"from_date": today(), "to_date": today(),
			"days": [day],
		}).insert(ignore_permissions=True)
		self.track("FieldMate Journey Plan", plan.name)
		plan.submit()
		return plan

	def test_the_route_estimates_reach_the_app(self):
		beat = self.make_beat(territory=self.territory, assigned_to=self.rep.name,
		                      outlets=self.shops, estimated_travel_km=18.5)
		self.plan_today(beat)

		day = journey_service.day_for(self.rep.name, today())
		self.assertEqual(day["beat_name"], beat.beat_name)
		self.assertEqual(day["outlet_count"], 3)
		self.assertEqual(day["estimated_travel_km"], 18.5)
		# 3 shops at the fixture's 10 minutes each, summed by the beat itself.
		self.assertEqual(day["estimated_duration_min"], 30)

	def test_an_estimate_nobody_entered_reads_as_absent_not_zero(self):
		"""The screen hides the line when there is no figure. Zero would read as a real
		estimate of nothing, which is a different claim and a wrong one."""
		beat = self.make_beat(territory=self.territory, assigned_to=self.rep.name)
		self.plan_today(beat)

		day = journey_service.day_for(self.rep.name, today())
		self.assertIsNone(day["estimated_travel_km"])
		self.assertIsNone(day["estimated_duration_min"])   # no outlets, so nothing to sum
		self.assertEqual(day["beat_name"], beat.beat_name)

	def test_the_beat_name_is_sent_not_only_its_id(self):
		"""A rep reads "South Market", not "FM-BEAT-0073"."""
		beat = self.make_beat(territory=self.territory, assigned_to=self.rep.name,
		                      outlets=self.shops)
		self.plan_today(beat)

		day = journey_service.day_for(self.rep.name, today())
		self.assertNotEqual(day["beat_name"], day["beat"])
		self.assertEqual(day["beat_name"], beat.beat_name)

	def test_a_day_with_no_beat_carries_no_route_fields(self):
		self.plan_today(beat=None, status="Holiday")

		day = journey_service.day_for(self.rep.name, today())
		self.assertIsNone(day.get("beat"))
		self.assertNotIn("beat_name", day)
		self.assertNotIn("estimated_travel_km", day)

	def test_no_plan_at_all_is_none_not_an_error(self):
		self.assertIsNone(journey_service.day_for(self.rep.name, today()))
