import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt, now_datetime


class FieldMateCollectionDeposit(Document):
	"""A rep declaring what they handed over, and the only place money reaches the ledger.

	A deposit is **declared** by the rep and **confirmed** by somebody at our end. Nothing posts
	until that second step, and Gate 6 criterion 2 asks for exactly that: no Payment Entry exists
	before confirmation, and a rep cannot make one directly — which they cannot, holding no
	permission on the DocType at all (ADR-004).

	Confirmation posts only the part that was **ours** (ADR-025). A shop's cash was the
	distributor's all along and passes through the rep's satchel without ever being our receivable;
	it still needs declaring, because the rep is holding somebody's money and that has to be
	accounted for, but it posts nothing.

	The two steps are deliberately different people. A declaration a rep could confirm themselves
	is a declaration, not a control.
	"""

	def validate(self):
		self.pull_the_lines()
		self.roll_up()

	def pull_the_lines(self):
		"""Read each collection rather than trusting what the phone said it was worth."""
		for row in self.lines or []:
			if not row.collection:
				continue
			source = frappe.db.get_value(
				"FieldMate Collection", row.collection,
				["party", "mode", "amount", "instrument_no", "posts_to_ledger", "status"],
				as_dict=True,
			)
			if not source:
				frappe.throw(frappe._("Collection {0} no longer exists.").format(row.collection))
			if source.status in ("Cancelled", "Bounced"):
				frappe.throw(
					frappe._("Collection {0} is {1} and cannot go into a deposit.")
					.format(row.collection, source.status.lower())
				)
			row.party = source.party
			row.mode = source.mode
			row.amount = source.amount
			row.instrument_no = source.instrument_no
			row.posts_to_ledger = source.posts_to_ledger

	def roll_up(self):
		cash = cheque = ours = total = 0.0
		cheques = 0
		for row in self.lines or []:
			amount = flt(row.amount)
			total += amount
			if row.mode in ("Cheque", "DD"):
				cheque += amount
				cheques += 1
			elif row.mode == "Cash":
				cash += amount
			if cint(row.posts_to_ledger):
				ours += amount

		self.cash_amount = cash
		self.cheque_amount = cheque
		self.cheque_count = cheques
		self.total_amount = total
		self.ours_amount = ours

		if not total:
			frappe.throw(frappe._("A deposit with nothing in it is not a deposit."))

	def on_submit(self):
		"""Submitting is the rep declaring. It posts nothing at all."""
		self.db_set("status", "Declared", update_modified=False)
		for row in self.lines or []:
			frappe.db.set_value("FieldMate Collection", row.collection,
			                    {"status": "Deposited", "deposit": self.name},
			                    update_modified=False)

	def on_cancel(self):
		if self.status == "Confirmed":
			frappe.throw(
				frappe._("This deposit is confirmed and its payments are posted. Reverse those "
				         "first rather than cancelling the declaration underneath them.")
			)
		self.db_set("status", "Cancelled", update_modified=False)
		for row in self.lines or []:
			frappe.db.set_value("FieldMate Collection", row.collection,
			                    {"status": "Collected", "deposit": None},
			                    update_modified=False)
