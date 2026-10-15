from frappe.model.document import Document


class FieldMateOutstandingSnapshot(Document):
	"""What a party owed on a given day, frozen so a trend can be read tomorrow.

	Computed nightly rather than accumulated: a snapshot that drifts from the bills behind it is
	worse than no snapshot, because somebody will act on it. A shop's figure is ours to hold
	because nobody else does (ADR-025); a distributor's comes from ERPNext, where it is real.
	"""

	def validate(self):
		self.party = self.party or self.outlet or self.distributor
