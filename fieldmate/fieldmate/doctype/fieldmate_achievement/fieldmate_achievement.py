from frappe.model.document import Document


class FieldMateAchievement(Document):
	"""A snapshot of one plan, rewritten by the nightly job.

	Not submittable, and deliberately so. A submitted document says a decision was taken; this
	says what was true when it last ran, and it will say something different tomorrow. What must
	not move once a period closes is the payout, and that is a different document.

	Nothing is computed in this controller. `services/target.py` measures, because the same
	arithmetic has to be callable from a job, a test and a gate script without a document in
	hand.
	"""
