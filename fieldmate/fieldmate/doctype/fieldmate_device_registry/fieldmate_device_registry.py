import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class FieldMateDeviceRegistry(Document):
	def before_insert(self):
		self.registered_on = now_datetime()

	def on_update(self):
		# A deregistered device must stop receiving pushes immediately. The PWA is
		# separately responsible for wiping its local store.
		if self.status == "Deregistered" and self.push_subscription:
			self.db_set("push_subscription", None, update_modified=False)

	def touch(self, synced: bool = False) -> None:
		"""Record activity without a full save. Called on every sync request."""
		now = now_datetime()
		self.db_set("last_seen_on", now, update_modified=False)
		if synced:
			self.db_set("last_sync_on", now, update_modified=False)

	def assert_active(self) -> None:
		if self.status != "Active":
			frappe.throw(
				frappe._("This device is no longer active. Sign in again to continue."),
				frappe.PermissionError,
			)
