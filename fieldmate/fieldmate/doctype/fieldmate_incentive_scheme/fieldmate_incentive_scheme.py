import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class FieldMateIncentiveScheme(Document):
	"""A slab table, and the rule for which achievement reads it.

	Everything a rep argues about at the end of a month is decided here, so the validations are
	about the shapes that produce an argument: two slabs that both claim 80%, a gap between 79
	and 81 that a rep can land in and earn nothing, and a table with no ceiling.
	"""

	def validate(self):
		self.check_validity()
		self.order_slabs()
		self.check_slabs_hold_apart()
		self.check_top_is_reachable()
		self.describe_scope()

	def check_validity(self):
		if self.valid_to and self.valid_from and self.valid_to < self.valid_from:
			frappe.throw(frappe._("The scheme expires before it starts."))

	def order_slabs(self):
		rows = sorted(self.slabs or [], key=lambda r: flt(r.from_pct))
		for index, row in enumerate(rows, start=1):
			row.slab_idx = index
			row.idx = index
			if row.payout_kind == "Fixed Amount" and flt(row.payout_amount) <= 0:
				frappe.throw(
					frappe._("Slab {0} pays a fixed amount of nothing.").format(index))
			if row.payout_kind == "Percent Of Value" and flt(row.payout_pct) <= 0:
				frappe.throw(
					frappe._("Slab {0} pays a percentage of nothing.").format(index))
		self.set("slabs", rows)

	def check_slabs_hold_apart(self):
		"""No overlaps, and no gaps a rep can fall into.

		The gap is the one people forget. A table of 80-100 and 110-120 leaves a rep at 105%
		earning nothing at all, and nobody discovers that until the month it happens to somebody.
		"""
		previous = None
		for row in self.slabs or []:
			if previous is not None:
				if flt(row.from_pct) < flt(previous.to_pct):
					frappe.throw(
						frappe._("Slabs {0} and {1} overlap. A rep at {2}% would be in both.")
						.format(previous.slab_idx, row.slab_idx, flt(row.from_pct)))
				if flt(row.from_pct) > flt(previous.to_pct):
					frappe.throw(
						frappe._("There is a gap between slab {0} and slab {1}. A rep landing "
						         "between {2}% and {3}% would earn nothing.")
						.format(previous.slab_idx, row.slab_idx,
						        flt(previous.to_pct), flt(row.from_pct)))
			if not cint(row.is_open_ended) and flt(row.to_pct) <= flt(row.from_pct):
				frappe.throw(
					frappe._("Slab {0} ends at or before it begins.").format(row.slab_idx))
			previous = row

	def check_top_is_reachable(self):
		if not self.slabs:
			return
		top = self.slabs[-1]
		if not cint(top.is_open_ended):
			frappe.throw(
				frappe._("The top slab stops at {0}%. Mark it open ended, or a rep who does "
				         "better than that earns nothing at all.").format(flt(top.to_pct)))
		# An open-ended slab anywhere but the top would swallow everything above it.
		for row in self.slabs[:-1]:
			if cint(row.is_open_ended):
				frappe.throw(
					frappe._("Slab {0} is open ended but is not the last one.")
					.format(row.slab_idx))

	def describe_scope(self):
		parts = []
		if self.designation:
			parts.append(self.designation)
		if self.territory:
			parts.append(f"in {self.territory} and below")
		if self.sales_person:
			parts.append(f"under {self.sales_person}")
		self.applies_note = ", ".join(parts) if parts else "Everybody"

	def slab_for(self, achievement_pct):
		"""The one slab this achievement lands in, or None below the first.

		Inclusive at the bottom, exclusive at the top, open ended on the last - the rule the
		validations above exist to keep true.
		"""
		pct = flt(achievement_pct)
		if pct < flt(self.qualifying_pct):
			return None
		for row in self.slabs or []:
			if pct < flt(row.from_pct):
				continue
			if cint(row.is_open_ended) or pct < flt(row.to_pct):
				return row
		return None
