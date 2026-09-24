from frappe.model.document import Document


class FieldMateSchemeItem(Document):
	"""One line of the qualifying set: a SKU, an item group or a brand.

	Managers write schemes at whichever level they think in, and the same offer is genuinely
	"Surf Excel 1kg", "Detergents" or "Surf" depending on who wrote it. The compiler flattens all
	three to base item codes before anything reaches a phone, so a row only has to record which of
	the three was meant - and the parent refuses a row naming more than one, because such a row
	cannot be read the same way twice.
	"""
