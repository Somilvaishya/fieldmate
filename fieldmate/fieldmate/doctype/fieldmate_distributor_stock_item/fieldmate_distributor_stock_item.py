from frappe.model.document import Document


class FieldMateDistributorStockItem(Document):
	"""One SKU's movement through a distributor for a period.

	opening + primary - closing = secondary. The identity is computed on the parent; this row
	holds the four figures it is computed from, plus whatever the distributor reported
	themselves so the two can be compared.
	"""
