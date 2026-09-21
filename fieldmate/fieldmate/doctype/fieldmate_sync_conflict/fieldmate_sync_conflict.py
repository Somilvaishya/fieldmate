import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class FieldMateSyncConflict(Document):
	def validate(self):
		if self.status in ("Resolved", "Discarded"):
			if not self.resolution:
				frappe.throw(
					frappe._("Choose how this conflict was resolved before closing it.")
				)
			if not self.resolved_on:
				self.resolved_on = now_datetime()
				self.resolved_by = frappe.session.user
		else:
			# Reopening clears the resolution trail rather than leaving a stale one.
			self.resolved_on = None
			self.resolved_by = None
			self.resolution = None
