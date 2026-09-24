"""Orders, and the one thing about them that is easy to get wrong.

A rep booking at a kirana shop is making a **secondary** sale. The distributor delivers it out of
their own stock and bills the shop themselves, so nothing about it belongs in our order book or
our ledger (ADR-023). The build plan originally said the opposite — task 4.9 read "Sales Order
creation in on_submit" — and the tests here exist so that nobody quietly puts it back.

Most of these assert a **negative**, which is unusual and deliberate. "No Sales Order exists" and
"no GL Entry exists" are the actual requirements; a test that only checks the FieldMate Order
looks fine while the company's books are being corrupted behind it.

Everything that a rep does is exercised **as the rep**. Every gate before Phase 3 ran as
Administrator, which hid a defect that made the whole app unusable in the field.
"""

import frappe
from frappe.utils import add_days, today

from fieldmate.services import order as order_service
from fieldmate.services import settings as settings_service
from fieldmate.tests.test_scheme_compile import SchemeFixture


class OrderFixture(SchemeFixture):
	def setUp(self):
		super().setUp()
		self.rep = self.make_field_user(territory=self.territory_for_orders())
		self.outlet = self.make_outlet(territory=self.rep.territory, approval_status="Approved")
		# An order routes to a distributor, so that distributor has to be one we hold a profile
		# for. Building the Customer without the profile would test a shape the real system
		# never has - which is the exact family of bug that shipped three times in Phase 3.
		self.distributor = frappe.get_doc({
			"doctype": "FieldMate Distributor Profile",
			"customer": self.outlet.distributor,
			"territory": self.rep.territory,
		}).insert(ignore_permissions=True)
		self.track("FieldMate Distributor Profile", self.distributor.name)
		self.price_item(self.item, 100)

	def territory_for_orders(self):
		if not getattr(self, "_territory", None):
			self._territory = self.make_territory()
		return self._territory

	def tearDown(self):
		frappe.set_user("Administrator")
		for dt in ("FieldMate Scheme Ledger", "FieldMate Order"):
			for name in frappe.get_all(dt, pluck="name",
			                           filters={"field_user": self.rep.name}):
				try:
					doc = frappe.get_doc(dt, name)
					if doc.docstatus == 1:
						doc.flags.ignore_permissions = True
						doc.cancel()
					frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
				except Exception:
					pass
		frappe.db.commit()
		super().tearDown()

	def cart(self, qty=20):
		return [{"item": self.item, "qty": qty}]

	def as_rep(self, fn, *args, **kwargs):
		frappe.set_user(self.rep.user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def book(self, qty=20, **extra):
		payload = {"outlet": self.outlet.name, "lines": self.cart(qty),
		           "client_uuid": self.uid("ORD")}
		payload.update(extra)
		created = self.as_rep(order_service.create, payload, self.rep.name)
		self.track("FieldMate Order", created["name"])
		return self.as_rep(order_service.submit_order, created["name"])


# --------------------------------------------------------------------------------------
# ADR-023 — the whole point
# --------------------------------------------------------------------------------------


class TestAnOrderIsASecondarySale(OrderFixture):
	def test_submitting_creates_no_sales_order(self):
		"""The single most important assertion in Phase 4.

		A Sales Order here would book revenue on a sale the company did not make, and consume the
		distributor's credit for stock they never asked us for.
		"""
		before = frappe.db.count("Sales Order")
		result = self.book()

		self.assertIsNone(result["sales_order"], "order booking must not raise a Sales Order")
		self.assertEqual(frappe.db.count("Sales Order"), before,
		                 "no Sales Order may be created anywhere by a retailer order")

	def test_submitting_creates_no_gl_entry(self):
		"""Gate 5 criterion 4 in as many words: no secondary sales document produces a GL Entry."""
		before = frappe.db.count("GL Entry")
		self.book()
		self.assertEqual(frappe.db.count("GL Entry"), before,
		                 "a secondary sale must never reach the ledger")

	def test_submitting_routes_the_order_to_the_distributor(self):
		result = self.book()
		self.assertEqual(result["order_status"], "Sent To Distributor")
		self.assertTrue(result["sent_to_distributor_on"], "the hand-off has to be stamped")
		self.assertEqual(result["docstatus"], 1)

	def test_the_order_appears_in_that_distributors_queue(self):
		"""Until the Phase 9 portal ships, this queue is the entire downstream."""
		result = self.book()
		queue = order_service.for_distributor(result["distributor"])
		self.assertIn(result["name"], [row["name"] for row in queue])

	def test_a_rep_can_book_and_submit_their_own_order(self):
		"""A rep holds create and submit-if-owner, never write. Every submit is elevated by the
		server after an ownership check (ADR-004), and nothing here may need Administrator."""
		frappe.set_user(self.rep.user)
		try:
			self.assertTrue(frappe.has_permission("FieldMate Order", "create"))
			self.assertFalse(frappe.has_permission("FieldMate Order", "write"))
		finally:
			frappe.set_user("Administrator")

		result = self.book()
		self.assertEqual(result["docstatus"], 1)

	def test_an_order_belonging_to_another_rep_is_refused(self):
		result = self.book()
		colleague = self.make_field_user(territory=self.rep.territory)
		frappe.db.commit()

		frappe.set_user(colleague.user)
		try:
			with self.assertRaises(frappe.PermissionError):
				order_service.cancel(result["name"])
		finally:
			frappe.set_user("Administrator")


class TestVanSalesIsTheOneException(OrderFixture):
	"""Where we are genuinely the seller, an ERPNext document is correct — and required."""

	def test_the_seller_test_lives_only_in_credit(self):
		answer = order_service.credit_service.we_are_the_seller(self.outlet.name, self.rep.name)
		self.assertFalse(answer["we_bill"])
		self.assertTrue(answer["routes_to_distributor"])
		self.assertEqual(answer["reason"], "order booking")

	def test_a_directly_billed_outlet_is_not_routed_to_a_distributor(self):
		"""ADR-001's escape hatch: an outlet the company genuinely invoices itself."""
		self.outlet.db_set("customer", self.make_distributor(), update_modified=False)
		answer = order_service.credit_service.we_are_the_seller(self.outlet.name, self.rep.name)

		self.assertTrue(answer["we_bill"])
		self.assertFalse(answer["routes_to_distributor"])
		self.assertEqual(answer["reason"], "directly billed outlet")


# --------------------------------------------------------------------------------------
# the two engines
# --------------------------------------------------------------------------------------


class TestTheServerOwnsTheTotals(OrderFixture):
	def test_a_phone_that_got_the_total_wrong_is_overwritten_and_recorded(self):
		"""Divergence is never blocked. The rep already said a number across a counter, so what
		we need is to know which shop heard which figure — not a failed sync in a market."""
		result = self.book(proposed_net_total=1.0)

		self.assertEqual(result["proposed_net_total"], 1.0, "kept exactly as the phone sent it")
		self.assertEqual(result["net_total"], 2000.0, "the server's own arithmetic wins")
		self.assertEqual(result["totals_match"], 0, "and the disagreement is on the record")

	def test_a_phone_that_agrees_is_marked_as_agreeing(self):
		result = self.book(proposed_net_total=2000.0)
		self.assertEqual(result["totals_match"], 1)

	def test_totals_are_recomputed_even_when_no_phone_figure_arrived(self):
		result = self.book()
		self.assertEqual(result["gross_total"], 2000.0)
		self.assertEqual(result["net_total"], 2000.0)
		self.assertEqual(result["lines"], 1)


class TestSchemesLandOnTheOrder(OrderFixture):
	def setUp(self):
		super().setUp()
		self.scheme = self.make_scheme(slabs=[{
			"slab_idx": 1, "from_value": 10, "is_open_ended": 1,
			"benefit_kind": "Percent Discount", "per": "Slab", "discount_pct": 5,
		}])

	def test_a_qualifying_order_carries_the_discount_and_says_why(self):
		result = self.book(qty=20)

		self.assertEqual(result["discount_total"], 100.0, "5% of 2000")
		self.assertEqual(result["net_total"], 1900.0)
		self.assertEqual(len(result["schemes"]), 1)
		self.assertIn("off", result["schemes"][0]["description"],
		              "the rep has to be able to read the benefit out loud")

	def test_the_benefit_accrues_to_the_ledger_exactly_once(self):
		result = self.book(qty=20)
		entries = frappe.get_all("FieldMate Scheme Ledger",
		                         filters={"order": result["name"]}, fields=["name", "status"])
		self.assertEqual(len(entries), 1)
		self.assertEqual(entries[0]["status"], "Accrued")

	def test_cancelling_reverses_the_accrual(self):
		"""A cancelled order that leaves its benefits behind overstates trade spend every month
		until somebody reconciles by hand."""
		result = self.book(qty=20)
		consumed = frappe.db.get_value("FieldMate Scheme", self.scheme.name, "consumed_amount")
		self.assertEqual(consumed, 100.0)

		self.as_rep(order_service.cancel, result["name"], "shop changed their mind")

		self.assertEqual(
			frappe.db.get_value("FieldMate Scheme", self.scheme.name, "consumed_amount"), 0.0
		)
		statuses = frappe.get_all("FieldMate Scheme Ledger",
		                          filters={"order": result["name"]}, pluck="status")
		self.assertEqual(statuses, ["Reversed"])

	def test_free_goods_do_not_reduce_the_bill(self):
		"""SCHEME_SPEC S9. Netting their value off pays the shop twice for one scheme — once in
		stock, once in cash — and the distributor later claims for the half nobody authorised."""
		free = self.make_scheme(
			priority=20,
			slabs=[{"slab_idx": 1, "from_value": 10, "is_open_ended": 1,
			        "benefit_kind": "Free Goods", "per": "Slab",
			        "free_item": self.item, "free_qty": 2}],
		)
		self.track("FieldMate Scheme", free.name)

		result = self.book(qty=20)

		self.assertEqual(result["discount_total"], 100.0,
		                 "only the percent scheme comes off the bill")
		self.assertEqual(result["net_total"], 1900.0, "the free units are not a deduction")
		self.assertEqual([(f["item"], f["qty"]) for f in result["free_goods"]],
		                 [(self.item, 2.0)], "and they are shipped, listed separately")


# --------------------------------------------------------------------------------------
# credit
# --------------------------------------------------------------------------------------


class TestCreditBreachRoutesRatherThanRefuses(OrderFixture):
	def test_an_order_over_the_limit_still_goes_through(self):
		"""A rep refused in front of a shopkeeper stops booking in the app at all, and then we
		lose the data as well as the order."""
		self.outlet.db_set("credit_limit", 100, update_modified=False)

		result = self.book(qty=20)
		self.assertEqual(result["docstatus"], 1, "the order is recorded, never refused")
		self.assertIn(result["order_status"], ("Sent To Distributor", "Pending Approval"))

	def test_cash_on_delivery_consumes_no_credit(self):
		"""A shop paying at the door was never a credit risk, and treating it as one blocks
		orders that never needed blocking."""
		estimate = order_service.estimate(
			self.outlet.name, self.cart(20), self.rep.name, payment_term="Cash on Delivery"
		)
		self.assertEqual(estimate["credit"]["order_value"], 0)


class TestApproval(OrderFixture):
	def test_a_rep_cannot_approve_their_own_order(self):
		result = self.book()
		frappe.set_user(self.rep.user)
		try:
			with self.assertRaises(frappe.ValidationError):
				order_service.approve(result["name"], "Approved")
		finally:
			frappe.set_user("Administrator")


# --------------------------------------------------------------------------------------
# the offline path
# --------------------------------------------------------------------------------------


class TestAnOfflineOrderLandsTheSameWay(OrderFixture):
	"""An order captured with no signal arrives through sync.push, which inserts the document
	directly and never calls the order service. Everything that matters therefore has to live on
	the controller — which is exactly the bug that once landed Day End with every figure at zero.
	"""

	def test_a_pushed_order_is_priced_routed_and_accrued(self):
		from fieldmate.services import sync as sync_service

		device = frappe.get_doc({
			"doctype": "FieldMate Device Registry",
			"device_uuid": self.uid("DEV"),
			"user": self.rep.user,
			"platform": "Android",
		}).insert(ignore_permissions=True)
		self.track("FieldMate Device Registry", device.name)
		frappe.db.commit()

		frappe.set_user(self.rep.user)
		try:
			pushed = sync_service.push(self.rep.user, device, self.uid("BATCH"), [{
				"doctype": "FieldMate Order",
				"client_uuid": self.uid("ORD"),
				"data": {
					"docstatus": 1,
					"outlet": self.outlet.name,
					"order_date": today(),
					"payment_term": "Credit",
					"created_offline": 1,
					"proposed_net_total": 2000.0,
					"items": [{"item_code": self.item, "qty": 20}],
				},
			}])["results"][0]
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(pushed["status"], "created",
		                 f"rejected: {pushed.get('code')} {pushed.get('message')}")
		self.track("FieldMate Order", pushed["name"])

		doc = frappe.get_doc("FieldMate Order", pushed["name"])
		self.assertEqual(doc.docstatus, 1, "submit_on_push must work for a real rep")
		self.assertEqual(doc.field_user, self.rep.name, "filled from the session, not the payload")
		self.assertEqual(doc.net_total, 2000.0, "priced on the controller, not taken from the phone")
		self.assertEqual(doc.order_status, "Sent To Distributor", "routed on the controller too")
		self.assertIsNone(doc.sales_order, "and still no accounting document")
