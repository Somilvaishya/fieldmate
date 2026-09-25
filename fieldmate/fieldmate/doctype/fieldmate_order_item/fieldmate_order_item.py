from frappe.model.document import Document


class FieldMateOrderItem(Document):
	"""One line of a field order, carried twice over.

	Once in the rep's words - two cases, the way the shopkeeper said it - and once in base units,
	which is the only form the scheme engine and the eventual Sales Order will accept. Both are
	kept because the conversion between them is exactly where an argument at delivery starts, and
	a line that stored only the converted number cannot answer what was actually agreed.

	Every money field here is recomputed on the server. Nothing on this line is trusted from the
	device that sent it.
	"""
