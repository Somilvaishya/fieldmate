import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, today


class FieldMateGeoFenceException(Document):
	def validate(self):
		if not self.exception_date:
			self.exception_date = today()

		outlet = frappe.get_doc("FieldMate Outlet", self.outlet)
		radius = outlet.effective_geo_fence_radius()
		if flt(self.distance_m) <= radius:
			# Inside the fence there is nothing to excuse, and an approval trail full of
			# non-exceptions is one nobody reads.
			frappe.throw(
				frappe._("This check-in was {0} m from the shop, inside its {1} m fence. "
				         "No exception is needed.").format(flt(self.distance_m), radius)
			)

	def before_submit(self):
		if self.status == "Pending":
			frappe.throw(frappe._("Approve or reject this exception before submitting it."))
		self.approved_by = frappe.session.user
		self.decided_on = now_datetime()
