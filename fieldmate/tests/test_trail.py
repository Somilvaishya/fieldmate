import json

import frappe
from frappe.utils import today

from fieldmate.services import trail as trail_service
from fieldmate.tests.test_day import DELHI
from fieldmate.tests.test_field_user import FieldUserFixture
from fieldmate.tests.test_visit import VisitFixture

# Two points about 14.4 km apart in Delhi, measured straight-line.
CONNAUGHT = (28.6139, 77.2090)
MODEL_TOWN = (28.7041, 77.1025)


class TrailFixture(FieldUserFixture):
	def setUp(self):
		super().setUp()
		self.rep = self.make_field_user()

	def tearDown(self):
		for name in frappe.get_all("FieldMate Location Trail",
		                           filters={"field_user": self.rep.name}, pluck="name"):
			frappe.delete_doc("FieldMate Location Trail", name, force=True, ignore_permissions=True)
		super().tearDown()


class TestHaversine(TrailFixture):
	def test_known_distance(self):
		km = trail_service.haversine_km(*CONNAUGHT, *MODEL_TOWN)
		self.assertGreater(km, 13)
		self.assertLess(km, 16)

	def test_same_point_is_zero(self):
		self.assertEqual(trail_service.haversine_km(*CONNAUGHT, *CONNAUGHT), 0)


class TestSummarise(TrailFixture):
	def test_empty_trail(self):
		s = trail_service.summarise([])
		self.assertEqual(s["ping_count"], 0)
		self.assertEqual(s["total_distance_km"], 0)

	def test_distance_across_a_drive(self):
		s = trail_service.summarise([
			{"t": "2026-09-22 09:00:00", "lat": CONNAUGHT[0], "lon": CONNAUGHT[1]},
			{"t": "2026-09-22 09:30:00", "lat": MODEL_TOWN[0], "lon": MODEL_TOWN[1]},
		])
		self.assertGreater(s["total_distance_km"], 11)
		self.assertGreater(s["max_speed_kmph"], 20)

	def test_a_phone_sitting_still_travels_nowhere(self):
		"""GPS wanders a few metres continuously; summing that noise inflates every claim."""
		pings = [
			{"t": f"2026-09-22 09:{m:02d}:00", "lat": 28.6139 + m * 0.00001, "lon": 77.2090}
			for m in range(30)
		]
		self.assertEqual(trail_service.summarise(pings)["total_distance_km"], 0)

	def test_a_teleport_is_counted_and_excluded(self):
		"""Paying for an impossible jump would be worse than under-reporting a real drive."""
		s = trail_service.summarise([
			{"t": "2026-09-22 09:00:00", "lat": CONNAUGHT[0], "lon": CONNAUGHT[1]},
			{"t": "2026-09-22 09:01:00", "lat": MODEL_TOWN[0], "lon": MODEL_TOWN[1]},
		])
		self.assertEqual(s["implausible_jumps"], 1)
		self.assertEqual(s["total_distance_km"], 0)

	def test_mock_pings_are_counted(self):
		s = trail_service.summarise([
			{"t": "2026-09-22 09:00:00", "lat": 28.61, "lon": 77.20, "mock": True},
			{"t": "2026-09-22 09:05:00", "lat": 28.62, "lon": 77.21},
		])
		self.assertEqual(s["mock_ping_count"], 1)

	def test_pings_are_ordered_before_measuring(self):
		"""A batch can arrive out of order after a retry; distance must not depend on that."""
		forwards = trail_service.summarise([
			{"t": "2026-09-22 09:00:00", "lat": CONNAUGHT[0], "lon": CONNAUGHT[1]},
			{"t": "2026-09-22 09:30:00", "lat": MODEL_TOWN[0], "lon": MODEL_TOWN[1]},
		])
		backwards = trail_service.summarise([
			{"t": "2026-09-22 09:30:00", "lat": MODEL_TOWN[0], "lon": MODEL_TOWN[1]},
			{"t": "2026-09-22 09:00:00", "lat": CONNAUGHT[0], "lon": CONNAUGHT[1]},
		])
		self.assertEqual(forwards["total_distance_km"], backwards["total_distance_km"])

	def test_pings_without_coordinates_are_dropped(self):
		s = trail_service.summarise([
			{"t": "2026-09-22 09:00:00", "lat": None, "lon": None},
			{"t": "2026-09-22 09:05:00", "lat": 28.61, "lon": 77.20},
		])
		self.assertEqual(s["ping_count"], 1)


class TestTrailStorage(TrailFixture):
	def test_one_row_per_rep_per_day(self):
		"""A row per ping would add ~30 million rows a year at 250 reps."""
		for hour in range(9, 13):
			trail_service.append(self.rep.name, [
				{"t": f"2026-09-22 {hour:02d}:00:00", "lat": 28.61 + hour / 1000, "lon": 77.20}
			], trail_date="2026-09-22")

		rows = frappe.get_all("FieldMate Location Trail",
		                      filters={"field_user": self.rep.name, "trail_date": "2026-09-22"})
		self.assertEqual(len(rows), 1)

	def test_pings_accumulate_across_batches(self):
		trail_service.append(self.rep.name, [
			{"t": "2026-09-22 09:00:00", "lat": 28.61, "lon": 77.20}
		], trail_date="2026-09-22")
		result = trail_service.append(self.rep.name, [
			{"t": "2026-09-22 09:05:00", "lat": 28.62, "lon": 77.21}
		], trail_date="2026-09-22")
		self.assertEqual(result["ping_count"], 2)

	def test_a_replayed_upload_does_not_inflate_distance(self):
		"""A retried batch after a dropped connection must not be paid for twice."""
		batch = [
			{"t": "2026-09-22 09:00:00", "lat": CONNAUGHT[0], "lon": CONNAUGHT[1]},
			{"t": "2026-09-22 09:30:00", "lat": MODEL_TOWN[0], "lon": MODEL_TOWN[1]},
		]
		first = trail_service.append(self.rep.name, batch, trail_date="2026-09-22")
		second = trail_service.append(self.rep.name, batch, trail_date="2026-09-22")

		self.assertEqual(second["added"], 0)
		self.assertEqual(second["ignored_duplicates"], 2)
		self.assertEqual(first["total_distance_km"], second["total_distance_km"])
		self.assertEqual(second["ping_count"], 2)

	def test_the_path_is_stored_as_json(self):
		trail_service.append(self.rep.name, [
			{"t": "2026-09-22 09:00:00", "lat": 28.61, "lon": 77.20}
		], trail_date="2026-09-22")
		raw = frappe.db.get_value("FieldMate Location Trail",
		                          {"field_user": self.rep.name, "trail_date": "2026-09-22"}, "trail")
		self.assertEqual(len(json.loads(raw)), 1)

	def test_distance_for_reads_the_summary(self):
		trail_service.append(self.rep.name, [
			{"t": "2026-09-22 09:00:00", "lat": CONNAUGHT[0], "lon": CONNAUGHT[1]},
			{"t": "2026-09-22 09:30:00", "lat": MODEL_TOWN[0], "lon": MODEL_TOWN[1]},
		], trail_date="2026-09-22")
		self.assertGreater(trail_service.distance_for(self.rep.name, "2026-09-22"), 11)

	def test_no_trail_reads_as_zero(self):
		self.assertEqual(trail_service.distance_for(self.rep.name, "2020-01-01"), 0)

	def test_retention_purge_removes_old_trails(self):
		"""GPS trails track a named employee, so they do not live forever."""
		trail_service.append(self.rep.name, [
			{"t": "2020-01-01 09:00:00", "lat": 28.61, "lon": 77.20}
		], trail_date="2020-01-01")
		removed = trail_service.purge_older_than(30)
		self.assertGreaterEqual(removed, 1)
		self.assertEqual(trail_service.distance_for(self.rep.name, "2020-01-01"), 0)

	def test_a_zero_retention_purges_nothing(self):
		"""A misconfigured retention must not silently delete everything."""
		self.assertEqual(trail_service.purge_older_than(0), 0)


class TestRouteDistance(VisitFixture):
	"""Travel measured along the shops actually visited, for the days with no trail at all.

	A PWA only reports its position while it is open. A rep who worked a full beat with the
	phone in a pocket has no trail, and that used to read as zero kilometres - a day end showing
	no travel and an expense claim worth nothing for a day somebody drove.
	"""

	def tearDown(self):
		# VisitFixture, not TrailFixture, so the trail rows one of these tests writes are this
		# class's own to clean up. A leaked trail would make the next day's route look recorded.
		for name in frappe.get_all("FieldMate Location Trail",
		                           filters={"field_user": self.rep.name}, pluck="name"):
			frappe.delete_doc("FieldMate Location Trail", name, force=True, ignore_permissions=True)
		super().tearDown()

	def visit_at(self, point, **kwargs):
		"""One finished visit at a given place, which is what puts it on the route."""
		shop = self.make_outlet(
			territory=self.territory,
			latitude=kwargs.pop("shop_lat", point[0]),
			longitude=kwargs.pop("shop_lon", point[1]),
			enable_geo_fence=0,
			approval_status="Approved",
		)
		payload = {"outlet": shop.name, "latitude": point[0], "longitude": point[1]}
		payload.update(kwargs)
		visit = self.check_in(**payload)
		self.check_out(visit["visit"])
		return shop

	def test_a_day_with_no_trail_is_measured_along_the_route(self):
		self.start_day()
		self.visit_at(MODEL_TOWN)
		km = trail_service.distance_for(self.rep.name, today())
		# Day start at Connaught Place, one shop in Model Town: the 14.4 km between them.
		self.assertGreater(km, 13)
		self.assertLess(km, 16)

	def test_the_trail_still_wins_where_there_is_one(self):
		"""The trail is where the rep actually was. The route is only ever the fallback.

		Set up so the two figures cannot be confused: the route through the visited shop is
		about 14 km, the recorded trail about 1 km. Only one of them can be the answer.
		"""
		self.start_day()
		self.visit_at(MODEL_TOWN)
		self.assertGreater(trail_service.route_distance_for(self.rep.name, today()), 13)

		# ~1 km north of the day-start point: 0.009 degrees of latitude.
		trail_service.append(self.rep.name, [
			{"t": f"{today()} 09:00:00", "lat": CONNAUGHT[0], "lon": CONNAUGHT[1], "acc": 8},
			{"t": f"{today()} 09:30:00", "lat": CONNAUGHT[0] + 0.009, "lon": CONNAUGHT[1],
			 "acc": 8},
		], trail_date=today())

		self.assertLess(trail_service.distance_for(self.rep.name, today()), 2)

	def test_a_shop_visited_without_a_fix_falls_back_to_its_pin(self):
		"""A check-in can have no coordinates - GPS off, or a fence the company does not enforce.

		The shop's own pin is still a place, and a shop that was visited is still travel.
		"""
		self.start_day()
		self.visit_at(MODEL_TOWN, latitude=None, longitude=None,
		              shop_lat=MODEL_TOWN[0], shop_lon=MODEL_TOWN[1])
		km = trail_service.route_distance_for(self.rep.name, today())
		self.assertGreater(km, 13)

	def test_a_shop_nobody_has_ever_located_is_skipped(self):
		"""Not counted as (0, 0), which is in the Atlantic and would add nine thousand km."""
		self.start_day()
		self.visit_at(MODEL_TOWN)
		self.visit_at((None, None), shop_lat=None, shop_lon=None,
		              latitude=None, longitude=None)
		km = trail_service.route_distance_for(self.rep.name, today())
		self.assertLess(km, 20)

	def test_a_day_that_went_nowhere_is_zero_not_missing(self):
		"""Started the day and visited the shop downstairs. Zero is the true answer here."""
		self.start_day()
		self.visit_at(DELHI)
		self.assertEqual(trail_service.route_distance_for(self.rep.name, today()), 0)

	def test_a_cancelled_visit_is_not_travel(self):
		"""A visit that was cancelled did not happen, so nobody drove to it."""
		self.start_day()
		shop = self.make_outlet(territory=self.territory, latitude=MODEL_TOWN[0],
		                        longitude=MODEL_TOWN[1], enable_geo_fence=0,
		                        approval_status="Approved")
		visit = self.check_in(outlet=shop.name, latitude=MODEL_TOWN[0], longitude=MODEL_TOWN[1])
		self.check_out(visit["visit"])
		self.assertGreater(trail_service.route_distance_for(self.rep.name, today()), 13)
		doc = frappe.get_doc("FieldMate Visit", visit["visit"])
		doc.flags.ignore_permissions = True
		doc.cancel()
		self.assertEqual(trail_service.route_distance_for(self.rep.name, today()), 0)

	def test_no_day_and_no_visits_is_zero(self):
		self.assertEqual(trail_service.route_distance_for(self.rep.name, "2020-01-01"), 0)

	def test_the_figure_says_where_it_came_from(self):
		"""The basis travels with the number, because the claim screen prints it.

		It used to badge the figure "GPS trail" unconditionally. A route figure under that badge
		is not a rounding problem - it is a sentence about a trail that does not exist, shown to
		the rep claiming and to the manager approving.
		"""
		self.start_day()
		self.visit_at(MODEL_TOWN)
		self.assertEqual(trail_service.measure(self.rep.name, today())["basis"], "route")

		trail_service.append(self.rep.name, [
			{"t": f"{today()} 09:00:00", "lat": CONNAUGHT[0], "lon": CONNAUGHT[1], "acc": 8},
			{"t": f"{today()} 09:30:00", "lat": MODEL_TOWN[0], "lon": MODEL_TOWN[1], "acc": 8},
		], trail_date=today())
		self.assertEqual(trail_service.measure(self.rep.name, today())["basis"], "trail")

	def test_a_day_nobody_recorded_claims_no_basis_at_all(self):
		"""Zero km from a route of nothing is not a measurement, and must not read as one."""
		measured = trail_service.measure(self.rep.name, "2020-01-01")
		self.assertEqual(measured["km"], 0)
		self.assertIsNone(measured["basis"])

	def test_a_real_route_that_comes_to_zero_is_still_a_measurement(self):
		"""Started at the shop downstairs and walked back. Zero km, and we did measure it.

		The basis used to be decided by the distance, so this day read as "nothing recorded" -
		which tells the rep no figure exists and leaves their manager reading the same thing,
		when in fact two places were recorded and the honest answer is zero.
		"""
		self.start_day()
		self.visit_at(DELHI)
		measured = trail_service.measure(self.rep.name, today())
		self.assertEqual(measured["km"], 0)
		self.assertEqual(measured["basis"], "route")

	def test_one_stop_on_its_own_measures_nothing(self):
		"""A day start nobody located, and one shop. One point is not a journey."""
		shop = self.make_outlet(territory=self.territory, latitude=MODEL_TOWN[0],
		                        longitude=MODEL_TOWN[1], enable_geo_fence=0,
		                        approval_status="Approved")
		self.start_day(latitude=None, longitude=None)
		visit = self.check_in(outlet=shop.name, latitude=MODEL_TOWN[0], longitude=MODEL_TOWN[1])
		self.check_out(visit["visit"])
		self.assertIsNone(trail_service.measure(self.rep.name, today())["basis"])
