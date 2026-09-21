import frappe
from frappe.model.document import Document
from frappe.utils import flt

from fieldmate.fieldmate.doctype.fieldmate_product_catalogue.fieldmate_product_catalogue import (
	validate_period,
	validate_unique_items,
)


class FieldMateMustSellList(Document):
	def validate(self):
		validate_period(self)
		validate_unique_items(self, "item_code")
		self.item_count = len(self.items or [])

		if self.is_active and not self.items:
			frappe.throw(
				frappe._("An active must-sell list needs at least one item, or compliance "
				         "scores against nothing and always reads 100%.")
			)

		for row in self.items or []:
			if flt(row.weightage) <= 0:
				frappe.throw(
					frappe._("Row {0}: Weight must be above zero, or the line cannot affect "
					         "the score.").format(row.idx)
				)

	def total_weight(self) -> float:
		return flt(sum(flt(r.weightage) for r in self.items or []))
