from frappe.model.document import Document


class FieldMateCatalogueUOM(Document):
	"""One unit a catalogue is willing to take orders in.

	Rows of the `uoms` Table MultiSelect on `FieldMate Product Catalogue`. It lives on the
	catalogue header rather than on each item row: a Table MultiSelect inside a child table is
	accepted by Frappe's DocType validator and then **stores nothing at all** - checked against a
	real save, twice, and the grandchild table comes back empty with no error anywhere. Per-item
	narrowing through that shape would have looked like it worked and quietly lost every tick.
	"""
