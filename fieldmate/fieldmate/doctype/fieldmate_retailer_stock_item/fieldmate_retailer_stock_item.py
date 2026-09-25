from frappe.model.document import Document


class FieldMateRetailerStockItem(Document):
	"""One SKU on a shop's shelf.

	`is_counted` carries what the number cannot: a Float is never null, so a shelf counted at
	zero and a shelf nobody looked at are the same zero. They are opposite facts about the
	shop, and only one of them is a reason to push.
	"""
