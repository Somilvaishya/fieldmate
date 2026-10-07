import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate


class FieldMateCollection(Document):
	"""Money a rep took at a counter, and whose it is.

	`party_type` decides everything downstream (ADR-025). A shop buys from its distributor, so
	cash taken at a shop is the **distributor's** and reaches no ledger of ours — recording a
	Payment Entry for it would credit us with money we never earned and reduce a receivable that
	was never raised. A distributor buys from us, so their payment is ours.

	The rep's hands look identical in both cases: same person, same receipt book, same satchel.
	Only the counterparty differs, so only the counterparty may decide.

	**Nothing here posts, in either case.** A Payment Entry appears when a deposit is confirmed by
	somebody at our end, and only for the part that was ours to begin with. Gate 6 criterion 2
	asks for exactly that.
	"""

	def validate(self):
		self.resolve_party()
		self.allocate()
		self.check_the_money_adds_up()
		self.stamp_receipt()

	def resolve_party(self):
		"""Who the money came from, and whether it is ours."""
		if self.party_type == "Outlet":
			if not self.outlet:
				frappe.throw(frappe._("A collection at a shop needs the shop."))
			self.party = self.outlet
			# Filled from the shop rather than asked for: the rep knows which counter they are
			# standing at, not which distributor's ledger it feeds.
			self.distributor = self.distributor or self.distributor_behind(self.outlet)
			self.posts_to_ledger = 0
		else:
			if not self.distributor:
				frappe.throw(frappe._("A collection from a distributor needs the distributor."))
			self.party = self.distributor
			self.outlet = None
			self.posts_to_ledger = 1

		if not self.company:
			self.company = frappe.db.get_value("FieldMate Field User", self.field_user, "company")
		if not self.currency and self.company:
			self.currency = frappe.db.get_value("Company", self.company, "default_currency")

	def distributor_behind(self, outlet) -> str | None:
		"""Whose money this is. The outlet names its billing party directly (step 2d)."""
		return frappe.db.get_value("FieldMate Outlet", outlet, "distributor")

	def allocate(self):
		"""Spread the money across the bills the rep ticked, and name what is left over.

		Money against no particular bill is ordinary at a kirana counter. It is not an error, but
		it has to be visible rather than quietly spread about — a rep who meant it against one
		bill and an accountant who applied it to another is an argument nobody can settle later.
		"""
		total = 0.0
		for row in self.allocations or []:
			row.allocated_amount = flt(row.allocated_amount)
			total += row.allocated_amount
			if row.due_date:
				row.days_overdue = max(
					0, frappe.utils.date_diff(getdate(self.collection_date), getdate(row.due_date))
				)

		self.allocated_amount = total
		self.unallocated_amount = flt(self.amount) - total

	def check_the_money_adds_up(self):
		if flt(self.amount) <= 0:
			frappe.throw(frappe._("A collection of nothing is not a collection."))

		if flt(self.allocated_amount) - flt(self.amount) > 0.005:
			frappe.throw(
				frappe._("You have put {0} against bills but only collected {1}. One of the two "
				         "is wrong.").format(
					frappe.format_value(self.allocated_amount, {"fieldtype": "Currency"}),
					frappe.format_value(self.amount, {"fieldtype": "Currency"}),
				)
			)

		# A cheque with no number cannot be followed up, deposited or chased when it bounces.
		if self.mode in ("Cheque", "DD") and not (self.instrument_no or "").strip():
			frappe.throw(frappe._("A cheque needs its number. Nobody can chase one without it."))

	def stamp_receipt(self):
		"""The number the shopkeeper is handed.

		Issued here rather than on the phone: two devices offline in the same market would
		otherwise hand out the same number, and the first thing anybody does with a receipt
		number is use it to tell two payments apart.
		"""
		if not self.receipt_no:
			self.receipt_no = frappe.model.naming.make_autoname(
				f"REC-{getdate(self.collection_date).strftime('%Y%m%d')}-.####"
			)

	def on_submit(self):
		self.db_set("status", "Collected", update_modified=False)
		self.release_what_this_pays_for()

	def release_what_this_pays_for(self):
		"""A season booking held for its advance goes the moment the advance arrives.

		Here rather than in a service because a collection taken with no signal arrives through
		`sync.push`, which inserts and submits the document directly and never calls a service -
		the same reason the order reprices on its controller. A rep who collects an advance in a
		village and syncs that evening must not find the booking still held in the morning.

		Never allowed to fail the collection. The money has been taken and recorded; a booking
		that did not release is a thing somebody can look at, and a collection that refused to
		save because of it is money with nowhere to go.
		"""
		from fieldmate.services import order as order_service

		for row in self.allocations or []:
			if row.reference_type != "FieldMate Order" or not row.reference_name:
				continue
			try:
				order_service.release_if_paid(row.reference_name)
			except Exception:
				frappe.log_error(title="fieldmate: releasing a booking after a collection")

	def on_cancel(self):
		if self.deposit and frappe.db.get_value(
			"FieldMate Collection Deposit", self.deposit, "status"
		) == "Confirmed":
			frappe.throw(
				frappe._("This collection is already inside a confirmed deposit. Reverse the "
				         "deposit first — cancelling it here would leave the bank with money "
				         "nothing accounts for.")
			)
		self.db_set("status", "Cancelled", update_modified=False)

	def mark(self, status: str, **extra) -> None:
		"""Move the status without a save. The rep holds no write on their own collection."""
		values = {"status": status}
		values.update(extra)
		frappe.db.set_value("FieldMate Collection", self.name, values, update_modified=False)
