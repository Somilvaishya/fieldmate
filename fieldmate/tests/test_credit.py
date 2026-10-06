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
		"enable_secondary_sales",
		"enable_primary_sales",
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
class TestBillingParty(CreditFixture):
	def test_order_booking_bills_the_distributor(self):
		outlet = self.make_outlet()
		party = credit_service.billing_party(outlet.name, self.rep.name)
		self.assertEqual(party["party"], outlet.distributor)
		self.assertEqual(party["mode"], settings_service.ORDER_BOOKING)
		self.assertEqual(party["company"], self.company)
	def test_the_outlet_document_asks_the_same_question(self):
		"""The controller delegates, so there is one branch and not two that drift apart."""
		outlet = self.make_outlet()
		self.assertEqual(
			outlet.billing_party(), credit_service.billing_party(outlet.name)["party"]
		)
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

class TestTheShopsOwnCreditIsMeasuredToo(CreditFixture):
	"""A secondary sale has two debts behind it: the shop owes its distributor, and the
	distributor owes us. Only the second was ever measured, so a kirana ten thousand overdue with
	its distributor read as perfectly clear - and the distributor, the one who would refuse,
	found out when the order reached their queue."""

	def setUp(self):
		super().setUp()
		self.outlet = self.make_outlet()
		self.set_credit_limit(self.outlet.distributor, 1_000_000)

	def owes_its_distributor(self, outstanding, overdue=0):
		"""Stand in for the soft ledger. What it counts is `test_collection`'s business."""
		return patch.object(
			credit_service, "_shop_position",
			return_value={"outlet": self.outlet.name, "outlet_name": self.outlet.outlet_name,
			              "outstanding": flt(outstanding), "overdue": flt(overdue),
			              "credit_limit": flt(self.outlet.credit_limit), "headroom": None})

	def set_shop_limit(self, amount):
		frappe.db.set_value("FieldMate Outlet", self.outlet.name, "credit_limit", amount,
		                    update_modified=False)
		frappe.clear_document_cache("FieldMate Outlet", self.outlet.name)
		self.outlet.reload()

	def test_a_shop_with_no_limit_is_not_measured(self):
		"""A Currency column is NOT NULL DEFAULT 0, so a zero cannot be told from a blank, and
		treating the default as a ceiling would put every shop over its limit on day one."""
		self.set_shop_limit(0)
		with self.owing(0), self.owes_its_distributor(50_000):
			answer = credit_service.check(self.outlet.name, self.rep.name, 1_000)
		self.assertEqual(answer["shop"]["status"], credit_service.NO_LIMIT_SET)
		self.assertNotEqual(answer["status"], credit_service.BREACH)

	def test_a_shop_within_its_limit_passes(self):
		self.set_shop_limit(10_000)
		with self.owing(0), self.owes_its_distributor(2_000):
			answer = credit_service.check(self.outlet.name, self.rep.name, 1_000)
		self.assertEqual(answer["shop"]["status"], credit_service.WITHIN_LIMIT)
		self.assertEqual(answer["shop"]["exposure"], 3_000)

	def test_a_shop_over_its_limit_breaches_even_when_the_distributor_is_clear(self):
		"""The whole point. The distributor has a million of headroom with us and the shop is
		still over with them."""
		self.set_shop_limit(5_000)
		with self.owing(0), self.owes_its_distributor(4_500):
			answer = credit_service.check(self.outlet.name, self.rep.name, 1_000)

		self.assertEqual(answer["shop"]["status"], credit_service.BREACH)
		self.assertEqual(answer["status"], credit_service.BREACH,
		                 "a caller reading one field must not be told 'within limit'")
		self.assertIn("over the limit their distributor allows", answer["message"])

	def test_the_message_says_whose_number_it_is(self):
		"""The distributor's figure comes out of a ledger; this one is our own arithmetic over
		orders and collections, and a rep arguing it across a counter has to know which."""
		self.set_shop_limit(5_000)
		with self.owing(0), self.owes_its_distributor(4_500):
			answer = credit_service.check(self.outlet.name, self.rep.name, 1_000)
		self.assertIn("our own count", answer["message"])
		self.assertTrue(answer["shop"]["is_our_own_count"])

	def test_the_distributors_own_breach_still_wins_the_message(self):
		"""Both over: the top-level answer stays the one ERPNext can prove."""
		# Edited rather than appended. ERPNext allows one credit-limit row per company, and
		# `set_credit_limit` appends - setUp has already put one there.
		doc = frappe.get_doc("Customer", self.outlet.distributor)
		doc.credit_limits[0].credit_limit = 1_000
		doc.save(ignore_permissions=True)
		self.set_shop_limit(5_000)
		with self.owing(900), self.owes_its_distributor(4_500):
			answer = credit_service.check(self.outlet.name, self.rep.name, 1_000)
		self.assertEqual(answer["status"], credit_service.BREACH)
		self.assertEqual(answer["shop"]["status"], credit_service.BREACH)
		self.assertNotIn("our own count", answer["message"],
		                 "the provable breach is the one to read out")

	def test_a_primary_sale_has_no_second_level(self):
		"""There is only one debt there: the party we bill is the party being sold to."""
		customer = self.outlet.distributor
		frappe.db.set_value("Customer", customer, {"fm_tier": "Distributor",
		                                           "fm_buys_from": "Company"},
		                    update_modified=False)
		frappe.clear_document_cache("Customer", customer)
		with self.owing(0):
			answer = credit_service.check(customer, self.rep.name, 1_000, "Customer")
		self.assertIsNone(answer["shop"])


class TestOneCreditAnswerForTheWholeApp(CreditFixture):
	"""There were three ways of asking - `credit.check` for the order path,
	`collection.outstanding_for` for the money screens, and `compat.get_credit_status` for the
	shop screen - and they disagreed by construction: the third measured the distributor and the
	screen labelled it as the shop's. `outlet.detail` now reads the same verdict as the order."""

	def setUp(self):
		super().setUp()
		self.outlet = self.make_outlet()
		self.set_credit_limit(self.outlet.distributor, 50_000)

	def test_the_shop_screen_and_the_order_path_answer_with_the_same_figures(self):
		from fieldmate.services import outlet as outlet_service

		with self.owing(12_000):
			detail = outlet_service.detail(self.outlet.name)
			verdict = credit_service.check(self.outlet.name, self.rep.name, 0)

		self.assertEqual(detail["credit"]["credit_limit"], verdict["limit"])
		self.assertEqual(detail["credit"]["outstanding"], verdict["outstanding"])
		self.assertEqual(detail["credit"]["status"], verdict["status"])

	def test_the_keys_three_screens_already_read_are_still_there(self):
		"""Additive on purpose. A phone that has not been updated goes on working."""
		from fieldmate.services import outlet as outlet_service

		with self.owing(12_000):
			credit = outlet_service.detail(self.outlet.name)["credit"]
		for key in ("credit_limit", "outstanding", "headroom", "unlimited"):
			self.assertIn(key, credit)
		self.assertFalse(credit["unlimited"], "a limit is set, so this is not unlimited")

	def test_the_shop_screen_can_now_see_the_shops_own_debt(self):
		"""The figure no screen could reach before: what this shop owes its distributor."""
		from fieldmate.services import outlet as outlet_service

		with self.owing(0):
			credit = outlet_service.detail(self.outlet.name)["credit"]
		self.assertIn("shop", credit)
		self.assertEqual(credit["shop"]["outlet"], self.outlet.name)
		self.assertTrue(credit["shop"]["is_our_own_count"],
		                "said plainly wherever it is shown")
