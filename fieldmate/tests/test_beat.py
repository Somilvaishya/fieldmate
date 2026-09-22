import frappe

from fieldmate.tests.test_outlet import OutletFixture


class BeatFixture(OutletFixture):
	def make_beat(self, outlets=None, **kwargs):
		territory = kwargs.pop("territory", None) or self.make_territory()
		rep = kwargs.pop("assigned_to", None)
		if rep is None:
			rep = self.make_field_user(territory=territory).name

		data = {
			"doctype": "FieldMate Beat",
			"beat_name": kwargs.pop("beat_name", None) or self.uid("BEAT"),
			"territory": territory,
			"assigned_to": rep,
			"frequency": "Weekly",
			"visit_day": "Monday",
			"outlets": [
				{"outlet": o, "expected_duration_min": 10} for o in (outlets or [])
			],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Beat", doc.name)
		return doc


class TestBeatBasics(BeatFixture):
	def test_beat_is_named_by_series(self):
		self.assertTrue(self.make_beat().name.startswith("FM-BEAT-"))

	def test_sequence_is_renumbered_on_save(self):
		"""Gaps and duplicates must not accumulate as a planner edits the route."""
		territory = self.make_territory()
		shops = [self.make_outlet(territory=territory).name for _ in range(3)]
		beat = self.make_beat(territory=territory, outlets=shops)

		beat.outlets[0].sequence = 99
		beat.outlets[2].sequence = 99
		beat.save(ignore_permissions=True)
		self.assertEqual([r.sequence for r in beat.outlets], [1, 2, 3])

	def test_rollups_are_computed(self):
		territory = self.make_territory()
		shops = [self.make_outlet(territory=territory, monthly_potential=1000).name
		         for _ in range(2)]
		beat = self.make_beat(territory=territory, outlets=shops)
		self.assertEqual(beat.outlet_count, 2)
		self.assertEqual(beat.estimated_duration_min, 20)
		self.assertEqual(beat.total_potential, 2000)

	def test_empty_beat_is_allowed(self):
		"""A planner creates the route first and fills it afterwards."""
		beat = self.make_beat()
		self.assertEqual(beat.outlet_count, 0)


class TestBeatIntegrity(BeatFixture):
	def test_same_outlet_twice_is_refused(self):
		territory = self.make_territory()
		shop = self.make_outlet(territory=territory).name
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_beat(territory=territory, outlets=[shop, shop])
		self.assertIn("already on this beat", str(ctx.exception))

	def test_outlet_outside_the_territory_is_refused(self):
		"""Otherwise a rep is handed a route containing shops their own permissions hide."""
		here, elsewhere = self.make_territory(), self.make_territory()
		stranger = self.make_outlet(territory=elsewhere).name
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_beat(territory=here, outlets=[stranger])
		self.assertIn("outside this beat's territory", str(ctx.exception))

	def test_outlet_from_a_child_territory_is_allowed(self):
		"""Territory is a tree: a beat on a parent node may cover areas beneath it."""
		parent = self.make_territory()
		child = self.make_territory(parent=parent)
		shop = self.make_outlet(territory=child).name
		beat = self.make_beat(territory=parent, outlets=[shop])
		self.assertEqual(beat.outlet_count, 1)

	def test_outlet_cannot_sit_on_two_active_beats(self):
		"""Coverage is counted per beat; a shop on two beats is counted twice."""
		territory = self.make_territory()
		shop = self.make_outlet(territory=territory).name
		self.make_beat(territory=territory, outlets=[shop])
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_beat(territory=territory, outlets=[shop])
		self.assertIn("already on active beat", str(ctx.exception))

	def test_a_deactivated_beat_releases_its_outlets(self):
		territory = self.make_territory()
		shop = self.make_outlet(territory=territory).name
		first = self.make_beat(territory=territory, outlets=[shop])
		first.is_active = 0
		first.save(ignore_permissions=True)

		second = self.make_beat(territory=territory, outlets=[shop])
		self.assertEqual(second.outlet_count, 1)

	def test_weekly_beat_cannot_carry_a_week_pattern(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_beat(frequency="Weekly", week_pattern="W2")
		self.assertIn("Week Pattern must be All", str(ctx.exception))

	def test_monthly_beat_may_carry_a_week_pattern(self):
		beat = self.make_beat(frequency="Monthly", week_pattern="W2")
		self.assertEqual(beat.week_pattern, "W2")

	def test_rep_must_cover_the_beat_territory(self):
		"""A rep scoped elsewhere would receive a route they cannot read."""
		here, elsewhere = self.make_territory(), self.make_territory()
		stranger = self.make_field_user(territory=elsewhere)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.make_beat(territory=here, assigned_to=stranger.name)
		self.assertIn("does not include this beat's territory", str(ctx.exception))

	def test_manager_on_a_parent_may_hold_a_child_beat(self):
		parent = self.make_territory()
		child = self.make_territory(parent=parent)
		manager = self.make_field_user(territory=parent, designation="Area Manager")
		beat = self.make_beat(territory=child, assigned_to=manager.name)
		self.assertEqual(beat.territory, child)


class TestPrimaryBeatBackReference(BeatFixture):
	def primary_beat(self, outlet):
		return frappe.db.get_value("FieldMate Outlet", outlet, "primary_beat")

	def test_adding_an_outlet_points_it_at_the_beat(self):
		territory = self.make_territory()
		shop = self.make_outlet(territory=territory).name
		beat = self.make_beat(territory=territory, outlets=[shop])
		self.assertEqual(self.primary_beat(shop), beat.name)

	def test_removing_an_outlet_clears_the_pointer(self):
		territory = self.make_territory()
		a = self.make_outlet(territory=territory).name
		b = self.make_outlet(territory=territory).name
		beat = self.make_beat(territory=territory, outlets=[a, b])

		beat.outlets = [r for r in beat.outlets if r.outlet != b]
		beat.save(ignore_permissions=True)

		self.assertEqual(self.primary_beat(a), beat.name)
		self.assertIsNone(self.primary_beat(b))

	def test_deactivating_the_beat_clears_every_pointer(self):
		territory = self.make_territory()
		shop = self.make_outlet(territory=territory).name
		beat = self.make_beat(territory=territory, outlets=[shop])
		beat.is_active = 0
		beat.save(ignore_permissions=True)
		self.assertIsNone(self.primary_beat(shop))

	def test_deleting_the_beat_clears_every_pointer(self):
		territory = self.make_territory()
		shop = self.make_outlet(territory=territory).name
		beat = self.make_beat(territory=territory, outlets=[shop])
		frappe.delete_doc("FieldMate Beat", beat.name, force=True, ignore_permissions=True)
		self.assertIsNone(self.primary_beat(shop))


class TestBeatSync(BeatFixture):
	def test_beat_is_pullable_but_never_pushable(self):
		"""Routes are planned by managers. A phone may read one, never invent one."""
		from fieldmate.services import registry
		entry = registry.get("FieldMate Beat")
		self.assertIsNotNone(entry)
		self.assertTrue(entry.pull)
		self.assertFalse(entry.push)

	def test_rep_pulls_only_beats_in_their_territory(self):
		from fieldmate.services import sync as sync_service

		north = self.make_territory()
		delhi = self.make_territory(parent=north)
		mumbai = self.make_territory(parent=north)

		rep = self.make_field_user(territory=delhi)
		mine = self.make_beat(territory=delhi, assigned_to=rep.name)
		theirs = self.make_beat(territory=mumbai)
		frappe.db.commit()

		frappe.set_user(rep.user)
		try:
			pulled = {b["name"] for b in sync_service.pull(rep.user)["changes"].get("FieldMate Beat", [])}
		finally:
			frappe.set_user("Administrator")

		self.assertIn(mine.name, pulled)
		self.assertNotIn(theirs.name, pulled)
