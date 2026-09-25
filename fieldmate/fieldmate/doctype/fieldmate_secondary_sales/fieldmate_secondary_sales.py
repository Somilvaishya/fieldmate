import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate


class FieldMateSecondarySales(Document):
	"""What a distributor sold on to shops, as they reported it.

	These are the distributor's own sales. We were never a party to them and nothing here
	reaches our books (ADR-023) — this is measurement, and Gate 5 asks explicitly that no
	secondary sales document produces a GL Entry.

	It arrives as a file, so most of the work is in `services/secondary_sales.py`. What the
	document itself owes is the arithmetic and one piece of honesty: how many rows were read,
	how many were rejected, and why each one was. A file that imports 340 of 347 rows and says
	nothing about the other 7 is worse than one that fails outright, because nobody goes looking.
	"""

	def validate(self):
		self.check_period()
		self.normalise_lines()
		self.roll_up()

	def check_period(self):
		if getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(frappe._("The period ends before it starts."))

	def normalise_lines(self):
		for row in self.items or []:
			row.conversion_factor = flt(row.conversion_factor) or 1
			row.base_qty = flt(row.qty) * flt(row.conversion_factor)

	def roll_up(self):
		lines = self.items or []
		self.total_lines = len(lines)
		self.total_qty = sum(flt(row.base_qty) for row in lines)
		self.total_amount = sum(flt(row.amount) for row in lines)
		self.matched_outlets = len({row.outlet for row in lines if row.outlet})
