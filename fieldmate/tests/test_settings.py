import json

import frappe

from fieldmate.services import settings as svc
from fieldmate.tests.base import FieldMateTestCase

TRACKED = (
	"enable_order_booking",
	"default_sales_mode",
	"gps_ping_interval_seconds",
	"sync_batch_size",
	"gps_trail_retention_days",
	"photo_max_kb",
)


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

	def test_the_only_mode_is_order_booking(self):
		self.assertEqual(svc.resolve_sales_mode(), svc.ORDER_BOOKING)
		self.assertEqual(svc.enabled_modes(), [svc.ORDER_BOOKING])

	def test_no_sales_model_at_all_is_refused(self):
		"""Kept with one model, because it is the check that will matter again when Phase 1
		adds the rest back beside it."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.apply(enable_order_booking=0)
		self.assertIn("at least one sales model", str(ctx.exception))

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

	def test_defaults_apply_without_the_form_ever_being_opened(self):
		"""A fresh site must behave sanely before anyone visits the settings page."""
		for key, expected in (("sync_batch_size", 50), ("photo_max_kb", 120),
		                      ("default_geo_fence_radius_m", 100)):
			self.assertEqual(svc.value(key), expected)
