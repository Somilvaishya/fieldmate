import frappe
from frappe.model.document import Document
from frappe.utils import flt, today


class FieldMateSchemeLedger(Document):
	"""One benefit actually granted, in rupees, against one order at one shop.

	Budget consumption and distributor claims are the same fact counted twice, and this is the row
	both of them count. Without it, a manager asking where a scheme's money went has a total and no
	evidence, and a distributor asking to be paid back for stock he handed over has a memory.

	No field role creates or writes this. The server accrues it when an order is submitted and
	elevates that write itself, because a rep who could touch a ledger row could pay himself an
	incentive - the same reason no field role posts to the accounting ledger either.
	"""

	def validate(self):
		if not self.posting_date:
			self.posting_date = today()
		if not self.currency and self.company:
			self.currency = frappe.db.get_value("Company", self.company, "default_currency")

		if flt(self.benefit_amount) < 0:
			frappe.throw(
				frappe._("A benefit cannot be worth less than nothing. Reverse the accrual by "
				         "setting its status to Reversed, which leaves the original row where the "
				         "claim can still see it.")
			)

		if self.status == "Settled" and not self.settled_on:
			frappe.throw(
				frappe._("Record the date the money moved. A settled claim with no date is the "
				         "first thing anybody disputes at month end.")
			)

	def on_cancel(self):
		"""Give the budget back, whoever cancelled this row and however they reached it.

		This used to live only in `order.reverse()`, which walks the rows still at docstatus 1
		and refunds each one. That works when an order is cancelled through the service, and not
		otherwise: a submitted ledger row links to the order, so Desk cancels the linked row
		first to get the back-link out of the way. By the time the order's `on_cancel` ran there
		were no docstatus 1 rows left to find, the refund never happened, and the scheme went on
		reporting a budget it had been given back - with the row beside it still labelled
		Accrued.

		Here the accrual and its undoing sit on the same document, so they cannot come apart.
		"""
		self.db_set("status", "Reversed", update_modified=False)

		# The same function that charges it, so the accrual and the refund can never drift into
		# two different ideas of the arithmetic. It updates in SQL, so two cancellations at once
		# do not lose one of the refunds.
		from fieldmate.services.order import _consume_budget

		_consume_budget(self.scheme, -flt(self.benefit_amount))
