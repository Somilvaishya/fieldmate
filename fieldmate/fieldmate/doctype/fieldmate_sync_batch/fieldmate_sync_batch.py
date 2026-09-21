import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime


class FieldMateSyncBatch(Document):
	def before_insert(self):
		if not self.received_on:
			self.received_on = now_datetime()

	def complete(self) -> None:
		"""Close the batch and derive its status from the counts."""
		self.completed_on = now_datetime()
		if self.received_on:
			delta = get_datetime(self.completed_on) - get_datetime(self.received_on)
			self.duration_ms = int(delta.total_seconds() * 1000)
		self.status = self.derive_status()
		self.save(ignore_permissions=True)

	def derive_status(self) -> str:
		accepted = frappe.utils.cint(self.accepted_count)
		rejected = frappe.utils.cint(self.rejected_count)
		conflicts = frappe.utils.cint(self.conflict_count)

		if accepted and not (rejected or conflicts):
			return "Completed"
		if accepted:
			# Some landed. A partial batch is normal: one bad record must never
			# block the rest of a rep's day from syncing.
			return "Partial"
		if rejected or conflicts:
			return "Failed"
		return "Completed"
