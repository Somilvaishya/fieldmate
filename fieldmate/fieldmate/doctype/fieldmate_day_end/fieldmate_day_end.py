import frappe
from frappe.model.document import Document
from frappe.utils import flt, get_datetime, getdate, now_datetime, time_diff_in_hours


class FieldMateDayEnd(Document):
	"""The close of a working day.

	What the day produced is counted here, from the records, rather than taken from the
	phone. `day_service.end()` does the same thing on the online path - but a day captured
	with no signal arrives through the sync queue, which inserts the document directly and
	never touches that service. Without this the offline day would land with every figure
	at zero, which reads as a wasted day rather than a synced one.
	"""

	def validate(self):
		self.fill_from_the_day()
		self.count_what_happened()

	def fill_from_the_day(self):
		if not self.day_start:
			return
		start = frappe.db.get_value(
			"FieldMate Day Start", self.day_start,
			["field_user", "day_date", "start_time"], as_dict=True,
		)
		if not start:
			return
		self.field_user = self.field_user or start.field_user
		self.day_date = self.day_date or start.day_date
		if not self.end_time:
			self.end_time = now_datetime()
		self.duration_hours = round(
			flt(time_diff_in_hours(get_datetime(self.end_time), get_datetime(start.start_time))), 2
		)

	def on_submit(self):
		"""Close the day this ends.

		`day_service.end()` does this on the online path. A day closed offline arrives through
		the sync queue, which never calls that service - so without this the Day Start stayed
		Open, the rep could not start the next day, and `auto_close_stale_days` eventually
		marked it "Auto Closed", which reports as a day the rep forgot to finish.
		"""
		if not self.day_start:
			return
		if frappe.db.get_value("FieldMate Day Start", self.day_start, "status") == "Open":
			frappe.db.set_value("FieldMate Day Start", self.day_start, "status", "Closed",
			                    update_modified=False)

	def count_what_happened(self):
		if not (self.field_user and self.day_date):
			return

		from fieldmate.services.day import day_counts
		from fieldmate.services.trail import distance_for

		counts = day_counts(self.field_user, getdate(self.day_date))
		for field, value in counts.items():
			if self.meta.has_field(field):
				self.set(field, value)
		self.distance_km = round(flt(distance_for(self.field_user, getdate(self.day_date))), 2)
