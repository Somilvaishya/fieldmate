import frappe
from frappe.model.document import Document

from fieldmate import compat


class FieldMateDistributorProfile(Document):
	def validate(self):
		if self.status == "Active" and not frappe.db.get_value("Customer", self.customer, "name"):
			frappe.throw(frappe._("Customer {0} no longer exists.").format(self.customer))
		if not self.onboarding_date:
			self.onboarding_date = frappe.utils.today()

	def refresh_outstanding(self) -> float:
		"""Read from the ledger on demand. Stored only as a display value, never as truth."""
		company = frappe.defaults.get_user_default("Company") or frappe.db.get_value("Company", {}, "name")
		amount = compat.get_outstanding(self.customer, company) if company else 0
		self.db_set("outstanding_amount", amount, update_modified=False)
		return amount
