from frappe.model.document import Document


class FieldMateSchemeScope(Document):
	"""One place a scheme reaches, or one place it is kept out of.

	No rows at all means everywhere. Territory is matched down the tree rather than by name, which
	is what keeps that promise honest: Frappe fills an empty Territory link from the session
	defaults of whoever opened the form, so a row nobody scoped arrives pinned to the root, and only
	a tree match reads the root as the ancestor of everything rather than as one node that matches
	almost nothing. Checklist templates vanished that way once, with no error anywhere to explain
	it.
	"""
