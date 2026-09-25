from frappe.model.document import Document


class FieldMateVanLoadItem(Document):
	"""One SKU loaded onto the vehicle.

	Both figures are kept. `godown_qty` is what the storekeeper says went in and `counted_qty`
	is what the rep found; overwriting the first with the second would make the load sheet
	something nobody can disagree with, and a sheet nobody can disagree with is a sheet
	nobody checks.
	"""
