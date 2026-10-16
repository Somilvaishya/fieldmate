import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate


class FieldMateDay(Document):
	"""A rep's working day, from the moment it opens to the moment it closes.

	One document, submitted when the day opens, with `status` carrying the lifecycle. The
	closing fields are `allow_on_submit`, so the end of the day is a legitimate update to the
	record of that day rather than a second document pointing at it.

	Everything the day produced is counted here, from the records, never taken from the phone -
	a handset that spent the day with no signal cannot know which of its orders finally landed,
	and a day that reports the phone's count is the figure a rep argues about at month end.
	"""

	def validate(self):
		self.store_selfie()
		self.check_coordinates()

		if getdate(self.day_date) > getdate(frappe.utils.today()):
			frappe.throw(frappe._("A day cannot be started in the future."))

	def check_coordinates(self):
		"""Both ends of the day, each named, because they are different places.

		The old pair of documents each had a bare `latitude` and each checked only its own, so
		this reads as one rule where there were two identical ones.
		"""
		for lat, lon, where in (
			(self.start_latitude, self.start_longitude, frappe._("start")),
			(self.end_latitude, self.end_longitude, frappe._("end")),
		):
			if not (lat or lon):
				continue
			if not (-90 <= flt(lat) <= 90):
				frappe.throw(
					frappe._("The {0} latitude must be between -90 and 90.").format(where)
				)
			if not (-180 <= flt(lon) <= 180):
				frappe.throw(
					frappe._("The {0} longitude must be between -180 and 180.").format(where)
				)

	def store_selfie(self):
		"""Turn a camera capture into a File, and keep the path.

		`selfie` is an Attach Image: varchar(140) holding a path, not bytes. `day_service.start`
		already converts it, but a day captured offline arrives through the sync queue, which
		inserts the document directly and never touches that service. This is the same trap the
		shopfront photo and the visit photos each hit in turn.
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
			"FieldMate Day",
			{"field_user": self.field_user, "status": "Open", "docstatus": 1,
			 "name": ["!=", self.name]},
		)
		if open_day:
			frappe.throw(
				frappe._("{0} already has a day open ({1}). Close it before starting another.")
				.format(self.field_user, open_day)
			)

	def before_update_after_submit(self):
		"""Check the closing coordinates, which nothing else will.

		Frappe does not run `validate` on an update to a submitted document, and the end of the
		day arrives exactly that way - so without this the closing latitude and longitude are
		the one pair on the record that nobody checks. The old Day End did not check them
		either; this is the first thing that does.
		"""
		self.check_coordinates()

	def on_update_after_submit(self):
		"""The closing has landed, however it got here.

		This is the one hook both paths go through. `day_service.end()` fills the end fields and
		saves; a day closed with no signal arrives later as a sync update to those same fields.
		Before the merge those were an API call and a separate document insert, and each had to
		carry its own copy of the counting, the HRMS mirror and the attendance row - which is
		how the offline close came to be the one that forgot them.
		"""
		if not self.end_time or self.status != "Open":
			return

		from fieldmate.services import day as day_service

		day_service.finish(self)
