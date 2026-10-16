import frappe
from frappe.model.document import Document
from frappe.utils import cint, flt

from fieldmate.services import settings as settings_service
from fieldmate.services import trail as trail_service

# What each type is capped at, and where that cap is read from. Travel is absent because it is
# not capped by a daily figure - it is capped by how far the rep actually went.
ALLOWANCE_SETTING = {
	"Food": "daily_food_allowance",
	"Stay": "daily_stay_allowance",
}


class FieldMateExpenseClaim(Document):
	"""A day in the market, priced.

	The rule the whole document exists to hold: **the distance is the server's, the claim is the
	rep's, and the gap between them is the manager's.** A rep may always file - somebody who
	walked a market with no signal has a real claim and a thin trail - but they cannot approve
	their own excess, and the excess is measured rather than guessed at.

	Gate 7 criterion 4 is that sentence: the distance matches Location Trail, and a rep cannot
	edit it upward without approval.
	"""

	def validate(self):
		self.resolve_rep()
		self.measure_the_day()
		self.price_it()
		self.decide_who_signs()
		self.check_proof()

	def resolve_rep(self):
		rep = frappe.db.get_value("FieldMate Field User", self.field_user,
		                          ["employee", "company"], as_dict=True)
		if not rep:
			frappe.throw(frappe._("{0} is not a field user.").format(self.field_user))
		self.employee = rep.employee
		if not self.company:
			self.company = rep.company or settings_service.value("default_company")

	def measure_the_day(self):
		"""Read the trail. Never accept a distance the phone sent.

		A device that could state its own mileage is a device that could invent it, and this is
		the one number on the document that turns directly into money.
		"""
		if self.expense_type != "Travel":
			self.trail_distance_km = 0
			self.claimed_distance_km = 0
			self.distance_variance_km = 0
			self.distance_variance_pct = 0
			self.trail_ping_count = 0
			return

		self.trail_distance_km = flt(trail_service.distance_for(self.field_user, self.claim_date), 2)

		trail = frappe.db.get_value(
			"FieldMate Location Trail",
			{"field_user": self.field_user, "trail_date": self.claim_date},
			["name", "ping_count", "day"], as_dict=True)
		self.trail_ping_count = cint(trail.ping_count) if trail else 0
		self.day = trail.day if trail else None

		# An unstated claim is the trail. A rep who agrees with the recording should not have to
		# retype it, and most of them do agree.
		if not flt(self.claimed_distance_km):
			self.claimed_distance_km = self.trail_distance_km

		over = flt(self.claimed_distance_km) - flt(self.trail_distance_km)
		self.distance_variance_km = flt(over, 2)
		self.distance_variance_pct = round(
			over / flt(self.trail_distance_km) * 100, 2) if flt(self.trail_distance_km) else (
			100 if over > 0 else 0)

	def price_it(self):
		if self.expense_type == "Travel":
			rate = flt(self.rate_per_km) or flt(settings_service.value("travel_rate_per_km"))
			if rate <= 0:
				frappe.throw(
					frappe._("No travel rate per km is set in FieldMate Settings, so a travel "
					         "claim cannot be priced. Set one before reps start filing."))
			# Frozen at the moment of claiming. A rate changed between filing and approval must
			# not silently restate the figure the rep was shown on the screen.
			self.rate_per_km = rate
			self.computed_amount = flt(flt(self.claimed_distance_km) * rate, 2)
			self.allowance_cap = 0
		else:
			setting = ALLOWANCE_SETTING.get(self.expense_type)
			cap = flt(settings_service.value(setting)) if setting else 0
			self.allowance_cap = cap
			self.computed_amount = cap if cap else flt(self.claimed_amount)

		if not flt(self.claimed_amount):
			self.claimed_amount = self.computed_amount
		if flt(self.claimed_amount) <= 0:
			frappe.throw(frappe._("A claim for nothing is not a claim."))

	def decide_who_signs(self):
		"""Does this need a manager, and if so say why in words the rep will read."""
		reasons = []

		if self.expense_type == "Travel":
			tolerance = flt(settings_service.value("expense_distance_tolerance_pct"))
			if flt(self.distance_variance_km) > 0 and flt(self.distance_variance_pct) > tolerance:
				reasons.append(
					f"{flt(self.distance_variance_km):g} km more than the trail recorded "
					f"({flt(self.distance_variance_pct):g}% over, tolerance {tolerance:g}%)")
			if not flt(self.trail_distance_km) and flt(self.claimed_distance_km):
				reasons.append("no GPS trail was recorded for that day")

		if flt(self.claimed_amount) > flt(self.computed_amount) + 0.005:
			reasons.append(
				f"claimed {flt(self.claimed_amount):,.2f} against {flt(self.computed_amount):,.2f} "
				f"the rule allows")

		if flt(self.allowance_cap) and flt(self.claimed_amount) > flt(self.allowance_cap) + 0.005:
			reasons.append(f"over the {flt(self.allowance_cap):,.2f} daily allowance")

		self.needs_approval = 1 if reasons else 0
		self.approval_reason = "; ".join(reasons) if reasons else None

		# Where nothing is in question, the approved figure is the claimed one from the start.
		# A manager can still lower it; what they do not have to do is confirm every ordinary day.
		if not self.needs_approval and not flt(self.approved_amount):
			self.approved_amount = self.claimed_amount

	def check_proof(self):
		threshold = flt(settings_service.value("expense_receipt_required_above"))
		self.receipt_required = 1 if threshold and flt(self.claimed_amount) > threshold else 0
		if self.receipt_required and not self.receipt and self.docstatus == 1:
			frappe.throw(
				frappe._("A claim over {0} needs a photograph of the bill.").format(threshold))

	def before_submit(self):
		self.check_proof()
		self.claim_status = "Pending Approval" if self.needs_approval else "Approved"
		if self.claim_status == "Approved" and not flt(self.approved_amount):
			self.approved_amount = self.claimed_amount

	def on_cancel(self):
		if self.claim_status == "Settled":
			frappe.throw(
				frappe._("This claim is settled{0}. Reverse the payment before cancelling the "
				         "record of it.").format(
					f" as {self.hrms_expense_claim}" if self.hrms_expense_claim else ""))
		self.db_set("claim_status", "Cancelled", update_modified=False)
