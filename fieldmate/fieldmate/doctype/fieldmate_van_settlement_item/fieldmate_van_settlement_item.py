from frappe.model.document import Document


class FieldMateVanSettlementItem(Document):
	"""One SKU reconciled at the end of a van day.

	loaded - sold - returned = short. Only `returned` is the rep's to enter; the other two are
	read from the morning's load and from their own submitted orders.
	"""
