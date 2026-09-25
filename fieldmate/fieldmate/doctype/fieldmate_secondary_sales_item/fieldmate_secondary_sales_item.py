from frappe.model.document import Document


class FieldMateSecondarySalesItem(Document):
	"""One line from a distributor's secondary sales file.

	`retailer_name` and `retailer_code` are kept exactly as they arrived even when we cannot
	match them to an outlet, because next quarter somebody will ask which shop a line was
	for and the file will be gone. `source_row` points back at the row it came from.
	"""
