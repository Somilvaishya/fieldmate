import frappe
from frappe.model.document import Document

from fieldmate.services import field_user as svc

FIELDMATE_ROLES = (
	"FieldMate Field Rep",
	"FieldMate Area Manager",
	"FieldMate Regional Manager",
	"FieldMate Sales Head",
	"FieldMate Admin",
	"FieldMate Distributor",
)


class FieldMateFieldUser(Document):
	def validate(self):
		self.validate_user_is_usable()
		self.validate_reporting_line()
		self.validate_van_sales()

	def validate_user_is_usable(self):
		if not frappe.db.get_value("User", self.user, "enabled"):
			frappe.throw(frappe._("{0} is disabled. Enable the login first.").format(self.user))

		roles = set(frappe.get_roles(self.user))
		if not roles.intersection(FIELDMATE_ROLES):
			frappe.throw(
				frappe._("{0} holds no FieldMate role, so they could not sign in to the app. "
				         "Assign a role on the User first.").format(self.user)
			)

	def validate_reporting_line(self):
		"""A cycle here would hang every roll-up that walks the chain."""
		if not self.reports_to:
			return
		if self.reports_to == self.name:
			frappe.throw(frappe._("A field user cannot report to themselves."))

		seen, current = {self.name}, self.reports_to
		while current:
			if current in seen:
				frappe.throw(frappe._("Reporting line loops back on itself at {0}.").format(current))
			seen.add(current)
			current = frappe.db.get_value("FieldMate Field User", current, "reports_to")

	def validate_van_sales(self):
		if self.sales_mode == "Van Sales" and not self.vehicle_warehouse:
			frappe.throw(
				frappe._("A van sales rep needs a Vehicle Warehouse. Stock has to come out of "
				         "somewhere and be settled back at day end.")
			)

	def on_update(self):
		svc.sync_territory_permission(self)

	def on_trash(self):
		svc.clear_territory_permission(self.user)
