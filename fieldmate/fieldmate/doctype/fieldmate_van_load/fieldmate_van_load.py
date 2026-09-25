import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class FieldMateVanLoad(Document):
	"""What went out on the vehicle this morning, and whose it is.

	The stock in a van belongs to the **distributor** (ADR-024). We sold it to them at primary
	billing and it is theirs; the rep collects it from their godown and carries it. So nothing
	here writes a Stock Entry, touches a Warehouse, or reaches the Stock Ledger. This document
	exists for operational control — what went out, what came back, what is missing — and for
	one other thing: it is the **opening stock** the day's settlement is measured against.

	The storekeeper loads the van and the rep counts it. Those two numbers are both kept, because
	the interesting case is when they disagree.
	"""

	def validate(self):
		self.roll_up()
		self.check_variance_is_explained()

	def roll_up(self):
		total_qty = value = skus = differing = 0
		for row in self.items or []:
			row.conversion_factor = flt(row.conversion_factor) or 1
			# The rep's count is what is in the van. The godown's figure is what was supposed to
			# be, and survives beside it rather than being overwritten - a load sheet nobody can
			# disagree with is a load sheet nobody checks.
			if row.counted_qty in (None, ""):
				row.counted_qty = flt(row.godown_qty)
			row.variance = flt(row.counted_qty) - flt(row.godown_qty)
			row.is_adjusted = 1 if row.variance else 0
			row.amount = flt(row.counted_qty) * flt(row.rate)

			if flt(row.counted_qty):
				skus += 1
			total_qty += flt(row.counted_qty)
			value += flt(row.amount)
			if row.variance:
				differing += 1

		self.total_skus = skus
		self.total_qty = total_qty
		self.stock_value = value
		self.variance_skus = differing
		self.has_variance = 1 if differing else 0

	def check_variance_is_explained(self):
		"""A difference accepted without a word is how stock loss becomes invisible.

		Refused here rather than warned about, because this is the one moment somebody still
		remembers why the count was different. By settlement time it is a number nobody can
		account for.
		"""
		if self.has_variance and not (self.variance_note or "").strip():
			differing = ", ".join(
				f"{row.item_code} (sheet {flt(row.godown_qty):g}, counted {flt(row.counted_qty):g})"
				for row in self.items or [] if row.variance
			)
			frappe.throw(
				frappe._("Your count differs from the load sheet on {0}. Say why before "
				         "confirming the load — nobody will remember this evening.").format(differing)
			)

	def on_submit(self):
		self.db_set("load_status", "Confirmed", update_modified=False)

	def on_cancel(self):
		self.db_set("load_status", "Cancelled", update_modified=False)

	def loaded_by_item(self) -> dict:
		"""Base units per item, as the settlement will read them."""
		return {row.item_code: flt(row.counted_qty) for row in self.items or []}
