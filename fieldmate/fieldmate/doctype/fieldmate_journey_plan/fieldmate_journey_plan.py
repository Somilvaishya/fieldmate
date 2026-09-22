import frappe
from frappe.model.document import Document
from frappe.utils import cint, date_diff, getdate

# A plan longer than this is almost always a typo in the date fields, and generating it would
# write thousands of rows before anyone noticed.
MAX_PLAN_DAYS = 120


class FieldMateJourneyPlan(Document):
	def validate(self):
		if date_diff(self.to_date, self.from_date) < 0:
			frappe.throw(frappe._("To date is before from date."))
		if date_diff(self.to_date, self.from_date) > MAX_PLAN_DAYS:
			frappe.throw(
				frappe._("A plan cannot span more than {0} days. Generate one month at a time.")
				.format(MAX_PLAN_DAYS)
			)

		self.validate_no_overlap()
		self.roll_up()

	def validate_no_overlap(self):
		"""Two submitted plans covering one date would make 'today's beat' ambiguous."""
		clash = frappe.db.sql(
			"""
			select name from `tabFieldMate Journey Plan`
			where field_user = %(user)s and name != %(self)s and docstatus = 1
			  and from_date <= %(to)s and to_date >= %(from)s
			limit 1
			""",
			{"user": self.field_user, "self": self.name or "",
			 "from": getdate(self.from_date), "to": getdate(self.to_date)},
		)
		if clash:
			frappe.throw(
				frappe._("{0} already covers part of this period for {1}. Cancel it first.")
				.format(clash[0][0], self.field_user)
			)

	def roll_up(self):
		days = self.days or []
		self.working_days = sum(1 for d in days if cint(d.is_working_day))
		self.planned_days = sum(1 for d in days if d.beat)
		self.planned_visits = sum(cint(d.outlet_count) for d in days if d.beat)

	def on_submit(self):
		if not self.days:
			frappe.throw(frappe._("Generate the days before submitting this plan."))
