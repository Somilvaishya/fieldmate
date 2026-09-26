from frappe.model.document import Document


class FieldMateIncentiveSlab(Document):
	"""One band of achievement and what it pays.

	Bands are inclusive at the bottom and exclusive at the top. A rep at exactly 80% lands in the
	80 slab and in no other, which is the one boundary every incentive argument is about.
	"""
