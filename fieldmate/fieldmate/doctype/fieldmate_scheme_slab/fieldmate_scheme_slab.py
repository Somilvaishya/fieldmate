from frappe.model.document import Document


class FieldMateSchemeSlab(Document):
	"""One benefit inside one tier of a scheme.

	A tier is a slab number, not a row: several rows carrying the same number make a single slab
	that grants a combo, because an offer written as "two cases gets five percent and a free
	dangler" is one thing a rep says and two things somebody has to settle afterwards. A row per
	benefit is what lets the ledger account for each half of that separately.

	The parent enforces everything that makes these rows compilable - that slabs ascend and never
	overlap, and that a row names the same benefit its amount column carries.
	"""
