import frappe
from frappe.model.document import Document
from frappe.utils import flt


class FieldMateIncentivePayout(Document):
	"""What one rep earned under one scheme in one period.

	Submittable, unlike the achievement it was computed from. The achievement is what was true
	last night and will say something else tomorrow; this is a decision, and once it is taken
	the number must stop moving. That is the whole difference between the two documents.

	Nothing here computes anything. `services/incentive.py` does the arithmetic, in integer
	paise, so that Gate 7 criterion 3 - three reps matching a hand-built spreadsheet to the
	rupee - is a question about one function rather than about a controller.
	"""

	def validate(self):
		self.resolve_employee()
		self.check_amount()

	def resolve_employee(self):
		if not self.employee and self.field_user:
			self.employee = frappe.db.get_value("FieldMate Field User", self.field_user,
			                                    "employee")

	def check_amount(self):
		if flt(self.payout_amount) < 0:
			frappe.throw(frappe._("A payout cannot be negative. Nobody owes us for a bad month."))

	def before_submit(self):
		if self.payout_status in ("Draft", ""):
			self.payout_status = "Pending Approval"

	def on_cancel(self):
		if self.payout_status == "Paid":
			frappe.throw(
				frappe._("This payout is marked paid on {0}. Reverse the payment before "
				         "cancelling the record of it.").format(self.payment_reference
				                                                or self.paid_on))
		self.db_set("payout_status", "Cancelled", update_modified=False)
