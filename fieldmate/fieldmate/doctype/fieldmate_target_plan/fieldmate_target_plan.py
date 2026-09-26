import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from fieldmate.fieldmate.doctype.fieldmate_target_line.fieldmate_target_line import TARGET_TYPES

# What each depth in the Sales Person tree is called out loud. Anything deeper than the list is
# a rep, because below an area manager there is nobody left but the person in the market.
LEVELS = ("National", "Region", "Area", "Rep")


class FieldMateTargetPlan(Document):
	"""What one person, or everyone under them, is asked for in one period.

	A plan is one document per node of the Sales Person tree. The root carries the company's
	number; cascading it creates a child plan for each node below, and the leaves are what a rep
	actually sees. Nothing is stored twice: a rep's target lives on the rep's own plan, and the
	root's number is the root's, not a sum recomputed on every read.

	That only works if the two agree. `services/target.py` splits in integer units and gives the
	remainder away deliberately, so the leaves add back up to the root exactly - which is Gate 7
	criterion 1, and the reason this cannot be a percentage multiplication.
	"""

	def validate(self):
		self.check_period()
		self.resolve_owner()
		self.stamp_lines()
		self.refuse_duplicate_lines()

	def check_period(self):
		if self.from_date and self.to_date and self.from_date > self.to_date:
			frappe.throw(frappe._("The period ends before it starts."))

	def resolve_owner(self):
		"""Work out where in the tree this sits, and whether it belongs to an actual person."""
		self.field_user = frappe.db.get_value(
			"FieldMate Field User", {"sales_person": self.sales_person}, "name")
		self.is_root = 0 if self.parent_plan else 1
		self.level = self.level_of(self.sales_person)

	@staticmethod
	def level_of(sales_person: str) -> str:
		depth = 0
		seen = set()
		node = sales_person
		while node:
			if node in seen:
				# A tree that loops is a data problem, not ours to fix here - but walking it
				# for ever is, so the walk stops and the plan still saves.
				break
			seen.add(node)
			node = frappe.db.get_value("Sales Person", node, "parent_sales_person")
			if node:
				depth += 1
		return LEVELS[depth] if depth < len(LEVELS) else LEVELS[-1]

	def stamp_lines(self):
		for row in self.lines or []:
			if row.target_type not in TARGET_TYPES:
				frappe.throw(
					frappe._("{0} is not a target type this app knows how to measure.")
					.format(row.target_type))
			row.is_additive = 1 if TARGET_TYPES[row.target_type] else 0
			if flt(row.target_value) <= 0:
				frappe.throw(
					frappe._("The {0} target is zero. A target nobody can miss is not a target.")
					.format(row.target_type))

	def refuse_duplicate_lines(self):
		"""One number per type per scope.

		Two Value lines for the same category is not a bigger target, it is two people having
		typed the same thing - and the achievement job would count the month twice against it.
		"""
		seen = set()
		for row in self.lines or []:
			key = (row.target_type, row.item_group or "", row.brand or "")
			if key in seen:
				scope = " / ".join(p for p in (row.item_group, row.brand) if p) or "overall"
				frappe.throw(
					frappe._("There are two {0} targets for {1}.")
					.format(row.target_type, scope))
			seen.add(key)

	def before_submit(self):
		if self.plan_status == "Draft":
			self.plan_status = "Active"

	def on_cancel(self):
		children = frappe.get_all("FieldMate Target Plan",
		                          filters={"parent_plan": self.name, "docstatus": 1},
		                          pluck="name")
		if children:
			frappe.throw(
				frappe._("{0} plans were cascaded from this one. Cancel those first, or the "
				         "targets below stop adding up to anything.").format(len(children)))
		self.db_set("plan_status", "Cancelled", update_modified=False)

	def line_for(self, target_type: str, item_group=None, brand=None):
		for row in self.lines or []:
			if (row.target_type == target_type
			        and (row.item_group or None) == (item_group or None)
			        and (row.brand or None) == (brand or None)):
				return row
		return None

	def totals(self) -> dict:
		return {row.target_type: flt(row.target_value)
		        for row in (self.lines or []) if not (row.item_group or row.brand)}

	@property
	def has_children(self) -> bool:
		return cint(self.child_count) > 0
