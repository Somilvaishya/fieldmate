import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class FieldMateOrderApprovalRule(Document):
	"""Which orders stop for somebody to look at, and who that somebody is.

	Nothing here refuses an order in the market. The rep books it, reads the total back to the
	shopkeeper and walks to the next shop; the rule only decides what lands in an approval queue
	afterwards. That bargain holds only while the queue stays small enough to be read, which is
	what the validation below is really protecting.
	"""

	def validate(self):
		self.assert_has_a_trigger()
		self.assert_thresholds_are_meaningful()
		self.assert_has_an_approver()

	def assert_has_a_trigger(self):
		"""A rule with no trigger matches every order in its scope.

		That is the failure nobody notices: the queue fills with ordinary orders, the approver
		starts clearing it in bulk without reading, and the one genuine credit breach in there
		goes through with everything else.
		"""
		if self.any_trigger_set():
			return
		frappe.throw(
			frappe._("Set at least one trigger. A rule with none matches every order in its "
			         "scope, and a queue holding everything gets approved without being read.")
		)

	def any_trigger_set(self) -> bool:
		return bool(
			cint(self.check_order_value)
			or cint(self.check_discount_percent)
			or cint(self.on_credit_breach)
		)

	def assert_thresholds_are_meaningful(self):
		"""A switched-on threshold of zero is the same trap wearing a different hat.

		The switch exists because Frappe stores Currency and Float as NOT NULL DEFAULT 0, so
		an untouched threshold and a deliberate zero are one stored value. Having asked for the
		switch, refusing zero behind it is what makes the switch mean anything.
		"""
		if cint(self.check_order_value) and flt(self.min_order_value) <= 0:
			frappe.throw(
				frappe._("Order value threshold must be above zero, or the rule catches every "
				         "order rather than the large ones.")
			)

		if cint(self.check_discount_percent) and flt(self.max_discount_percent) <= 0:
			frappe.throw(
				frappe._("Discount ceiling must be above zero, or every order with any scheme "
				         "on it needs approval.")
			)

	def assert_has_an_approver(self):
		# An order routed to nobody is an order that never gets delivered, and the rep finds out
		# a week later from the shopkeeper rather than from us.
		if self.approver_role or self.approver_user:
			return
		frappe.throw(
			frappe._("Name an approver role or an approver. An order this rule stops and sends "
			         "to nobody is an order that quietly never ships.")
		)
