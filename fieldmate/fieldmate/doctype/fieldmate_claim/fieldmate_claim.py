import frappe
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

# An Incentive row is what the rep earned. It never came off a shop bill and the distributor was
# never out of pocket for it, so it is not his to claim. Every other benefit kind is.
CLAIMABLE_KINDS = ("Free Goods", "Percent Discount", "Value Discount", "Rate Off")

# Which kinds are money off the bill, as opposed to stock handed over. The distributor settles
# the two differently and argues about them separately, so they are totalled separately.
DISCOUNT_KINDS = ("Percent Discount", "Value Discount", "Rate Off")


class FieldMateClaim(Document):
	"""A distributor asking for back what a rep promised out of his stock.

	Nothing on this document is the distributor's own arithmetic. Every line is copied from a
	submitted Scheme Ledger row - an accrual the server made when the order was routed - and the
	totals are added up from those copies. That is what lets approval be a decision about whether
	we agree, rather than an audit of whether he can add up.

	A claim produces exactly one accounting document, a credit note against his Customer, and it
	produces it on approval rather than on submission. Submitting is him asking; approving is us
	agreeing; settling is the money moving. Three events, weeks apart, three states.
	"""

	def validate(self):
		self.resolve_party()
		self.check_window()
		self.pull_the_lines()
		self.roll_up()
		self.reconcile()

	def resolve_party(self):
		if not self.customer:
			self.customer = frappe.db.get_value(
				"FieldMate Distributor Profile", self.distributor, "customer")
		if not self.customer:
			frappe.throw(
				frappe._("{0} has no Customer on its profile, so a credit note has nowhere to "
				         "go. Set one before claiming.").format(self.distributor))
		if not self.currency:
			self.currency = frappe.db.get_value("Company", self.company, "default_currency")

	def check_window(self):
		if self.from_date and self.to_date and self.from_date > self.to_date:
			frappe.throw(frappe._("The claim period ends before it starts."))

	def pull_the_lines(self):
		"""Re-read every line from its ledger row rather than trusting what arrived.

		The portal builds these lines server-side already, so in practice nothing changes here.
		It runs anyway because the Desk form can be edited by hand, and a claim whose figures
		came from a form is a claim nobody can reconcile.
		"""
		seen = set()
		kept = []
		for row in self.items or []:
			if not row.scheme_ledger:
				frappe.throw(frappe._("A claim line has no ledger entry behind it."))
			if row.scheme_ledger in seen:
				frappe.throw(
					frappe._("Ledger entry {0} appears twice on this claim.")
					.format(row.scheme_ledger))
			seen.add(row.scheme_ledger)

			source = frappe.db.get_value(
				"FieldMate Scheme Ledger", row.scheme_ledger,
				["scheme", "order", "outlet", "field_user", "posting_date", "benefit_kind",
				 "item_code", "benefit_amount", "free_qty", "distributor", "status", "docstatus",
				 "claim"],
				as_dict=True,
			)
			if not source:
				frappe.throw(
					frappe._("Ledger entry {0} no longer exists.").format(row.scheme_ledger))
			if source.docstatus != 1:
				frappe.throw(
					frappe._("Ledger entry {0} is not submitted and cannot be claimed.")
					.format(row.scheme_ledger))
			if source.distributor != self.distributor:
				frappe.throw(
					frappe._("Ledger entry {0} belongs to another distributor.")
					.format(row.scheme_ledger))
			if source.benefit_kind not in CLAIMABLE_KINDS:
				frappe.throw(
					frappe._("Ledger entry {0} is a {1} row. That is what the rep earned, not "
					         "what you gave away, and it is not claimable.")
					.format(row.scheme_ledger, source.benefit_kind))
			if source.claim and source.claim != self.name:
				frappe.throw(
					frappe._("Ledger entry {0} is already on claim {1}.")
					.format(row.scheme_ledger, source.claim))

			row.scheme = source.scheme
			row.order = source.order
			row.outlet = source.outlet
			row.field_user = source.field_user
			row.posting_date = source.posting_date
			row.benefit_kind = source.benefit_kind
			row.item_code = source.item_code
			row.benefit_amount = source.benefit_amount
			row.free_qty = source.free_qty
			kept.append(row)

		if not kept:
			frappe.throw(frappe._("A claim with nothing on it is not a claim."))

	def roll_up(self):
		discount = free_goods = 0.0
		outlets = set()
		for row in self.items or []:
			amount = flt(row.benefit_amount)
			if row.benefit_kind in DISCOUNT_KINDS:
				discount += amount
			else:
				free_goods += amount
			if row.outlet:
				outlets.add(row.outlet)

		self.discount_amount = discount
		self.free_goods_amount = free_goods
		self.claimed_amount = discount + free_goods
		self.line_count = len(self.items or [])
		self.outlet_count = len(outlets)

		# Nobody types the approved figure at the point of claiming, and a blank one would raise a
		# credit note for zero the moment somebody approved without reading. It starts equal to
		# what was claimed and an approver lowers it.
		if not flt(self.approved_amount):
			self.approved_amount = self.claimed_amount

	def reconcile(self):
		"""Compare what is attached against what the window actually holds.

		Gate 9 criterion 2 is this method. A claim is allowed not to reconcile - a distributor may
		deliberately claim half a month, or claim one scheme out of four - but the gap is measured
		and stored, because at approval a partial claim and a missing accrual look identical.
		"""
		eligible = eligible_rows(self.distributor, self.from_date, self.to_date,
		                         scheme=self.scheme, claim=self.name)
		self.ledger_count = len(eligible)
		self.ledger_amount = sum(flt(r.benefit_amount) for r in eligible)
		self.variance_amount = flt(self.ledger_amount) - flt(self.claimed_amount)
		# Currency fields round to two places, so an exact comparison on floats is a comparison of
		# two already-rounded numbers rather than of raw arithmetic. Half a paisa is still a gap.
		self.reconciles = 1 if abs(flt(self.variance_amount, 2)) < 0.005 else 0

	def before_submit(self):
		self.claim_status = "Pending Approval"
		self.submitted_on = now_datetime()

	def on_submit(self):
		"""Claiming takes the accruals off the table. It posts nothing.

		The credit note comes at approval. Marking the ledger here is what stops the same benefit
		reaching a second claim next month, which is the failure this document exists to prevent.
		"""
		for row in self.items or []:
			frappe.db.set_value("FieldMate Scheme Ledger", row.scheme_ledger,
			                    {"status": "Claimed", "claim": self.name},
			                    update_modified=False)

	def on_cancel(self):
		if self.credit_note:
			frappe.throw(
				frappe._("Credit note {0} stands against this claim. Reverse that before "
				         "cancelling the claim underneath it.").format(self.credit_note))

		# Release the back-link before anything else. A submitted ledger row that LINKS here is a
		# lock: Frappe checks back-links before it runs on_cancel, so a row still pointing at this
		# claim refuses the cancel outright.
		self.release_ledger()
		self.db_set("claim_status", "Cancelled", update_modified=False)

	def release_ledger(self):
		for row in self.items or []:
			current = frappe.db.get_value("FieldMate Scheme Ledger", row.scheme_ledger, "claim")
			if current and current != self.name:
				continue
			frappe.db.set_value("FieldMate Scheme Ledger", row.scheme_ledger,
			                    {"status": "Accrued", "claim": None, "settled_on": None},
			                    update_modified=False)


def eligible_rows(distributor: str, from_date, to_date, scheme: str | None = None,
                  claim: str | None = None) -> list[dict]:
	"""Every accrual this distributor could claim in this window.

	Unclaimed rows, plus the rows already on `claim` itself - otherwise a saved claim would
	reconcile against a window its own lines had just emptied, and every claim would read as a
	100% variance the moment it was submitted.
	"""
	rows = frappe.get_all(
		"FieldMate Scheme Ledger",
		filters={
			"distributor": distributor,
			"docstatus": 1,
			"posting_date": ["between", [from_date, to_date]],
			"benefit_kind": ["in", CLAIMABLE_KINDS],
			**({"scheme": scheme} if scheme else {}),
		},
		fields=["name", "scheme", "order", "outlet", "field_user", "posting_date",
		        "benefit_kind", "item_code", "benefit_amount", "free_qty", "status", "claim"],
		order_by="posting_date asc, name asc",
		limit_page_length=0,
	)
	return [r for r in rows if not r.claim or (claim and r.claim == claim)]
