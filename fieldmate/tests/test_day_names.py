import frappe
from frappe.utils import today

from fieldmate.services import day as day_service
from fieldmate.tests.test_day import DayFixture


class TestNamesNotIds(DayFixture):
	"""A rep reads "South Market", never "FM-BEAT-0003".

	Every screen that shows a route was rendering the document id, because the services
	returned only the link. These check the name travels with it.
	"""

	def test_the_open_day_carries_its_route_name(self):
		beat = self.make_beat(territory=self.territory, assigned_to=self.rep.name)
		started = self.start_day()
		frappe.db.set_value("FieldMate Day", started["day"], "planned_beat",
		                    beat.name, update_modified=False)

		day = day_service.current(self.rep.name)
		self.assertEqual(day["planned_beat"], beat.name)
		self.assertEqual(day["planned_beat_name"], beat.beat_name)
		self.assertNotEqual(day["planned_beat_name"], day["planned_beat"])

	def test_a_day_with_no_route_has_no_route_name(self):
		self.start_day()
		day = day_service.current(self.rep.name)
		self.assertIsNone(day["planned_beat"])
		self.assertIsNone(day["planned_beat_name"])

	def test_the_summary_carries_the_route_name_too(self):
		"""Finish Day names the route as well, and reads it from the plan."""
		self.start_day()
		summary = day_service.summary(self.rep.name)
		self.assertIn("beat_name", summary)
		self.assertEqual(str(summary["date"]), today())
