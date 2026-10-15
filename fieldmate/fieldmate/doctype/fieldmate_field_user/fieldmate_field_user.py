import frappe
from frappe.model.document import Document

from fieldmate.services import field_user as svc
from fieldmate.services import settings as settings_service

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
		self.fill_from_masters()
		self.validate_user_is_usable()
		self.validate_reporting_line()

	def fill_from_masters(self):
		"""Take what the masters already know, so an admin does not type it twice."""
		self.fill_mobile_no()
		self.fill_company()

	def fill_mobile_no(self):
		"""The login first, then the Employee - and never over something typed here.

		Two sources, which is why this is not a `fetch_from`: a FieldMate login is often created
		just to sign in and carries no number at all, while the HR record almost always has one,
		and on a site running without HR it is the other way round.

		**Only a blank is filled.** A plain `fetch_from` overwrites on every save - checked
		against a real save, not assumed - so a rep whose work phone is neither of those numbers
		would have had the admin's correction wiped each time anybody opened the record and
		saved it. That is worse than the field they fill in today.
		"""
		if self.mobile_no:
			return

		for doctype, name, field in (
			("User", self.user, "mobile_no"),
			("User", self.user, "phone"),
			("Employee", self.employee, "cell_number"),
		):
			if not name:
				continue
			found = frappe.db.get_value(doctype, name, field)
			if found:
				self.mobile_no = found
				return

	def fill_company(self):
		"""The Employee's company wins; otherwise the default company.

		Unlike the mobile number this **overwrites**, on every save, and that is deliberate: HR
		owns which company somebody is employed by, so a rep whose Employee record moves follows
		it rather than being left behind pointing at the old one.

		The cost of that is stated on the field: while an Employee is linked, a company chosen by
		hand here does not survive the next save. There is no way to tell "the admin meant this"
		from "the session filled it in" - Frappe sets a Link like this one from the session
		default during insert, which is also why `fetch_from` with `fetch_if_empty` was no use
		here: the field is never empty by the time a fetch would run. An admin who needs a
		company other than the employee's clears the Employee link.

		The fallback only applies with no Employee, and only to a blank: FieldMate Settings'
		own default company first, then Frappe's. On most sites the session default has already
		filled it and neither is reached.
		"""
		if self.employee:
			employed_by = frappe.db.get_value("Employee", self.employee, "company")
			if employed_by:
				self.company = employed_by
				return

		if self.company:
			return

		self.company = (settings_service.value("default_company")
		                or frappe.db.get_default("company"))

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

	def on_update(self):
		svc.sync_territory_permission(self)

	def on_trash(self):
		svc.clear_territory_permission(self.user)
