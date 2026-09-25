import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class FieldMateVanSettlement(Document):
	"""The end of a van day, and the one screen where the stock has to add up.

	    loaded - sold - returned = short

	Three of those four are not the rep's to type. **Loaded** comes from the morning's van load.
	**Sold** is computed from their own submitted orders, which is what makes this document worth
	anything — a settlement where the rep enters what they sold proves nothing. **Returned** is
	the single number they count and enter. **Short** falls out, and if it is not zero somebody
	has to say what happened to it.

	Nothing here posts. The goods were the distributor's the whole time (ADR-024), so there is no
	Stock Entry and no GL Entry; the cash goes back to the distributor too. What this document
	gives us is the count, the difference, and a sentence explaining it.
	"""

	def validate(self):
		self.pull_from_load()
		self.compute_each_line()
		self.roll_up()
		self.check_shortfall_is_explained()

	def pull_from_load(self):
		"""Loaded quantities are read, never retyped.

		A settlement that lets somebody restate the morning's figures can always be made to
		balance, which is the opposite of what it is for.
		"""
		if not self.van_load:
			return
		load = frappe.get_doc("FieldMate Van Load", self.van_load)
		self.distributor = load.distributor
		self.vehicle_no = load.vehicle_no
		self.field_user = self.field_user or load.field_user
		self.settlement_date = self.settlement_date or load.load_date
		self.currency = self.currency or load.currency

		loaded = load.loaded_by_item()
		sold = self.sold_by_item()
		rates = {row.item_code: flt(row.rate) for row in load.items or []}
		units = {row.item_code: (row.display_uom, flt(row.conversion_factor) or 1)
		         for row in load.items or []}

		existing = {row.item_code: row for row in self.items or []}
		self.set("items", [])
		for item_code, loaded_qty in loaded.items():
			was = existing.get(item_code)
			row = self.append("items", {})
			row.item_code = item_code
			row.loaded_qty = loaded_qty
			row.sold_qty = flt(sold.get(item_code))
			row.returned_qty = flt(was.returned_qty) if was else 0
			row.returned_good = flt(was.returned_good) if was else 0
			row.returned_damaged = flt(was.returned_damaged) if was else 0
			row.display_uom, row.conversion_factor = units.get(item_code, (None, 1))
			row._rate = rates.get(item_code, 0)

	def sold_by_item(self) -> dict:
		"""What this rep actually sold today, from their own submitted orders.

		Read from the records rather than taken from the phone, for the same reason Day End
		counts its own visits: a phone that spent the day with no signal does not know which of
		its orders finally landed.
		"""
		if not (self.field_user and self.settlement_date):
			return {}

		orders = frappe.get_all(
			"FieldMate Order",
			filters={"field_user": self.field_user, "order_date": self.settlement_date,
			         "docstatus": 1},
			pluck="name",
		)
		if not orders:
			return {}

		sold = {}
		for row in frappe.get_all(
			"FieldMate Order Item",
			filters={"parent": ["in", orders], "parenttype": "FieldMate Order"},
			fields=["item_code", "qty"],
		):
			sold[row.item_code] = sold.get(row.item_code, 0) + flt(row.qty)

		# Free goods left the van too. A scheme that gave two packs away has taken two packs out
		# of the vehicle, and a settlement that ignores them reports the rep short by exactly the
		# amount they gave away on our instructions.
		for row in frappe.get_all(
			"FieldMate Free Goods",
			filters={"parent": ["in", orders], "parenttype": "FieldMate Order"},
			fields=["item_code", "qty"],
		):
			sold[row.item_code] = sold.get(row.item_code, 0) + flt(row.qty)
		return sold

	def compute_each_line(self):
		for row in self.items or []:
			# Good and damaged are the split; returned is their sum. Entering the split is what
			# the rep does on the screen, so the total follows it rather than the other way round.
			split = flt(row.returned_good) + flt(row.returned_damaged)
			if split:
				row.returned_qty = split
			row.short_qty = flt(row.loaded_qty) - flt(row.sold_qty) - flt(row.returned_qty)
			row.short_value = flt(row.short_qty) * flt(getattr(row, "_rate", 0))

	def roll_up(self):
		self.loaded_qty = sum(flt(r.loaded_qty) for r in self.items or [])
		self.sold_qty = sum(flt(r.sold_qty) for r in self.items or [])
		self.returned_qty = sum(flt(r.returned_qty) for r in self.items or [])
		self.short_qty = self.loaded_qty - self.sold_qty - self.returned_qty
		self.short_value = sum(flt(r.short_value) for r in self.items or [])

		self.cash_collected = self.collected_today()
		self.cash_to_hand_over = flt(self.cash_collected) - flt(self.cash_deposited)

	def collected_today(self) -> float:
		"""Cash taken at the door today.

		Collections land in Phase 6. Until then this reads the day's cash-on-delivery orders,
		which is the whole of it for a van route - and returns a real figure rather than a zero
		that would quietly under-report every settlement until then.
		"""
		if not (self.field_user and self.settlement_date):
			return 0.0
		return flt(frappe.db.get_value(
			"FieldMate Order",
			{"field_user": self.field_user, "order_date": self.settlement_date, "docstatus": 1,
			 "payment_term": ["in", ["Cash on Delivery", "UPI on Delivery"]]},
			"sum(net_total)",
		))

	def check_shortfall_is_explained(self):
		"""Never round a difference away, and never let it past without a word.

		This is the entire point of the screen. A settlement that balances because the app
		quietly absorbed three cases is worse than no settlement at all.
		"""
		if abs(flt(self.short_qty)) < 0.0001:
			return
		if not (self.shortfall_note or "").strip():
			short = ", ".join(
				f"{row.item_code} {flt(row.short_qty):g}"
				for row in self.items or [] if abs(flt(row.short_qty)) >= 0.0001
			)
			frappe.throw(
				frappe._("The van is short: {0}. Say what happened before settling the day.")
				.format(short)
			)

	def on_submit(self):
		self.db_set("settlement_status", "Settled", update_modified=False)
		self.db_set("settled_on", now_datetime(), update_modified=False)
		if self.van_load:
			frappe.db.set_value("FieldMate Van Load", self.van_load, "load_status", "Settled",
			                    update_modified=False)

	def on_cancel(self):
		self.db_set("settlement_status", "Cancelled", update_modified=False)
		if self.van_load:
			frappe.db.set_value("FieldMate Van Load", self.van_load, "load_status", "Confirmed",
			                    update_modified=False)
