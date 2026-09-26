"""Expense claims, and the one rule the whole document exists to hold.

**The distance is the server's, the claim is the rep's, and the gap is the manager's.**

A rep may always file - somebody who walked a market with no signal has a real claim and a thin
trail. What they cannot do is approve their own excess, and the excess has to be measured rather
than guessed at. Gate 7 criterion 4 is that sentence, and so is most of this file.
"""

import frappe
from frappe.utils import add_days, flt, today

from fieldmate.services import expense as expense_service
from fieldmate.tests.test_order import OrderFixture


class ExpenseFixture(OrderFixture):
	def setUp(self):
		super().setUp()
		self.apply_settings(
			travel_rate_per_km=3.5,
			daily_food_allowance=250,
			daily_stay_allowance=0,
			expense_receipt_required_above=500,
			expense_distance_tolerance_pct=10,
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("FieldMate Expense Claim", pluck="name"):
			try:
				doc = frappe.get_doc("FieldMate Expense Claim", name)
				if doc.docstatus == 1:
					doc.flags.ignore_permissions = True
					doc.db_set("claim_status", "Approved", update_modified=False)
					doc.cancel()
				frappe.delete_doc("FieldMate Expense Claim", name, force=True,
				                  ignore_permissions=True)
			except Exception:
				pass
		for name in frappe.get_all("FieldMate Location Trail",
		                           filters={"field_user": self.rep.name}, pluck="name"):
			try:
				frappe.delete_doc("FieldMate Location Trail", name, force=True,
				                  ignore_permissions=True)
			except Exception:
				pass
		frappe.db.commit()
		super().tearDown()

	def lay_a_trail(self, km=48, on=None):
		"""Two pings the right distance apart, so the trail reports a real number.

		Roughly a hundredth of a degree of latitude per 1.11 km, which is close enough for a
		test about arithmetic rather than about geodesy.
		"""
		from fieldmate.services import trail as trail_service

		on = on or today()
		degrees = km / 111.0
		# `lat`, `lon`, `t` - the short keys the device actually sends, not the column names.
		# `trail_date` matters too: append defaults to today, so a trail laid for yesterday
		# without it lands on the wrong day and the claim reads zero.
		trail_service.append(self.rep.name, [
			{"lat": 28.6, "lon": 77.2, "t": f"{on} 09:00:00"},
			{"lat": 28.6 + degrees, "lon": 77.2, "t": f"{on} 17:00:00"},
		], trail_date=on)
		return trail_service.distance_for(self.rep.name, on)

	def file(self, **extra):
		payload = {"claim_date": today(), "expense_type": "Travel"}
		payload.update(extra)
		return self.as_rep(expense_service.create, payload, self.rep.name)

	def file_with_bill(self, **extra):
		"""A claim big enough to need a receipt, with one attached.

		The tests about the distance rule kept tripping the receipt rule instead: 150 km at
		3.50 is 525, which is over the threshold, and the claim was refused for the wrong
		reason. A rep claiming that much does attach a bill, so the fixture does too - rather
		than raising the threshold, which would have quietly stopped testing it.
		"""
		return self.file(receipt="/files/fixture-receipt.jpg", **extra)

	def manager(self):
		user = frappe.get_doc({
			"doctype": "User", "email": f"{self.uid('mgr')}@fieldmate.test",
			"first_name": "Manager", "send_welcome_email": 0,
			"roles": [{"role": "FieldMate Area Manager"}],
		}).insert(ignore_permissions=True)
		self.track("User", user.name)
		return user.name


class TestTheDistanceIsTheServers(ExpenseFixture):
	def test_the_claim_reads_the_trail(self):
		"""Gate 7 criterion 4, first half."""
		recorded = self.lay_a_trail(km=48)
		claim = self.file()

		self.assertAlmostEqual(claim["trail_distance_km"], round(recorded, 2), places=1)
		self.assertAlmostEqual(claim["claimed_distance_km"], claim["trail_distance_km"],
		                       places=2, msg="an unstated claim is the trail")

	def test_a_distance_the_phone_sends_is_not_the_trail(self):
		"""A device that could state its own mileage is one that could invent it."""
		self.lay_a_trail(km=20)
		claim = self.file(claimed_distance_km=500)

		self.assertLess(claim["trail_distance_km"], 30,
		                "the trail must be the server's own reading")
		self.assertEqual(claim["claimed_distance_km"], 500, "what the rep said is kept")
		self.assertTrue(claim["needs_approval"])

	def test_the_amount_is_distance_times_rate(self):
		self.lay_a_trail(km=48)
		claim = self.file()
		self.assertAlmostEqual(
			claim["computed_amount"],
			round(claim["claimed_distance_km"] * 3.5, 2), places=2)
		self.assertEqual(claim["rate_per_km"], 3.5)

	def test_the_rate_is_frozen_at_the_moment_of_claiming(self):
		"""A rate changed before approval must not restate what the rep was shown."""
		self.lay_a_trail(km=48)
		claim = self.file()
		self.apply_settings(travel_rate_per_km=9.0)

		doc = frappe.get_doc("FieldMate Expense Claim", claim["name"])
		doc.flags.ignore_permissions = True
		doc.save()

		self.assertEqual(flt(doc.rate_per_km), 3.5)

	def test_no_rate_at_all_refuses_rather_than_paying_zero(self):
		self.apply_settings(travel_rate_per_km=0)
		self.lay_a_trail(km=10)
		with self.assertRaises(frappe.ValidationError):
			self.file()


class TestWhoSignsForTheGap(ExpenseFixture):
	def test_a_claim_matching_the_trail_needs_nobody(self):
		self.lay_a_trail(km=48)
		claim = self.file()
		self.assertFalse(claim["needs_approval"])

		submitted = self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)
		self.assertEqual(submitted["claim_status"], "Approved")

	def test_a_little_over_is_within_tolerance(self):
		"""A trail drops pings in a basement. Claiming 5% more is ordinary, not suspicious."""
		recorded = self.lay_a_trail(km=100)
		claim = self.file(claimed_distance_km=round(recorded * 1.05, 2))
		self.assertFalse(claim["needs_approval"], claim["approval_reason"])

	def test_a_lot_over_waits_for_a_manager(self):
		"""Gate 7 criterion 4, second half: a rep cannot edit upward without approval."""
		recorded = self.lay_a_trail(km=100)
		claim = self.file_with_bill(claimed_distance_km=round(recorded * 1.5, 2))

		self.assertTrue(claim["needs_approval"])
		self.assertIn("more than the trail", claim["approval_reason"])

		submitted = self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)
		self.assertEqual(submitted["claim_status"], "Pending Approval")

	def test_a_day_with_no_trail_at_all_waits(self):
		claim = self.file(claimed_distance_km=30)
		self.assertTrue(claim["needs_approval"])
		self.assertIn("no GPS trail", claim["approval_reason"])

	def test_a_rep_cannot_approve_their_own_claim(self):
		"""The whole point. Filing over the trail and signing it off is stating your own mileage."""
		recorded = self.lay_a_trail(km=100)
		claim = self.file_with_bill(claimed_distance_km=round(recorded * 2, 2))
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)

		frappe.set_user(self.rep.user)
		try:
			with self.assertRaises(frappe.PermissionError):
				expense_service.approve(claim["name"], "Approved")
		finally:
			frappe.set_user("Administrator")

	def test_a_manager_may_approve_less_than_was_claimed(self):
		recorded = self.lay_a_trail(km=100)
		claim = self.file_with_bill(claimed_distance_km=round(recorded * 2, 2))
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)

		result = expense_service.approve(claim["name"], "Approved",
		                                 approved_amount=100, settle=False)
		self.assertEqual(result["approved_amount"], 100)
		self.assertEqual(result["claim_status"], "Approved")

	def test_more_than_was_claimed_cannot_be_approved(self):
		self.lay_a_trail(km=48)
		claim = self.file()
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)
		with self.assertRaises(frappe.ValidationError):
			expense_service.approve(claim["name"], "Approved",
			                        approved_amount=claim["claimed_amount"] + 500, settle=False)

	def test_a_rejection_needs_a_reason(self):
		self.lay_a_trail(km=100)
		claim = self.file_with_bill(claimed_distance_km=300)
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)
		with self.assertRaises(frappe.ValidationError):
			expense_service.approve(claim["name"], "Rejected")


class TestTheOtherTypes(ExpenseFixture):
	def test_food_is_capped_at_the_daily_allowance(self):
		claim = self.file(expense_type="Food")
		self.assertEqual(claim["allowance_cap"], 250)
		self.assertEqual(claim["claimed_amount"], 250)
		self.assertFalse(claim["needs_approval"])

	def test_over_the_allowance_waits(self):
		claim = self.file(expense_type="Food", claimed_amount=900)
		self.assertTrue(claim["needs_approval"])
		self.assertIn("allowance", claim["approval_reason"])

	def test_a_non_travel_claim_reads_no_trail(self):
		self.lay_a_trail(km=48)
		claim = self.file(expense_type="Food")
		self.assertEqual(claim["trail_distance_km"], 0)
		self.assertEqual(claim["claimed_distance_km"], 0)


class TestFilingRules(ExpenseFixture):
	def test_one_claim_of_a_type_per_day(self):
		"""The second is a mistake, not a second journey."""
		self.lay_a_trail(km=48)
		self.file()
		with self.assertRaises(frappe.ValidationError):
			self.file()

	def test_two_types_on_one_day_are_fine(self):
		self.lay_a_trail(km=48)
		self.file()
		food = self.file(expense_type="Food")
		self.assertEqual(food["expense_type"], "Food")

	def test_a_replayed_push_returns_the_same_claim(self):
		"""A phone that never heard the first answer sends it again."""
		self.lay_a_trail(km=48)
		uuid = self.uid("EXP")
		first = self.file(client_uuid=uuid)
		second = self.file(client_uuid=uuid)
		self.assertEqual(first["name"], second["name"])

	def test_a_big_claim_needs_a_receipt_to_submit(self):
		self.lay_a_trail(km=400)
		claim = self.file()
		self.assertTrue(claim["receipt_required"], claim["claimed_amount"])
		with self.assertRaises(frappe.ValidationError):
			self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)

	def test_a_claim_for_nothing_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.file(expense_type="Other", claimed_amount=0)

	def test_another_reps_claim_is_refused(self):
		self.lay_a_trail(km=48)
		claim = self.file()
		other = self.make_field_user(territory=self.rep.territory)

		doc = frappe.get_doc("FieldMate Expense Claim", claim["name"])
		with self.assertRaises(frappe.PermissionError):
			expense_service.assert_owner(doc, other.name)


class TestSettlement(ExpenseFixture):
	def test_settling_records_where_it_went(self):
		self.lay_a_trail(km=48)
		claim = self.file()
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)

		result = expense_service.settle_claim(claim["name"])

		self.assertEqual(result["claim_status"], "Settled")
		self.assertTrue(result["settled_on"])

	def test_a_settled_claim_cannot_be_cancelled_underneath_its_payment(self):
		self.lay_a_trail(km=48)
		claim = self.file()
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)
		expense_service.settle_claim(claim["name"])

		doc = frappe.get_doc("FieldMate Expense Claim", claim["name"])
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()

	def test_settling_twice_is_the_same_answer(self):
		self.lay_a_trail(km=48)
		claim = self.file()
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)
		first = expense_service.settle_claim(claim["name"])
		second = expense_service.settle_claim(claim["name"])
		self.assertEqual(first["hrms_expense_claim"], second["hrms_expense_claim"])

	def test_no_gl_entry_is_produced_by_filing_or_approving(self):
		"""FieldMate says what is owed. HR decides when it is payable."""
		before = frappe.db.count("GL Entry")
		self.lay_a_trail(km=48)
		claim = self.file()
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)
		expense_service.settle_claim(claim["name"])
		self.assertEqual(frappe.db.count("GL Entry"), before)


class TestWhatTheRepSees(ExpenseFixture):
	def test_the_estimate_fills_the_screen_without_creating_anything(self):
		self.lay_a_trail(km=48)
		before = frappe.db.count("FieldMate Expense Claim")

		estimate = self.as_rep(expense_service.estimate, self.rep.name, today(), "Travel")

		self.assertGreater(estimate["trail_distance_km"], 40)
		self.assertEqual(estimate["rate_per_km"], 3.5)
		self.assertTrue(estimate["rate_is_set"])
		self.assertEqual(frappe.db.count("FieldMate Expense Claim"), before)

	def test_the_estimate_says_when_a_day_is_already_claimed(self):
		self.lay_a_trail(km=48)
		claim = self.file()
		estimate = self.as_rep(expense_service.estimate, self.rep.name, today(), "Travel")
		self.assertEqual(estimate["already_claimed"], claim["name"])

	def test_the_month_totals_only_count_what_was_agreed(self):
		self.lay_a_trail(km=48)
		claim = self.file()
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)

		mine = self.as_rep(expense_service.mine, self.rep.name)

		self.assertEqual(len(mine["claims"]), 1)
		self.assertGreater(mine["approved_this_month"], 0)
		self.assertEqual(mine["awaiting_decision"], 0)

	def test_an_unagreed_claim_shows_as_waiting_not_as_earned(self):
		recorded = self.lay_a_trail(km=100)
		claim = self.file_with_bill(claimed_distance_km=round(recorded * 2, 2))
		self.as_rep(expense_service.submit_claim, claim["name"], self.rep.name)

		mine = self.as_rep(expense_service.mine, self.rep.name)

		self.assertEqual(mine["approved_this_month"], 0)
		self.assertGreater(mine["awaiting_decision"], 0)

	def test_yesterdays_trail_is_read_for_yesterdays_claim(self):
		"""The day being claimed for, not the day the rep got round to filing it."""
		yesterday = add_days(today(), -1)
		self.lay_a_trail(km=60, on=yesterday)
		claim = self.file(claim_date=yesterday)
		self.assertGreater(claim["trail_distance_km"], 50)
