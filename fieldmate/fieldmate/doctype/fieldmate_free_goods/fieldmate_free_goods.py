from frappe.model.document import Document


class FieldMateFreeGoods(Document):
	"""Something that leaves the warehouse on an order without being paid for.

	Two quite different things sit in this table and the flag between them matters. A free case of
	soap is a saleable SKU given away, and it belongs in cost but not in the slab that earned it.
	A branded shelf strip is dispatched and costs money too, but it was never a SKU at all, and
	counting it as volume inflates every offtake figure downstream of it.

	The quantities are the engine's, not the rep's. Nothing in this table is typed.
	"""
