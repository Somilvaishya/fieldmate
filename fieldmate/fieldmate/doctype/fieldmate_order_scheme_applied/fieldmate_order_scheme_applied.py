from frappe.model.document import Document


class FieldMateOrderSchemeApplied(Document):
	"""One benefit that a scheme actually granted on one order.

	This is the audit trail behind a number the rep already promised at the counter. It records
	not just what the benefit was worth but which slab produced it and what value it was measured
	against, because a scheme dispute weeks later is almost never about the arithmetic - it is
	about which slab the cart reached and what counted towards it.

	Every row is written by the server after it has re-evaluated the cart. A phone proposes an
	offer; this table records the one the server stands behind.
	"""
