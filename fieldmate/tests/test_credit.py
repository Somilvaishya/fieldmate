from unittest.mock import patch

import frappe
from frappe.utils import flt

from fieldmate.services import credit as credit_service
from fieldmate.services import settings as settings_service
from fieldmate.tests.test_outlet import OutletFixture


class CreditFixture(OutletFixture):
	"""Credit numbers have to be built from nothing.

	Two things on a real site would otherwise answer for us. ERPNext resolves a limit down a
	chain - the Customer, then its Customer Group, then the Company - so a limit somebody
	configured on a shared group or on the company would decide a test that deliberately set
	none. Each test therefore gets a customer group of its own, and the company limit is parked
	at zero and put back afterwards.

	Outstanding is the other one. It is the live ledger, and posting real invoices here would
	test ERPNext's billing rather than our arithmetic, so it is stood in for. What the ledger
	read itself returns is covered in test_compat.
	"""

	SETTINGS = (
		"enable_order_booking",
		"enable_van_sales",
		"default_sales_mode",
		"block_order_on_credit_breach",
		"allow_credit_override",
		"default_company",
	)

	def setUp(self):
		super().setUp()
		self._group = None

		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no company on this site")

		self._company_limit = frappe.db.get_value("Company", self.company, "credit_limit")
		self._set_company_limit(0)

		doc = self.fresh_settings()
		self._settings = {key: doc.get(key) for key in self.SETTINGS}
		self.apply_settings(default_company=self.company)

		self.rep = self.make_field_user(company=self.company)

	def tearDown(self):
		self.apply_settings(**self._settings)
		self._set_company_limit(self._company_limit)
		super().tearDown()

	# ---------------------------------------------------------------- fixtures

	def leaf_customer_group(self) -> str:
		"""A group of our own, so nobody else's credit limit answers for this test."""
		if not self._group:
			root = frappe.db.get_value(
				"Customer Group",
				{"is_group": 1, "parent_customer_group": ("in", ("", None))},
				"name",
			)
			doc = frappe.get_doc({
				"doctype": "Customer Group",
				"customer_group_name": self.uid("CG"),
				"parent_customer_group": root,
				"is_group": 0,
			}).insert(ignore_permissions=True)
			self.track("Customer Group", doc.name)
			self._group = doc.name
		return self._group

	def _set_company_limit(self, amount) -> None:
		frappe.db.set_value("Company", self.company, "credit_limit", flt(amount))
		# get_credit_limit reads the company through the document cache, which db.set_value on
		# its own does not always reach.
		frappe.clear_document_cache("Company", self.company)

	def set_credit_limit(self, customer: str, amount) -> None:
		doc = frappe.get_doc("Customer", customer)
		doc.append("credit_limits", {"company": self.company, "credit_limit": flt(amount)})
		doc.save(ignore_permissions=True)

	def owing(self, amount):
		"""Stand in for the ledger for the length of one call."""
		return patch.object(credit_service.compat, "get_outstanding", return_value=flt(amount))

	def van_rep(self):
		warehouse = frappe.db.get_value("Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not warehouse:
			self.skipTest("no warehouse on this site to stand in for a vehicle")
		return self.make_field_user(
			company=self.company, sales_mode="Van Sales", vehicle_warehouse=warehouse
		)


class TestBillingParty(CreditFixture):
	def test_order_booking_bills_the_distributor(self):
		outlet = self.make_outlet()
		party = credit_service.billing_party(outlet.name, self.rep.name)
		self.assertEqual(party["party"], outlet.distributor)
		self.assertEqual(party["mode"], settings_service.ORDER_BOOKING)
		self.assertEqual(party["company"], self.company)

	def test_van_sales_bills_the_shop(self):
		"""The one mode where FieldMate Outlet.customer is live (ADR-016)."""
		self.apply_settings(enable_van_sales=1)
		shop_account = self.make_distributor()
		outlet = self.make_outlet(customer=shop_account)
		rep = self.van_rep()

		party = credit_service.billing_party(outlet.name, rep.name)
		self.assertEqual(party["party"], shop_account)
		self.assertEqual(party["mode"], settings_service.VAN_SALES)
		self.assertNotEqual(party["party"], outlet.distributor)

	def test_the_outlet_document_asks_the_same_question(self):
		"""The controller delegates, so there is one branch and not two that drift apart."""
		outlet = self.make_outlet()
		self.assertEqual(
			outlet.billing_party(), credit_service.billing_party(outlet.name)["party"]
		)

	def test_a_van_shop_with_no_account_has_nobody_to_bill(self):
		self.apply_settings(enable_van_sales=1)
		outlet = self.make_outlet()
		rep = self.van_rep()

		result = credit_service.check(outlet.name, rep.name, 500)
		self.assertIsNone(result["party"])
		self.assertTrue(result["blocks"])
		self.assertIn("billing account", result["message"])


class TestCreditCheck(CreditFixture):
	def setUp(self):
		super().setUp()
		self.outlet = self.make_outlet()
		self.party = self.outlet.distributor

	def check(self, order_value, outstanding=0):
		with self.owing(outstanding):
			return credit_service.check(self.outlet.name, self.rep.name, order_value)

	def test_a_party_with_no_limit_has_no_headroom_to_run_out_of(self):
		"""Currency columns default to 0, so an unset limit reads as zero. Treating that as a
		ceiling would block every order for every new distributor on their first day."""
		result = self.check(500000)
		self.assertEqual(result["status"], credit_service.NO_LIMIT_SET)
		self.assertIsNone(result["headroom"])
		self.assertFalse(result["blocks"])
		self.assertFalse(result["can_override"])

	def test_an_order_that_exactly_meets_the_limit_is_within_it(self):
		self.set_credit_limit(self.party, 100000)
		result = self.check(60000, outstanding=40000)
		self.assertEqual(result["status"], credit_service.WITHIN_LIMIT)
		self.assertEqual(result["headroom"], 60000)
		self.assertFalse(result["blocks"])

	def test_one_rupee_over_the_limit_is_a_breach(self):
		self.set_credit_limit(self.party, 100000)
		result = self.check(60001, outstanding=40000)
		self.assertEqual(result["status"], credit_service.BREACH)
		self.assertEqual(result["exposure"], 100001)
		self.assertTrue(result["blocks"])

	def test_a_breach_blocks_only_while_settings_say_so(self):
		"""Recording a breach and refusing an order are two separate decisions (ADR-017)."""
		self.set_credit_limit(self.party, 100000)
		self.apply_settings(block_order_on_credit_breach=0)
		result = self.check(100001)
		self.assertEqual(result["status"], credit_service.BREACH)
		self.assertFalse(result["blocks"])
		self.assertFalse(result["can_override"])

	def test_an_override_is_offered_only_when_something_is_held(self):
		self.set_credit_limit(self.party, 100000)
		self.apply_settings(block_order_on_credit_breach=1, allow_credit_override=1)
		self.assertTrue(self.check(100001)["can_override"])

		self.apply_settings(allow_credit_override=0)
		held = self.check(100001)
		self.assertTrue(held["blocks"])
		self.assertFalse(held["can_override"])

	def test_booked_orders_count_and_not_only_invoices(self):
		"""A rep can book a month of business before any of it becomes an invoice."""
		with patch.object(credit_service.compat, "get_outstanding", return_value=0) as ledger:
			credit_service.check(self.outlet.name, self.rep.name, 100)
		self.assertTrue(ledger.call_args.kwargs.get("include_open_orders"))

	def test_the_message_is_something_a_rep_can_read_out(self):
		self.set_credit_limit(self.party, 100000)
		message = self.check(150000)["message"]
		self.assertIn(frappe.db.get_value("Customer", self.party, "customer_name"), message)
		self.assertIn("credit limit", message)
		self.assertTrue(message.endswith("."))
		self.assertNotIn("FieldMate", message)


class TestVanSalesCredit(CreditFixture):
	"""Two sales models means two paths through the same money, and an untested second path is
	where the money goes missing (ADR-016)."""

	def setUp(self):
		super().setUp()
		self.apply_settings(enable_van_sales=1)
		self.shop_account = self.make_distributor()
		self.outlet = self.make_outlet(customer=self.shop_account)
		self.rep = self.van_rep()

	def check(self, order_value, outstanding=0, rep=None):
		with self.owing(outstanding):
			return credit_service.check(self.outlet.name, (rep or self.rep).name, order_value)

	def test_the_shops_own_limit_is_what_binds(self):
		"""A van route is run on a per-shop figure set at the counter, not on the distributor."""
		self.set_credit_limit(self.shop_account, 500000)
		self.outlet.db_set("credit_limit", 20000, update_modified=False)

		result = self.check(25000)
		self.assertEqual(result["limit"], 20000)
		self.assertEqual(result["status"], credit_service.BREACH)

	def test_a_shop_without_its_own_limit_falls_back_to_its_customer(self):
		self.set_credit_limit(self.shop_account, 100000)
		self.assertEqual(self.check(100000)["status"], credit_service.WITHIN_LIMIT)
		self.assertEqual(self.check(100001)["status"], credit_service.BREACH)

	def test_the_same_cart_is_checked_against_a_different_party_in_each_mode(self):
		self.set_credit_limit(self.shop_account, 100000)
		self.set_credit_limit(self.outlet.distributor, 10000)

		van = self.check(50000)
		self.assertEqual(van["party"], self.shop_account)
		self.assertEqual(van["status"], credit_service.WITHIN_LIMIT)

		booking = self.check(50000, rep=self.rep_booking())
		self.assertEqual(booking["party"], self.outlet.distributor)
		self.assertEqual(booking["status"], credit_service.BREACH)

	def rep_booking(self):
		return self.make_field_user(company=self.company, sales_mode="Order Booking")
