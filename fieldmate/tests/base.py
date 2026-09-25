import frappe
from frappe.tests.utils import FrappeTestCase


class FieldMateTestCase(FrappeTestCase):
	"""Shared fixture hygiene.

	FrappeTestCase rolls back per CLASS, not per method, so records leak between tests in the
	same class. Everything here is therefore named uniquely per test and deleted explicitly -
	never relying on rollback between methods.
	"""

	def fresh_settings(self):
		"""FieldMate Settings is a Single: frappe hands back one shared instance, and a stale
		copy saved twice raises TimestampMismatchError. Every read here loads its own."""
		frappe.clear_document_cache("FieldMate Settings", "FieldMate Settings")
		doc = frappe.get_single("FieldMate Settings")
		doc.flags.ignore_permissions = True
		return doc

	def apply_settings(self, **values):
		"""Change settings and drop the cache, which is the half everybody forgets.

		`services/settings.get()` reads through `frappe.cache()`, so a test that writes with
		`frappe.db.set_single_value` changes the row and nothing else - the service keeps
		answering with the old value and the test fails somewhere unrelated. Lives here rather
		than on one fixture because three test files have now needed it.
		"""
		doc = self.fresh_settings()
		for key, value in values.items():
			doc.set(key, value)
		doc.save()
		frappe.cache().delete_value("fieldmate_settings")
		return doc

	def uid(self, prefix: str = "T") -> str:
		return f"{prefix}-{frappe.generate_hash(length=10)}"

	def track(self, doctype: str, name: str) -> str:
		self._created.append((doctype, name))
		return name

	def setUp(self):
		super().setUp()
		self._created = []

	def tearDown(self):
		for doctype, name in reversed(self._created):
			try:
				# A submitted document refuses deletion until it is cancelled. Without this
				# every submittable doctype leaks fixtures into the next test.
				if frappe.get_meta(doctype).is_submittable:
					docstatus = frappe.db.get_value(doctype, name, "docstatus")
					if docstatus == 1:
						doc = frappe.get_doc(doctype, name)
						doc.flags.ignore_permissions = True
						doc.cancel()
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			except frappe.DoesNotExistError:
				pass
		frappe.db.commit()
		super().tearDown()
