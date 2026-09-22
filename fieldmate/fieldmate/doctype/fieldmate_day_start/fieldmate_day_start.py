import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate


class FieldMateDayStart(Document):
	def validate(self):
		if self.latitude or self.longitude:
			if not (-90 <= flt(self.latitude) <= 90):
				frappe.throw(frappe._("Latitude must be between -90 and 90."))
			if not (-180 <= flt(self.longitude) <= 180):
				frappe.throw(frappe._("Longitude must be between -180 and 180."))

		if getdate(self.day_date) > getdate(frappe.utils.today()):
			frappe.throw(frappe._("A day cannot be started in the future."))

	def before_submit(self):
		# One open day per rep. Two would split the day's work across records and double-count
		# coverage for the same hours.
		open_day = frappe.db.exists(
			"FieldMate Day Start",
			{"field_user": self.field_user, "status": "Open", "docstatus": 1,
			 "name": ["!=", self.name]},
		)
		if open_day:
			frappe.throw(
				frappe._("{0} already has a day open ({1}). Close it before starting another.")
				.format(self.field_user, open_day)
			)
