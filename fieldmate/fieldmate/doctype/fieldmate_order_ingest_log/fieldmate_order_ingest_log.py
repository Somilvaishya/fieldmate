from frappe.model.document import Document


class FieldMateOrderIngestLog(Document):
	"""Append-only: every time somebody outside our four walls moved an order.

	The order itself carries only where it stands now. Who moved it there, from what, on which
	depot invoice number and at what time is the part anybody asks about a week later, and it is
	not recoverable from a Select field holding one word.

	Nothing is written here by hand. `services.portal` appends a row for each accepted move, in
	the same call that makes the move.
	"""
