import frappe

from fieldmate.services import registry
from fieldmate.services import sync as sync_service
from fieldmate.tests.base import FieldMateTestCase

TARGET = "FieldMate Sync Conflict"


class TestSyncPush(FieldMateTestCase):
	"""Exercises the real create path.

	`FieldMate Sync Conflict` is registered as pushable for the duration of these tests. It is a
	genuine app DocType with a client_uuid field, so this tests the actual machinery rather than
	a stand-in. Phase 1 replaces it with FieldMate Outlet.
	"""

	def setUp(self):
		super().setUp()
		self._saved = registry.get(TARGET)
		registry.register(
			registry.Syncable(
				doctype=TARGET,
				uuid_field="client_uuid",
				push=True,
				pull=False,
				server_owned=("resolved_by", "resolved_on"),
			)
		)
		self.device = frappe.get_doc({
			"doctype": "FieldMate Device Registry",
			"device_uuid": self.uid("DEV"),
			"user": "Administrator",
			"platform": "Android",
		}).insert(ignore_permissions=True)
		self.track("FieldMate Device Registry", self.device.name)

	def tearDown(self):
		for name in frappe.get_all(TARGET, filters={"client_uuid": ["like", "T-%"]}, pluck="name"):
			frappe.delete_doc(TARGET, name, force=True, ignore_permissions=True)
		for name in frappe.get_all("FieldMate Sync Batch", filters={"batch_uuid": ["like", "T-%"]}, pluck="name"):
			frappe.delete_doc("FieldMate Sync Batch", name, force=True, ignore_permissions=True)
		if self._saved:
			registry.register(self._saved)
		super().tearDown()

	def _records(self, n):
		return [
			{"doctype": TARGET, "client_uuid": self.uid("T"),
			 "data": {"conflict_type": "Duplicate", "status": "Open"}}
			for _ in range(n)
		]

	def test_push_creates_records(self):
		records = self._records(3)
		result = sync_service.push("Administrator", self.device, self.uid("T"), records)
		self.assertEqual(result["accepted"], 3)
		self.assertEqual(result["status"], "Completed")

	def test_replaying_a_batch_creates_nothing_new(self):
		"""Gate 0, criterion 3. The single most important behaviour in the sync layer."""
		records = self._records(20)
		batch_uuid = self.uid("T")

		first = sync_service.push("Administrator", self.device, batch_uuid, records)
		self.assertEqual(first["accepted"], 20)

		uuids = [r["client_uuid"] for r in records]
		after_first = frappe.db.count(TARGET, {"client_uuid": ["in", uuids]})
		self.assertEqual(after_first, 20)

		# Push the identical batch twice more, as a flaky connection would.
		second = sync_service.push("Administrator", self.device, batch_uuid, records)
		third = sync_service.push("Administrator", self.device, batch_uuid, records)

		self.assertTrue(second["replayed"])
		self.assertTrue(third["replayed"])
		self.assertEqual(frappe.db.count(TARGET, {"client_uuid": ["in", uuids]}), 20)

	def test_same_records_in_a_new_batch_are_duplicates_not_creates(self):
		"""A client that loses its batch id and retries must still not double-create."""
		records = self._records(5)
		sync_service.push("Administrator", self.device, self.uid("T"), records)
		again = sync_service.push("Administrator", self.device, self.uid("T"), records)

		self.assertFalse(again["replayed"])
		self.assertEqual(again["accepted"], 5)
		statuses = {r["status"] for r in again["results"]}
		self.assertEqual(statuses, {"duplicate"})

		uuids = [r["client_uuid"] for r in records]
		self.assertEqual(frappe.db.count(TARGET, {"client_uuid": ["in", uuids]}), 5)

	def test_unregistered_doctype_is_refused(self):
		"""push takes a DocType name from a phone. The registry is the allow-list."""
		result = sync_service.push(
			"Administrator", self.device, self.uid("T"),
			[{"doctype": "ToDo", "client_uuid": self.uid("T"), "data": {"description": "no"}}],
		)
		self.assertEqual(result["accepted"], 0)
		self.assertEqual(result["results"][0]["code"], "NOT_SYNCABLE")

	def test_server_owned_fields_from_the_client_are_discarded(self):
		"""Evidence the device can edit is not evidence."""
		uuid = self.uid("T")
		sync_service.push(
			"Administrator", self.device, self.uid("T"),
			[{"doctype": TARGET, "client_uuid": uuid,
			  "data": {"conflict_type": "Duplicate", "status": "Open",
			           "resolved_by": "Administrator", "resolved_on": "2020-01-01 00:00:00"}}],
		)
		name = frappe.db.get_value(TARGET, {"client_uuid": uuid}, "name")
		self.assertIsNone(frappe.db.get_value(TARGET, name, "resolved_by"))

	def test_bad_record_is_rejected_without_killing_the_batch(self):
		records = [*self._records(2), {"doctype": TARGET}]
		result = sync_service.push("Administrator", self.device, self.uid("T"), records)
		self.assertEqual(result["accepted"], 2)
		self.assertEqual(result["rejected"], 1)
		self.assertEqual(result["status"], "Partial")

	def test_oversized_batch_is_refused(self):
		with self.assertRaises(ValueError):
			sync_service.push(
				"Administrator", self.device, self.uid("T"),
				self._records(sync_service.MAX_BATCH_SIZE + 1),
			)

	def test_validation_failure_becomes_a_conflict_not_a_loss(self):
		"""What a rep captured is kept verbatim even when it cannot be applied."""
		uuid = self.uid("T")
		result = sync_service.push(
			"Administrator", self.device, self.uid("T"),
			[{"doctype": TARGET, "client_uuid": uuid,
			  "data": {"conflict_type": "Duplicate", "status": "Resolved"}}],
		)
		self.assertEqual(result["conflicts"], 1)
		conflict_name = result["results"][0]["conflict"]
		self.track("FieldMate Sync Conflict", conflict_name)
		payload = frappe.db.get_value("FieldMate Sync Conflict", conflict_name, "client_payload")
		self.assertIn("Resolved", payload)


class TestSyncPull(FieldMateTestCase):
	def test_pull_returns_a_watermark(self):
		result = sync_service.pull("Administrator")
		self.assertIn("watermark", result)
		self.assertIn("changes", result)

	def test_pull_only_returns_registered_doctypes(self):
		result = sync_service.pull("Administrator")
		registered = {e.doctype for e in registry.pullable()}
		self.assertTrue(set(result["changes"].keys()).issubset(registered))
