import json

import frappe

from fieldmate.services import trail as trail_service
from fieldmate.tests.test_field_user import FieldUserFixture

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
