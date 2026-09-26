import frappe
from frappe.model.document import Document

# The nine, named once. Everything downstream - the charts, the alert rules, the manager's
# summary, the rep's phone - asks for these by name rather than re-deriving them, which is the
# only way nine numbers stay one set of nine numbers.
#
# Five are ratios and four are counts, and the difference matters when a month is asked for:
# a count adds up, a ratio has to be recomputed from its own numerator and denominator. Both
# halves of every ratio are stored on the row for exactly that reason.
CORE_METRICS = {
	"coverage_pct": ("outlets_billed", "outlets_in_scope"),
	"productive_pct": ("productive_visits", "actual_visits"),
	"visit_compliance_pct": ("actual_visits", "planned_visits"),
	"collection_efficiency_pct": ("collection_amount", "billable_base"),
	"lines_per_call": ("order_lines", "productive_visits"),
	"avg_order_value": ("order_value", "orders_count"),
	# The three that are simply totals.
	"order_value": None,
	"order_qty": None,
	"new_outlets": None,
}

# Which of the nine are percentages, so a caller formatting them does not have to guess.
RATIO_METRICS = tuple(k for k, v in CORE_METRICS.items() if v and k.endswith("_pct"))


class FieldMateKPISnapshot(Document):
	"""One rep, one day, counted once.

	Every chart, report and screen in the app reads these rows. Nothing downstream counts a
	visit or an order for itself - that is Gate 8 criterion 3 in as many words, and it is not
	only about speed. Two places counting "productive calls" from raw documents is two places
	that will eventually disagree, and the argument is unwinnable because both are right
	according to their own query.

	Daily grain on purpose. A month is these rows added up, so a visit corrected three weeks
	late restates the month by recomputing one row rather than by rebuilding anything.

	Nothing is computed in this controller; `services/kpi.py` does the counting, because the same
	arithmetic has to be callable from a job, a test and a gate script with no document in hand.
	"""

	def before_insert(self):
		self.guard_against_a_second_row()

	def guard_against_a_second_row(self):
		"""One row per rep per day.

		Enforced here rather than by a unique index across two columns, which Frappe does not
		offer on a DocType. Two snapshots for one rep-day is two answers to the same question,
		and every sum downstream would quietly double.
		"""
		existing = frappe.db.get_value("FieldMate KPI Snapshot", {
			"field_user": self.field_user, "snapshot_date": self.snapshot_date,
		}, "name")
		if existing:
			frappe.throw(
				frappe._("{0} already has a snapshot for {1} ({2}).")
				.format(self.field_user, self.snapshot_date, existing))
