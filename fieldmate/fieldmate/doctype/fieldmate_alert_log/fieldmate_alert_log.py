from frappe.model.document import Document


class FieldMateAlertLog(Document):
	"""One exception, noticed once.

	`occurrence_key` is rule + rep + day and carries a unique index, so the same occurrence
	cannot be logged twice however often the job runs. Gate 8 criterion 5 asks that each rule
	fires exactly once per occurrence, and the database enforces it rather than a caller
	remembering to check first.

	Append-only. An alert that was withdrawn still happened.
	"""
