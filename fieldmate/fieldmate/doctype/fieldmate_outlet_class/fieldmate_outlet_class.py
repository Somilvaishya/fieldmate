import frappe
from frappe.model.document import Document
from frappe.utils import flt


class FieldMateOutletClass(Document):
	def validate(self):
		if self.max_monthly_potential and flt(self.max_monthly_potential) < flt(self.min_monthly_potential):
			frappe.throw(frappe._("Max Monthly Potential cannot be below the minimum."))
		if self.visits_per_month and not (1 <= self.visits_per_month <= 31):
			frappe.throw(frappe._("Visits Per Month must be between 1 and 31."))
