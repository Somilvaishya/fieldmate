import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt


class FieldMateBeat(Document):
	def validate(self):
		self.validate_schedule()
		self.renumber_outlets()
		self.validate_outlets_are_unique()
		self.validate_outlets_belong_here()
		self.validate_outlet_not_on_another_beat()
		self.validate_rep_covers_this_territory()
		self.roll_up()

	def validate_schedule(self):
		# A week pattern on a weekly beat reads as a restriction that is quietly ignored.
		if self.frequency == "Weekly" and self.week_pattern != "All":
			frappe.throw(
				frappe._("A weekly beat runs every week, so Week Pattern must be All. "
				         "Use Fortnightly or Monthly to visit on selected weeks.")
			)

	def renumber_outlets(self):
		"""Rewrite the sequence 1..n in table order, so gaps and duplicates never accumulate."""
		for index, row in enumerate(self.outlets or [], start=1):
			row.sequence = index

	def validate_outlets_are_unique(self):
		seen = set()
		for row in self.outlets or []:
			if row.outlet in seen:
				frappe.throw(
					frappe._("Row {0}: {1} is already on this beat. A shop is visited once per run.")
					.format(row.idx, row.outlet)
				)
			seen.add(row.outlet)

	def validate_outlets_belong_here(self):
		"""A beat cannot reach outside its own territory.

		Otherwise a rep scoped to one district would be handed a route containing shops they
		cannot even read, and the visit would fail in the field with nothing to explain it.
		"""
		if not self.outlets:
			return

		allowed = set(territory_and_descendants(self.territory))
		for row in self.outlets:
			outlet_territory = frappe.db.get_value("FieldMate Outlet", row.outlet, "territory")
			if outlet_territory not in allowed:
				frappe.throw(
					frappe._("Row {0}: {1} is in {2}, which is outside this beat's territory ({3}).")
					.format(row.idx, row.outlet, outlet_territory, self.territory)
				)

	def validate_outlet_not_on_another_beat(self):
		"""One active beat per outlet.

		Coverage and productivity are counted per beat. A shop on two active beats is counted
		twice, and the numbers stop meaning anything.
		"""
		if not self.is_active or not self.outlets:
			return

		for row in self.outlets:
			clash = frappe.db.sql(
				"""
				select parent from `tabFieldMate Beat Outlet` bo
				inner join `tabFieldMate Beat` b on b.name = bo.parent
				where bo.outlet = %(outlet)s and b.name != %(beat)s and b.is_active = 1
				limit 1
				""",
				{"outlet": row.outlet, "beat": self.name or ""},
			)
			if clash:
				frappe.throw(
					frappe._("Row {0}: {1} is already on active beat {2}. "
					         "Remove it there first, or deactivate that beat.")
					.format(row.idx, row.outlet, clash[0][0])
				)

	def validate_rep_covers_this_territory(self):
		"""The assigned rep must be able to see the beat's territory, or they get a route of
		shops their own permissions hide from them."""
		if not self.assigned_to:
			return
		rep_territory = frappe.db.get_value("FieldMate Field User", self.assigned_to, "territory")
		if not rep_territory:
			return
		if self.territory not in territory_and_descendants(rep_territory):
			frappe.throw(
				frappe._("{0} covers {1}, which does not include this beat's territory ({2}).")
				.format(self.assigned_to, rep_territory, self.territory)
			)

	def roll_up(self):
		self.outlet_count = len(self.outlets or [])
		self.total_potential = flt(sum(flt(r.monthly_potential) for r in self.outlets or []))
		self.estimated_duration_min = cint(
			sum(cint(r.expected_duration_min) for r in self.outlets or [])
		)

	def on_update(self):
		self.sync_primary_beat()

	def on_trash(self):
		for row in self.outlets or []:
			clear_primary_beat(row.outlet, self.name)

	def sync_primary_beat(self):
		"""Keep the outlet's back-reference in step.

		The beat's child table is the truth; this is a denormalised pointer so a visit screen can
		answer "which route is this shop on" without scanning every beat.
		"""
		current = {row.outlet for row in self.outlets or []}

		for outlet in frappe.get_all(
			"FieldMate Outlet", filters={"primary_beat": self.name}, pluck="name"
		):
			if outlet not in current:
				clear_primary_beat(outlet, self.name)

		if not self.is_active:
			for outlet in current:
				clear_primary_beat(outlet, self.name)
			return

		for outlet in current:
			frappe.db.set_value(
				"FieldMate Outlet", outlet, "primary_beat", self.name, update_modified=False
			)


def clear_primary_beat(outlet: str, beat: str) -> None:
	if frappe.db.get_value("FieldMate Outlet", outlet, "primary_beat") == beat:
		frappe.db.set_value("FieldMate Outlet", outlet, "primary_beat", None, update_modified=False)


def territory_and_descendants(territory: str) -> list[str]:
	"""A territory plus everything beneath it. Territory is a tree, so a beat placed on a parent
	node may legitimately contain outlets from any area below."""
	if not territory:
		return []
	descendants = frappe.get_all(
		"Territory",
		filters={"lft": [">=", frappe.db.get_value("Territory", territory, "lft") or 0],
		         "rgt": ["<=", frappe.db.get_value("Territory", territory, "rgt") or 0]},
		pluck="name",
	)
	return descendants or [territory]
