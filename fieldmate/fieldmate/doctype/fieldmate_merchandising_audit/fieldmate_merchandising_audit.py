import frappe
from frappe.model.document import Document
from frappe.utils import cint, today

from fieldmate.services import scope


class FieldMateMerchandisingAudit(Document):
	"""What our products looked like on the shelf at one shop on one day.

	Three numbers come out of this and they are the ones brand teams actually argue about:
	numeric distribution (how many of our lines were on the shelf at all), must-sell compliance
	(how many of the lines we insist on were there), and shelf share (our facings against every
	facing on that shelf). All three are computed here rather than typed, because a typed
	percentage is a claim and a computed one is a measurement.
	"""

	def validate(self):
		if not self.audit_date:
			self.audit_date = today()
		self.mark_must_sell()
		self.roll_up_lines()
		self.roll_up_shelf_share()

	def on_submit(self):
		self.link_to_visit()

	# ------------------------------------------------------------------ must-sell

	def must_sell_items(self) -> set:
		"""The items this shop is expected to stock, from its own list.

		Scoped like the catalogue: the narrowest matching list wins, and a blank scope means the
		list applies everywhere.
		"""
		outlet = frappe.get_cached_doc("FieldMate Outlet", self.outlet)
		lists = frappe.get_all(
			"FieldMate Must Sell List", filters={"is_active": 1}, pluck="name"
		)
		items = set()
		for name in lists:
			doc = frappe.get_cached_doc("FieldMate Must Sell List", name)
			if not scope.is_effective_on(doc, self.audit_date):
				continue
			if not scope.applies_to_outlet(doc, outlet):
				continue
			items.update(row.item_code for row in doc.items)
		return items

	def mark_must_sell(self):
		expected = self.must_sell_items()
		for row in self.lines:
			row.is_must_sell = 1 if row.item_code in expected else 0

		# A must-sell item the rep never looked at is not compliant - it is unchecked. Adding
		# the missing rows is what turns this from a rep's selection into a real audit.
		present = {row.item_code for row in self.lines}
		for item_code in sorted(expected - present):
			self.append("lines", {
				"item_code": item_code,
				"is_must_sell": 1,
				"is_available": 0,
				"note": frappe._("Not checked during the visit"),
			})

	# ------------------------------------------------------------------ rollups

	def roll_up_lines(self):
		self.line_count = len(self.lines)
		self.available_count = sum(1 for row in self.lines if cint(row.is_available))
		must_sell = [row for row in self.lines if cint(row.is_must_sell)]
		self.must_sell_total = len(must_sell)
		self.must_sell_available = sum(1 for row in must_sell if cint(row.is_available))
		self.must_sell_compliance_pct = (
			round(100.0 * self.must_sell_available / self.must_sell_total, 2)
			if self.must_sell_total else 0.0
		)

	def roll_up_shelf_share(self):
		self.our_facings = sum(cint(row.facings) for row in self.lines)
		competitor_facings = sum(cint(row.facings) for row in self.competitors)

		# The rep can report a shelf total directly - counting every pack on a crowded shelf is
		# often faster than listing each competitor. Their count wins when it is at least as
		# large as what we can see; anything smaller is arithmetically impossible.
		counted = self.our_facings + competitor_facings
		reported = cint(self.total_facings)
		self.total_facings = max(reported, counted)

		self.shelf_share_pct = (
			round(100.0 * self.our_facings / self.total_facings, 2)
			if self.total_facings else 0.0
		)

	def link_to_visit(self):
		if not self.visit:
			return
		if frappe.db.get_value("FieldMate Visit", self.visit, "merchandising_audit"):
			return
		frappe.db.set_value(
			"FieldMate Visit", self.visit, "merchandising_audit", self.name,
			update_modified=False,
		)
