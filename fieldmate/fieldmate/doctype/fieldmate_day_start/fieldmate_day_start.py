import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate


class FieldMateDayStart(Document):
	def validate(self):
		self.store_selfie()
		if self.latitude or self.longitude:
			if not (-90 <= flt(self.latitude) <= 90):
				frappe.throw(frappe._("Latitude must be between -90 and 90."))
			if not (-180 <= flt(self.longitude) <= 180):
				frappe.throw(frappe._("Longitude must be between -180 and 180."))

		if getdate(self.day_date) > getdate(frappe.utils.today()):
			frappe.throw(frappe._("A day cannot be started in the future."))

	def store_selfie(self):
		"""Turn a camera capture into a File, and keep the path.

		`selfie` is an Attach Image: varchar(140) holding a path, not bytes. day_service.start
		already converts it, but a day captured offline arrives through the sync queue, which
		inserts the document directly and never touches that service. This is the same trap
		the shopfront photo and the visit photos each hit in turn.
		"""
		from fieldmate.services import files as file_service
		from fieldmate.services import settings as settings_service

		if not file_service.is_data_url(self.selfie):
			return
		self.selfie = file_service.attach_photo(
			self.selfie, filename=f"selfie-{self.name}",
			doctype=self.doctype, name=self.name, fieldname="selfie",
			max_kb=settings_service.value("photo_max_kb"),
		)

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
