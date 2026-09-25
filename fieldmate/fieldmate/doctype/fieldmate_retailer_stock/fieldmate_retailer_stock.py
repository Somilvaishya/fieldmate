import frappe
from frappe.model.document import Document
from frappe.utils import cint, date_diff, flt, getdate


class FieldMateRetailerStock(Document):
	"""What a shop was holding when the rep counted it.

	Two things come out of this. The obvious one is distribution: which of our SKUs a shop
	actually stocks, as opposed to which ones somebody once told us they stock. The second is
	retailer-level offtake — count a shop twice and the fall between the counts, plus whatever
	was delivered in between, is what the shop sold through.

	An uncounted line and a line counted at zero are opposite facts. The first says nobody
	looked; the second says the rep looked and the shelf was empty, which is a lost sale and a
	reason to push. A Frappe Float is never null, so the difference is carried by `is_counted`
	rather than inferred from the number — that inference was the bug this field exists to
	prevent.

	A partial count saves. A rep interrupted halfway through has still learnt something, and
	refusing it would mean the app throws that away.
	"""

	def validate(self):
		self.link_to_previous()
		self.normalise_lines()
		self.roll_up()

	def link_to_previous(self):
		previous = frappe.db.get_value(
			"FieldMate Retailer Stock",
			{"outlet": self.outlet, "stock_date": ["<", self.stock_date], "docstatus": 1,
			 "name": ["!=", self.name or ""]},
			["name", "stock_date"],
			order_by="stock_date desc",
			as_dict=True,
		)
		if not previous:
			self.previous_stock = None
			self.days_since_previous = 0
			return

		self.previous_stock = previous.name
		self.days_since_previous = date_diff(getdate(self.stock_date), getdate(previous.stock_date))

		last = {
			row.item_code: flt(row.qty)
			for row in frappe.get_all(
				"FieldMate Retailer Stock Item",
				filters={"parent": previous.name, "parenttype": "FieldMate Retailer Stock"},
				fields=["item_code", "qty"],
			)
		}
		for row in self.items or []:
			row.last_qty = last.get(row.item_code, 0)
			row.last_counted_on = previous.stock_date if row.item_code in last else None

	def normalise_lines(self):
		for row in self.items or []:
			row.conversion_factor = flt(row.conversion_factor) or 1
			# The rep types cases; everything downstream compares base units. Converting here
			# means no report has to remember which unit a given shop was counted in.
			row.qty = flt(row.qty_display) * flt(row.conversion_factor)
			row.is_out_of_stock = 1 if (cint(row.is_counted) and not flt(row.qty)) else 0

	def roll_up(self):
		lines = self.items or []
		self.total_lines = len(lines)
		self.counted_lines = sum(1 for row in lines if cint(row.is_counted))
		self.coverage_pct = (
			round(100.0 * self.counted_lines / self.total_lines, 2) if self.total_lines else 0
		)
		self.is_partial = 1 if self.counted_lines < self.total_lines else 0

	def offtake(self) -> dict:
		"""What this shop sold through since the last count, per item.

		    previous count + delivered in between - this count = sold through

		The same identity as the distributor's, one level down the chain. Returns only items we
		can actually answer for: a line nobody counted this time, or last time, is left out
		rather than reported as a number that looks real.
		"""
		if not self.previous_stock:
			return {}

		delivered = self.delivered_since()
		previous = {
			row.item_code: (flt(row.qty), cint(row.is_counted))
			for row in frappe.get_all(
				"FieldMate Retailer Stock Item",
				filters={"parent": self.previous_stock, "parenttype": "FieldMate Retailer Stock"},
				fields=["item_code", "qty", "is_counted"],
			)
		}

		sold = {}
		for row in self.items or []:
			was, was_counted = previous.get(row.item_code, (0, 0))
			if not (cint(row.is_counted) and was_counted):
				continue
			sold[row.item_code] = was + flt(delivered.get(row.item_code)) - flt(row.qty)
		return sold

	def delivered_since(self) -> dict:
		"""What this shop was sent between the two counts, from our own orders."""
		if not self.previous_stock:
			return {}
		since = frappe.db.get_value("FieldMate Retailer Stock", self.previous_stock, "stock_date")

		orders = frappe.get_all(
			"FieldMate Order",
			filters={"outlet": self.outlet, "docstatus": 1,
			         "order_date": ["between", [since, self.stock_date]]},
			pluck="name",
		)
		if not orders:
			return {}

		delivered = {}
		for doctype in ("FieldMate Order Item", "FieldMate Free Goods"):
			for row in frappe.get_all(
				doctype,
				filters={"parent": ["in", orders], "parenttype": "FieldMate Order"},
				fields=["item_code", "qty"],
			):
				delivered[row.item_code] = delivered.get(row.item_code, 0) + flt(row.qty)
		return delivered
