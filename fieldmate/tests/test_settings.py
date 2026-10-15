import json

import frappe

from fieldmate.services import settings as svc
from fieldmate.tests.base import FieldMateTestCase

# Deliberately **not** including `track_gps_trail`: this class's restore goes through the
# Document and saves, which would write a `tabSingles` row for a field that had none - and a
# missing row reading as 0 on some sites is the bug `switch_on_the_gps_trail` exists to fix.
# The two tests that touch it restore the row themselves.
TRACKED = (
	"enable_secondary_sales",
	"enable_primary_sales",
	"default_sales_mode",
	"gps_ping_interval_seconds",
	"sync_batch_size",
	"gps_trail_retention_days",
	"photo_max_kb",
)


def stored_switch():
	"""The trail switch's row in `tabSingles`, or None when there is no row.

	Raw SQL because `frappe.db.get_value("Singles", ...)` appends `order by modified`, a column
	that table does not have, and dies with "Unknown column 'modified' in 'ORDER BY'". The patch
	had the same mistake, which would have broken `bench migrate` rather than a test.
	"""
	rows = frappe.db.sql(
		"select value from tabSingles where doctype = %s and field = %s",
		("FieldMate Settings", "track_gps_trail"))
	return rows[0][0] if rows else None


class TestSettings(FieldMateTestCase):
	"""Settings is a Single, so frappe hands back a shared instance and a stale copy saved twice
	raises TimestampMismatchError. Every test therefore loads its own fresh document and never
	reuses one across a save.
	"""

	def fresh(self):
		frappe.clear_document_cache("FieldMate Settings", "FieldMate Settings")
		doc = frappe.get_single("FieldMate Settings")
		doc.flags.ignore_permissions = True
		return doc

	def setUp(self):
		super().setUp()
		doc = self.fresh()
		self._original = {k: doc.get(k) for k in TRACKED}

	def tearDown(self):
		doc = self.fresh()
		for key, val in self._original.items():
			doc.set(key, val)
		doc.save()
		frappe.cache().delete_value("fieldmate_settings")
		frappe.db.commit()
		super().tearDown()

	def apply(self, **values):
		"""Set fields on a freshly loaded document and save it."""
		doc = self.fresh()
		for key, val in values.items():
			doc.set(key, val)
		doc.save()
		frappe.cache().delete_value("fieldmate_settings")
		return doc

	# ---------------------------------------------------------------- sales model

	def test_a_fresh_site_sells_secondary_only(self):
		"""Secondary on, primary off. A site that upgrades into primary sales turns it on; one
		that never does keeps behaving exactly as it did."""
		self.apply(enable_secondary_sales=1, enable_primary_sales=0)
		self.assertEqual(svc.enabled_modes(), [svc.SECONDARY])
		self.assertTrue(svc.allows(svc.SECONDARY))
		self.assertFalse(svc.allows(svc.PRIMARY))

	def test_primary_only_is_a_valid_site(self):
		"""A company that sells nothing through retailers - pure wholesale or sell-in."""
		self.apply(enable_secondary_sales=0, enable_primary_sales=1)
		self.assertEqual(svc.enabled_modes(), [svc.PRIMARY])
		self.assertFalse(svc.allows(svc.SECONDARY))

	def test_both_together(self):
		self.apply(enable_secondary_sales=1, enable_primary_sales=1)
		self.assertEqual(set(svc.enabled_modes()), {svc.SECONDARY, svc.PRIMARY})

	def test_neither_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.apply(enable_secondary_sales=0, enable_primary_sales=0)
		self.assertIn("at least one kind of sale", str(ctx.exception))

	# ---------------------------------------------------------------- bounds

	def test_absurd_ping_interval_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.apply(gps_ping_interval_seconds=5)
		self.assertIn("GPS Ping Interval", str(ctx.exception))

	def test_oversized_batch_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.apply(sync_batch_size=5000)

	def test_zero_retention_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.apply(gps_trail_retention_days=0)

	def test_bounds_message_says_what_it_got(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.apply(photo_max_kb=99999)
		self.assertIn("99999", str(ctx.exception))

	# ---------------------------------------------------------------- cache

	def test_cache_is_cleared_on_save(self):
		before = svc.value("photo_max_kb")
		doc = self.fresh()
		doc.photo_max_kb = 200
		doc.save()          # on_update clears the cache; no manual clear here
		self.assertEqual(svc.value("photo_max_kb"), 200)
		self.assertNotEqual(svc.value("photo_max_kb"), before)

	# ---------------------------------------------------------------- client payload

	def test_client_settings_hides_server_only_config(self):
		payload = svc.client_settings()
		for leaked in ("gps_trail_retention_days", "selfie_retention_days", "default_company"):
			self.assertNotIn(leaked, payload)
		self.assertIn("geo_fence_radius_m", payload)
		self.assertIn("photo_max_kb", payload)

	def test_client_settings_are_json_safe(self):
		json.dumps(svc.client_settings())

	def test_the_phone_is_told_whether_to_track_the_trail(self):
		"""The switch has to reach the handset, or it is a switch that does nothing."""
		payload = svc.client_settings()
		self.assertIn("track_gps_trail", payload)

	def test_the_trail_switch_is_on_even_with_no_stored_value(self):
		"""A Check added to a **Single** gets no row in `tabSingles`, and that absence is not
		read consistently: on one site `doc.get()` answered `None` and the service default of 1
		applied, on another - same empty table - it answered `0`. `settings.get()` has to treat
		0 as a choice somebody made, or a Check could never be switched off, so the second site
		read **tracking off** and every rep on it would have quietly stopped recording after a
		deploy that only meant to add a switch.

		The first version of this test asserted `True` and passed on the site that answers
		`None` - a pass that had nothing to do with the code being right. So this one removes
		the stored value and runs the patch that is supposed to put it there.
		"""
		from fieldmate.patches.switch_on_the_gps_trail import execute

		self._forget_the_switch()
		execute()

		stored = stored_switch()
		self.assertEqual(stored, "1")
		self.assertIs(svc.client_settings()["track_gps_trail"], True)

	def test_switching_the_trail_off_survives_the_patch(self):
		"""Re-run on a site whose admin has turned it off. Their answer stands."""
		from fieldmate.patches.switch_on_the_gps_trail import execute

		self._forget_the_switch()
		frappe.db.sql(
			"insert into tabSingles (doctype, field, value) values (%s, %s, %s)",
			("FieldMate Settings", "track_gps_trail", "0"))
		frappe.clear_document_cache("FieldMate Settings", "FieldMate Settings")
		frappe.cache().delete_value("fieldmate_settings")

		execute()

		stored = stored_switch()
		self.assertEqual(stored, "0")
		self.assertIs(svc.client_settings()["track_gps_trail"], False)

	def _forget_the_switch(self):
		"""Back to a site that has never stored a value for it, which is what a deploy leaves.

		The stored row is put back afterwards by hand. `tearDown` here **commits**, and this
		class's snapshot/restore works through the Document - which would write a row where
		there was none, leaving the test site in exactly the state whose misreading is the bug
		under test.
		"""
		before = stored_switch()
		self.addCleanup(self._restore_the_switch, before)
		self._drop_switch_row()

	def _drop_switch_row(self):
		frappe.db.sql(
			"delete from tabSingles where doctype = %s and field = %s",
			("FieldMate Settings", "track_gps_trail"))
		frappe.clear_document_cache("FieldMate Settings", "FieldMate Settings")
		frappe.cache().delete_value("fieldmate_settings")

	def _restore_the_switch(self, value):
		self._drop_switch_row()
		if value is not None:
			frappe.db.sql(
				"insert into tabSingles (doctype, field, value) values (%s, %s, %s)",
				("FieldMate Settings", "track_gps_trail", value))
		frappe.clear_document_cache("FieldMate Settings", "FieldMate Settings")
		frappe.cache().delete_value("fieldmate_settings")

	def test_defaults_apply_without_the_form_ever_being_opened(self):
		"""A fresh site must behave sanely before anyone visits the settings page."""
		for key, expected in (("sync_batch_size", 50), ("photo_max_kb", 120),
		                      ("default_geo_fence_radius_m", 100)):
			self.assertEqual(svc.value(key), expected)
