import frappe
from frappe.tests.utils import FrappeTestCase


class FieldMateTestCase(FrappeTestCase):
	"""Shared fixture hygiene.

	FrappeTestCase rolls back per CLASS, not per method, so records leak between tests in the
	same class. Everything here is therefore named uniquely per test and deleted explicitly -
	never relying on rollback between methods.
	"""

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
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			except frappe.DoesNotExistError:
				pass
		frappe.db.commit()
		super().tearDown()
