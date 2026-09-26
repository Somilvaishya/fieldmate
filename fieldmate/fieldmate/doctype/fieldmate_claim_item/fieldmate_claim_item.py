from frappe.model.document import Document


class FieldMateClaimItem(Document):
	"""One accrued benefit, carried into a claim exactly as it was recorded.

	Every column here is read-only and copied from the Scheme Ledger by the parent. Nothing on
	this row is the distributor's own figure, which is what makes the reconciliation check on the
	parent mean anything.
	"""
