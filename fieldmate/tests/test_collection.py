"""Collections, and the one question that decides where the money goes.

    collected from a shop        -> the distributor's money  -> posts nothing, ever
    collected from a distributor -> our money                -> posts on deposit confirmation

ADR-025. The rep's hands look identical in both cases — same person, same receipt book, same
satchel — so the tests here are mostly about proving the app can still tell them apart.

Gate 6 criterion 2 is asserted as a negative, like the two before it: **no Payment Entry exists
before deposit confirmation**, and a rep cannot make one directly. A test that only checks the
FieldMate Collection looks fine while the books are being credited for money we never earned.
"""

import frappe
from frappe.utils import add_days, today

from fieldmate.services import collection as collection_service
from fieldmate.tests.test_order import OrderFixture


class CollectionFixture(OrderFixture):
	def tearDown(self):
		frappe.set_user("Administrator")
		self.wipe_since_setup("FieldMate Collection Deposit", "FieldMate Collection",
		                      "FieldMate Outstanding Snapshot")
		super().tearDown()

	def collect(self, amount=1000, party_type="Outlet", **extra):
		payload = {
			"party_type": party_type,
			"outlet": self.outlet.name if party_type == "Outlet" else None,
			"distributor": self.distributor.name,
			"amount": amount,
			"mode": "Cash",
			"client_uuid": self.uid("COL"),
		}
		payload.update(extra)
		return self.as_rep(collection_service.create, payload, self.rep.name)

	def manager(self):
		"""Somebody other than the rep, because a deposit cannot be confirmed by its declarer."""
		user = frappe.get_doc({
			"doctype": "User", "email": f"{self.uid('mgr')}@fieldmate.test",
			"first_name": "Manager", "send_welcome_email": 0,
			"roles": [{"role": "FieldMate Area Manager"}],
		}).insert(ignore_permissions=True)
		self.track("User", user.name)
		return user.name


class TestWhoTheMoneyBelongsTo(CollectionFixture):
	def test_cash_taken_at_a_shop_is_the_distributors(self):
		result = self.collect(party_type="Outlet")
		self.assertEqual(result["party"], self.outlet.name)
		self.assertFalse(result["posts_to_ledger"], "a shop owes its distributor, not us")
		self.assertEqual(
			frappe.db.get_value("FieldMate Collection", result["name"], "distributor"),
			self.distributor.name,
			"filled from the shop - the rep knows the counter, not the ledger behind it",
		)

	def test_money_from_a_distributor_is_ours(self):
		result = self.collect(party_type="Distributor")
		self.assertEqual(result["party"], self.distributor.name)
		self.assertTrue(result["posts_to_ledger"])

	def test_the_question_is_asked_in_one_place(self):
		self.assertFalse(collection_service.ours("Outlet"))
		self.assertTrue(collection_service.ours("Distributor"))


class TestNothingPostsWhenMoneyIsTaken(CollectionFixture):
	"""Gate 6 criterion 2, first half."""

	def test_recording_a_shop_collection_creates_no_payment_entry(self):
		before = frappe.db.count("Payment Entry")
		result = self.collect(party_type="Outlet")

		self.assertIsNone(result["payment_entry"])
		self.assertEqual(frappe.db.count("Payment Entry"), before)

	def test_recording_a_distributor_collection_creates_no_payment_entry_either(self):
		"""Even though this one is ours. The money has not arrived anywhere yet - it is in a
		satchel."""
		before = frappe.db.count("Payment Entry")
		result = self.collect(party_type="Distributor")

		self.assertIsNone(result["payment_entry"])
		self.assertEqual(frappe.db.count("Payment Entry"), before,
		                 "nothing posts until a deposit is confirmed")

	def test_a_rep_holds_no_permission_on_payment_entry_at_all(self):
		"""Gate 6 criterion 2, second half. The endpoint guard is belt; this is braces."""
		frappe.set_user(self.rep.user)
		try:
			self.assertFalse(frappe.has_permission("Payment Entry", "create"))
			self.assertFalse(frappe.has_permission("Payment Entry", "write"))
		finally:
			frappe.set_user("Administrator")


class TestTheReceipt(CollectionFixture):
	def test_every_collection_gets_a_number_the_shopkeeper_can_hold(self):
		result = self.collect()
		self.assertTrue(result["receipt_no"], "a receipt with no number settles no argument")

	def test_two_collections_never_share_a_number(self):
		"""Issued server-side for exactly this reason: two phones offline in one market would
		otherwise hand out the same number."""
		first, second = self.collect(), self.collect()
		self.assertNotEqual(first["receipt_no"], second["receipt_no"])

	def test_a_cheque_without_its_number_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.collect(mode="Cheque")
		self.assertIn("number", str(ctx.exception).lower())

	def test_a_collection_of_nothing_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.collect(amount=0)


class TestAllocatingAcrossBills(CollectionFixture):
	def test_money_against_no_particular_bill_is_named_rather_than_spread(self):
		"""Ordinary at a kirana counter. Not an error, but it has to be visible - a rep who meant
		it against one bill and an accountant who applied it to another is unsettleable later."""
		result = self.collect(amount=1000, allocations=[
			{"reference_type": "FieldMate Order", "reference_name": None,
			 "bill_no": "INV-1", "allocated_amount": 600},
		])
		self.assertEqual(result["allocated_amount"], 600)
		self.assertEqual(result["unallocated_amount"], 400)

	def test_allocating_more_than_was_collected_is_refused(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.collect(amount=500, allocations=[
				{"reference_type": "FieldMate Order", "bill_no": "INV-1",
				 "allocated_amount": 900},
			])
		self.assertIn("one of the two is wrong", str(ctx.exception).lower())


class TestWhatAShopOwes(CollectionFixture):
	def test_an_order_on_credit_becomes_outstanding(self):
		self.book(qty=20)
		position = self.as_rep(collection_service.outstanding_for, self.outlet.name, self.rep.name)

		self.assertEqual(position["outstanding"], 2000.0)
		self.assertEqual(len(position["bills"]), 1)
		self.assertEqual(position["source"], "Soft Ledger",
		                 "nobody else holds this figure - the distributor billed the shop")

	def test_an_order_paid_at_the_door_was_never_outstanding(self):
		self.book(qty=20, payment_term="Cash on Delivery")
		position = self.as_rep(collection_service.outstanding_for, self.outlet.name, self.rep.name)
		self.assertEqual(position["outstanding"], 0.0)

	def test_a_collection_reduces_what_the_shop_owes(self):
		order = self.book(qty=20)
		self.collect(amount=500, allocations=[
			{"reference_type": "FieldMate Order", "reference_name": order["name"],
			 "allocated_amount": 500},
		])

		position = self.as_rep(collection_service.outstanding_for, self.outlet.name, self.rep.name)
		self.assertEqual(position["outstanding"], 1500.0)

	def test_a_shop_with_no_limit_set_is_not_a_shop_with_no_room(self):
		"""The two read identically as 0 and mean opposite things."""
		position = self.as_rep(collection_service.outstanding_for, self.outlet.name, self.rep.name)
		self.assertIsNone(position["headroom"])


class TestDepositing(CollectionFixture):
	def declare(self, *collections, **extra):
		payload = {"collections": [c["name"] for c in collections],
		           "reference_no": "CDM-8849201", "channel": "Cash Deposit Machine",
		           "client_uuid": self.uid("DEP")}
		payload.update(extra)
		return self.as_rep(collection_service.declare_deposit, payload, self.rep.name)

	def test_declaring_a_deposit_still_posts_nothing(self):
		"""Gate 6 criterion 2. The rep saying where the money went is not the money arriving."""
		before = frappe.db.count("Payment Entry")
		self.declare(self.collect(party_type="Distributor", amount=5000))

		self.assertEqual(frappe.db.count("Payment Entry"), before,
		                 "no Payment Entry exists before deposit confirmation")

	def test_a_declared_deposit_marks_its_collections(self):
		collection = self.collect(amount=1200)
		deposit = self.declare(collection)

		self.assertEqual(deposit["status"], "Declared")
		self.assertEqual(deposit["total_amount"], 1200.0)
		self.assertEqual(
			frappe.db.get_value("FieldMate Collection", collection["name"], "status"), "Deposited"
		)

	def test_only_the_part_that_was_ours_is_counted_as_ours(self):
		shop = self.collect(party_type="Outlet", amount=1000)
		dist = self.collect(party_type="Distributor", amount=4000)
		deposit = self.declare(shop, dist)

		self.assertEqual(deposit["total_amount"], 5000.0)
		self.assertEqual(deposit["ours_amount"], 4000.0,
		                 "the shop's thousand was the distributor's all along")

	def test_a_rep_cannot_confirm_their_own_deposit(self):
		"""A declaration somebody can confirm themselves is a declaration, not a control."""
		deposit = self.declare(self.collect(party_type="Distributor", amount=3000))

		frappe.set_user(self.rep.user)
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				collection_service.confirm_deposit(deposit["name"])
			self.assertIn("declared it", str(ctx.exception))
		finally:
			frappe.set_user("Administrator")

	def test_confirming_posts_only_the_distributors_money(self):
		shop = self.collect(party_type="Outlet", amount=1000)
		dist = self.collect(party_type="Distributor", amount=4000)
		deposit = self.declare(shop, dist)

		before = frappe.db.count("Payment Entry")
		collection_service.confirm_deposit(deposit["name"], confirmed_by=self.manager())

		self.assertEqual(frappe.db.count("Payment Entry"), before + 1,
		                 "one entry, for the one collection that was ours")
		self.assertIsNone(
			frappe.db.get_value("FieldMate Collection", shop["name"], "payment_entry"),
			"a shop collection never posts, confirmed or not",
		)
		self.assertTrue(
			frappe.db.get_value("FieldMate Collection", dist["name"], "payment_entry")
		)
		self.assertEqual(
			frappe.db.get_value("FieldMate Collection", shop["name"], "status"), "Cleared",
			"it is still accounted for, it simply reached no ledger of ours",
		)

	def test_confirming_twice_does_not_pay_twice(self):
		deposit = self.declare(self.collect(party_type="Distributor", amount=4000))
		manager = self.manager()

		collection_service.confirm_deposit(deposit["name"], confirmed_by=manager)
		before = frappe.db.count("Payment Entry")
		collection_service.confirm_deposit(deposit["name"], confirmed_by=manager)

		self.assertEqual(frappe.db.count("Payment Entry"), before)


class TestCashInHand(CollectionFixture):
	def test_the_satchel_counts_both_kinds_of_money(self):
		"""The rep is equally liable for both and equally likely to be robbed."""
		self.collect(party_type="Outlet", amount=1000)
		self.collect(party_type="Distributor", amount=4000)

		position = self.as_rep(collection_service.undeposited, self.rep.name)
		self.assertEqual(position["total_amount"], 5000.0)
		self.assertEqual(position["ours_amount"], 4000.0)
		self.assertEqual(position["count"], 2)

	def test_money_older_than_the_threshold_is_flagged(self):
		self.collect(amount=1000, collection_date=add_days(today(), -5))
		position = self.as_rep(collection_service.undeposited, self.rep.name)

		self.assertTrue(position["is_overdue"])
		self.assertGreaterEqual(position["oldest_days"], 5)

	def test_a_deposited_collection_leaves_the_satchel(self):
		collection = self.collect(amount=1000)
		self.as_rep(collection_service.declare_deposit, {
			"collections": [collection["name"]], "reference_no": "X-1",
			"client_uuid": self.uid("DEP"),
		}, self.rep.name)

		position = self.as_rep(collection_service.undeposited, self.rep.name)
		self.assertEqual(position["count"], 0)


class TestABouncedCheque(CollectionFixture):
	def test_a_bounced_shop_cheque_restores_what_the_shop_owed(self):
		order = self.book(qty=20)
		collection = self.collect(
			amount=500, mode="Cheque", instrument_no="004921",
			allocations=[{"reference_type": "FieldMate Order",
			              "reference_name": order["name"], "allocated_amount": 500}],
		)

		after_paying = self.as_rep(collection_service.outstanding_for, self.outlet.name,
		                           self.rep.name)
		self.assertEqual(after_paying["outstanding"], 1500.0)

		collection_service.bounce(collection["name"], "insufficient funds")

		back = self.as_rep(collection_service.outstanding_for, self.outlet.name, self.rep.name)
		self.assertEqual(back["outstanding"], 2000.0,
		                 "a cheque that came back never paid anything")

	def test_a_bounced_distributor_cheque_cancels_its_payment_entry(self):
		collection = self.collect(party_type="Distributor", amount=4000,
		                          mode="Cheque", instrument_no="893102")
		deposit = self.as_rep(collection_service.declare_deposit, {
			"collections": [collection["name"]], "reference_no": "X-2",
			"client_uuid": self.uid("DEP"),
		}, self.rep.name)
		collection_service.confirm_deposit(deposit["name"], confirmed_by=self.manager())

		entry = frappe.db.get_value("FieldMate Collection", collection["name"], "payment_entry")
		self.assertTrue(entry)

		collection_service.bounce(collection["name"], "signature mismatch")

		self.assertEqual(frappe.db.get_value("Payment Entry", entry, "docstatus"), 2,
		                 "the receivable has to come back too")
		self.assertIn(entry,
		              frappe.db.get_value("FieldMate Collection", collection["name"], "remarks"),
		              "the link is released to allow the cancel, so the trail lives in the remark")
		self.assertEqual(
			frappe.db.get_value("FieldMate Collection", collection["name"], "status"), "Bounced"
		)

	def test_bouncing_twice_is_not_an_error(self):
		"""A rep pressing a button twice, not something worth showing anybody."""
		collection = self.collect(amount=500, mode="Cheque", instrument_no="111")
		collection_service.bounce(collection["name"])
		result = collection_service.bounce(collection["name"])
		self.assertEqual(result["status"], "Bounced")
