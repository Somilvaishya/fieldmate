import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime, today

from fieldmate.services import field_user as field_user_service
from fieldmate.services import settings as settings_service


class FieldMateOutlet(Document):
	def before_insert(self):
		self.onboarding_date = self.onboarding_date or today()
		if not self.created_by_rep:
			self.created_by_rep = field_user_service.for_user()

		# A shop a rep adds in the field is unapproved until a manager says otherwise, whatever
		# the payload claimed. Trusting the client here would make approval decorative.
		if self.created_by_rep and frappe.session.user != "Administrator":
			self.approval_status = "Pending Approval"

	def validate(self):
		self.validate_geo()
		self.validate_billing()
		self.validate_contacts()

	def validate_geo(self):
		if self.latitude or self.longitude:
			if not (-90 <= flt(self.latitude) <= 90):
				frappe.throw(frappe._("Latitude must be between -90 and 90."))
			if not (-180 <= flt(self.longitude) <= 180):
				frappe.throw(frappe._("Longitude must be between -180 and 180."))
			if not self.geo_captured_on:
				self.geo_captured_on = now_datetime()

		if self.geo_fence_radius_m and not (10 <= self.geo_fence_radius_m <= 5000):
			frappe.throw(frappe._("Geo Fence Radius must be between 10 and 5000 metres."))

	def validate_billing(self):
		"""The shop is only a billing party in van sales (ADR-013, amended by ADR-016)."""
		if not self.customer:
			return
		if "Van Sales" not in settings_service.enabled_modes():
			frappe.throw(
				frappe._("This outlet has a Customer set, which only applies to van sales. "
				         "Enable van sales in FieldMate Settings, or clear the Customer.")
			)

	def validate_contacts(self):
		primaries = [c for c in (self.contacts or []) if c.is_primary]
		if len(primaries) > 1:
			frappe.throw(frappe._("Only one contact can be the primary."))

	def on_update(self):
		if self.has_value_changed("approval_status"):
			if self.approval_status == "Approved" and not self.approved_by:
				self.db_set("approved_by", frappe.session.user, update_modified=False)
			elif self.approval_status != "Approved" and self.approved_by:
				self.db_set("approved_by", None, update_modified=False)

	# ------------------------------------------------------------------ helpers

	def effective_geo_fence_radius(self) -> int:
		return int(self.geo_fence_radius_m or settings_service.value("default_geo_fence_radius_m"))

	def can_take_order(self) -> tuple[bool, str]:
		"""Visitable is not the same as sellable."""
		if self.approval_status != "Approved":
			return False, frappe._("This shop is waiting for approval. You can visit it, but not book an order yet.")
		if self.outlet_status != "Active":
			return False, frappe._("This shop is marked {0}.").format(self.outlet_status)
		return True, ""

	def billing_party(self) -> str | None:
		"""Who the money is owed by. The whole order and collection path hangs off this."""
		if settings_service.is_van_sales(field_user_service.for_user()):
			return self.customer or None
		return self.distributor
