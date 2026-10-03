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


class TestEveryControllerImports(FieldMateTestCase):
	"""`bench migrate` DELETES a DocType whose controller will not import.

	`frappe/model/sync.py::remove_orphan_doctypes` calls `get_controller()` on every non-custom
	DocType and deletes the ones that raise ImportError. Despite the name it checks nothing about
	whether a child table is referenced anywhere - the only thing it tests is the import.

	So a controller class named `FieldmateVisitTask` instead of `FieldMateVisitTask` is enough
	to have the DocType removed. That happened here: five Phase 5 child tables were deleted on
	their first migrate, the log said "Orphaned DocType(s) found" and named no cause, and the
	migration otherwise succeeded. Data is left behind but the DocType is gone.

	This test is the guard. It is cheap, it needs no database, and it fails on the bench rather
	than on somebody's site.
	"""

	def doctype_files(self):
		import glob
		import os

		import fieldmate

		root = os.path.join(os.path.dirname(fieldmate.__file__), "fieldmate", "doctype")
		for folder in sorted(glob.glob(os.path.join(root, "*"))):
			slug = os.path.basename(folder)
			schema = os.path.join(folder, slug + ".json")
			if os.path.exists(schema):
				yield slug, schema, os.path.join(folder, slug + ".py")

	def test_every_controller_class_matches_its_doctype_name(self):
		import json
		import os
		import re

		wrong = []
		for slug, schema, controller in self.doctype_files():
			name = json.load(open(schema, encoding="utf-8"))["name"]
			expected = name.replace(" ", "")
			if not os.path.exists(controller):
				wrong.append(f"{name}: no {slug}.py at all")
				continue
			source = open(controller, encoding="utf-8").read()
			found = re.search(r"^class (\w+)\(", source, re.M)
			if not found:
				wrong.append(f"{name}: {slug}.py declares no class")
			elif found.group(1) != expected:
				wrong.append(f"{name}: class is {found.group(1)}, must be {expected}")

		self.assertEqual(wrong, [], "migrate will delete these:\n  " + "\n  ".join(wrong))

	def test_frappe_can_actually_load_every_one_of_them(self):
		"""The same question asked the way migrate asks it, rather than by reading the file."""
		from frappe.model.base_document import get_controller

		broken = []
		for _slug, schema, _ in self.doctype_files():
			import json
			name = json.load(open(schema, encoding="utf-8"))["name"]
			try:
				get_controller(name)
			except ImportError as e:
				broken.append(f"{name}: {e}")

		self.assertEqual(broken, [], "migrate would delete these:\n  " + "\n  ".join(broken))
