import frappe

from fieldmate.tests.base import FieldMateTestCase


class TestSyncDocTypes(FieldMateTestCase):
	def _device(self, uuid=None):
		uuid = uuid or self.uid("DEV")
		doc = frappe.get_doc({
			"doctype": "FieldMate Device Registry",
			"device_uuid": uuid,
			"user": "Administrator",
			"platform": "Android",
		}).insert(ignore_permissions=True)
		return self.track("FieldMate Device Registry", doc.name) and doc

	def test_registered_on_is_set_automatically(self):
		device = self._device()
		self.assertIsNotNone(device.registered_on)
		self.assertEqual(device.status, "Active")

	def test_device_uuid_is_unique(self):
		"""The guarantee the entire offline story rests on."""
		uuid = self.uid("DEV")
		self._device(uuid)
		with self.assertRaises((frappe.DuplicateEntryError, frappe.UniqueValidationError)):
			frappe.get_doc({
				"doctype": "FieldMate Device Registry",
				"device_uuid": uuid,
				"user": "Administrator",
			}).insert(ignore_permissions=True)

	def test_deregistering_clears_push_subscription(self):
		device = self._device()
		device.push_subscription = '{"endpoint":"https://example.test/x"}'
		device.save(ignore_permissions=True)
		device.status = "Deregistered"
		device.save(ignore_permissions=True)
		self.assertFalse(
			frappe.db.get_value("FieldMate Device Registry", device.name, "push_subscription")
		)

	def test_conflict_cannot_close_without_resolution(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({
				"doctype": "FieldMate Sync Conflict",
				"conflict_type": "Stale Write",
				"status": "Resolved",
				"client_uuid": self.uid("U"),
			}).insert(ignore_permissions=True)

	def test_conflict_records_who_resolved_it(self):
		doc = frappe.get_doc({
			"doctype": "FieldMate Sync Conflict",
			"conflict_type": "Duplicate",
			"status": "Open",
			"client_uuid": self.uid("U"),
		}).insert(ignore_permissions=True)
		self.track("FieldMate Sync Conflict", doc.name)

		doc.status = "Resolved"
		doc.resolution = "Keep Client"
		doc.save(ignore_permissions=True)
		self.assertEqual(doc.resolved_by, frappe.session.user)
		self.assertIsNotNone(doc.resolved_on)

	def test_batch_status_is_partial_when_some_land(self):
		batch = frappe.get_doc({
			"doctype": "FieldMate Sync Batch",
			"batch_uuid": self.uid("B"),
			"user": "Administrator",
			"direction": "Push",
			"status": "Processing",
			"record_count": 3,
			"accepted_count": 2,
			"rejected_count": 1,
		}).insert(ignore_permissions=True)
		self.track("FieldMate Sync Batch", batch.name)
		# One bad record must never block the rest of a rep's day from syncing.
		self.assertEqual(batch.derive_status(), "Partial")
