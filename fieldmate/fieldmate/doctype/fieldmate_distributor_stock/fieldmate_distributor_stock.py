import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate


class FieldMateDistributorStock(Document):
	"""A distributor's stock for a period, and the secondary sales it implies.

	The identity the whole document exists for, in the owner's own words:

	    opening + primary billing - secondary sale = closing
	    opening + primary billing - closing        = secondary sale

	Secondary sales are what the distributor sold on to shops. We never see those transactions —
	they are the distributor's own sales — so the only honest way to know the number is to count
	what went in and what is left. That is what this computes.

	A distributor who also *reports* their secondary sales gives us a second figure, and the
	difference between the two is worth more than either: a gap is either sales nobody recorded
	or stock that has gone missing, and both are a phone call.

	Nothing here posts. This is measurement, not accounting (ADR-023, ADR-024).
	"""

	def validate(self):
		self.check_period()
		self.carry_opening_forward()
		self.compute_offtake()
		self.roll_up()

	def check_period(self):
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(frappe._("The period ends before it starts."))

	def carry_opening_forward(self):
		"""This period's opening is last period's closing, wherever there was one.

		Typed independently, the two drift, and a chain of months quietly stops adding up. Only
		an opening nobody has entered is filled - an opening somebody typed deliberately is left
		alone, because a physical recount is exactly when the chain is meant to be broken.
		"""
		previous = frappe.db.get_value(
			"FieldMate Distributor Stock",
			{"distributor": self.distributor, "to_date": ["<", self.from_date], "docstatus": 1,
			 "name": ["!=", self.name or ""]},
			"name",
			order_by="to_date desc",
		)
		self.previous_stock = previous
		if not previous:
			return

		closing = {
			row.item_code: flt(row.closing_qty)
			for row in frappe.get_all(
				"FieldMate Distributor Stock Item",
				filters={"parent": previous, "parenttype": "FieldMate Distributor Stock"},
				fields=["item_code", "closing_qty"],
			)
		}
		for row in self.items or []:
			if not flt(row.opening_qty) and row.item_code in closing:
				row.opening_qty = closing[row.item_code]

	def compute_offtake(self):
		for row in self.items or []:
			row.conversion_factor = flt(row.conversion_factor) or 1
			row.secondary_qty = (
				flt(row.opening_qty) + flt(row.primary_qty) - flt(row.closing_qty)
			)
			# Only meaningful where they actually reported something. A distributor who sent no
			# file would otherwise show a variance equal to their whole month's sales.
			row.variance_qty = (
				flt(row.secondary_qty) - flt(row.reported_secondary_qty)
				if flt(row.reported_secondary_qty) else 0
			)

	def roll_up(self):
		self.total_opening = sum(flt(r.opening_qty) for r in self.items or [])
		self.total_primary = sum(flt(r.primary_qty) for r in self.items or [])
		self.total_closing = sum(flt(r.closing_qty) for r in self.items or [])
		self.total_secondary = sum(flt(r.secondary_qty) for r in self.items or [])
		self.total_variance = sum(flt(r.variance_qty) for r in self.items or [])
