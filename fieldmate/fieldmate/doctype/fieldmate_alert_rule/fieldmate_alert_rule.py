import frappe
from frappe.model.document import Document
from frappe.utils import cint

# The five, and the unit each threshold is read in. Named here so the form can say so and the
# evaluator can refuse a rule whose threshold means nothing.
EXCEPTIONS = {
	"Day Not Started": "hours past the expected start",
	"No Order All Day": "visits made with nothing sold",
	"Coverage Below Target": "percent",
	"Collection Overdue In Hand": "rupees carried",
	"Geo Fence Breaches": "breaches in a day",
}


class FieldMateAlertRule(Document):
	"""A threshold and an audience. Never a condition.

	What is being measured lives in `services/alerts.py`; a rule chooses one of five known
	exceptions and says at what level and to whom. A site that could write its own condition
	here would be a site where nobody can say what an alert means six months later, and where
	the gate criterion - each rule fires exactly once per occurrence - stops being checkable.
	"""

	def validate(self):
		self.check_threshold()
		self.check_window()

	def check_threshold(self):
		if self.exception not in EXCEPTIONS:
			frappe.throw(
				frappe._("{0} is not an exception this app knows how to watch for.")
				.format(self.exception))
		if self.exception == "Coverage Below Target" and not (0 < self.threshold <= 100):
			frappe.throw(
				frappe._("A coverage threshold is a percentage between 1 and 100."))

	def check_window(self):
		if cint(self.consecutive_days) < 1:
			self.consecutive_days = 1
		if cint(self.cooldown_days) < 0:
			self.cooldown_days = 0

	def roles(self) -> list[str]:
		return [r.strip() for r in (self.notify_roles or "").split(",") if r.strip()]
