import frappe
from frappe.model.document import Document
from frappe.utils import getdate


class FieldMateProductCatalogue(Document):
	def validate(self):
		validate_period(self)
		validate_unique_items(self, "item_code")
		self.item_count = len(self.items or [])
		for row in self.items or []:
			if row.max_order_qty and row.min_order_qty and row.max_order_qty < row.min_order_qty:
				frappe.throw(
					frappe._("Row {0}: Max Qty cannot be below Min Qty.").format(row.idx)
				)

	def is_current(self, on=None) -> bool:
		on = getdate(on or frappe.utils.today())
		if not self.is_active:
			return False
		if self.valid_from and on < getdate(self.valid_from):
			return False
		if self.valid_to and on > getdate(self.valid_to):
			return False
		return True


def validate_period(doc) -> None:
	if doc.valid_from and doc.valid_to and getdate(doc.valid_to) < getdate(doc.valid_from):
		frappe.throw(frappe._("Valid To cannot be before Valid From."))


def validate_unique_items(doc, fieldname: str) -> None:
	seen = set()
	for row in doc.items or []:
		value = row.get(fieldname)
		if value in seen:
			frappe.throw(
				frappe._("Row {0}: {1} is listed twice.").format(row.idx, value)
			)
		seen.add(value)
