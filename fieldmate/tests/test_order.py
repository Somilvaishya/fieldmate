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

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from fieldmate.services import order as order_service
from fieldmate.services import settings as settings_service
from fieldmate.tests.test_scheme_compile import SchemeFixture, default_selling_price_list


class OrderFixture(SchemeFixture):
	def setUp(self):
		super().setUp()
		self.rep = self.make_field_user(territory=self.territory_for_orders())
		self.outlet = self.make_outlet(territory=self.rep.territory, approval_status="Approved")
		# An order routes to a distributor, and since step 2d a distributor IS a Customer with a
		# channel tier - there is no second document beside it. The outlet already names the
		# Customer, so this marks the one it names rather than building another. Marking it
		# matters: `outlet.create` and `channel.resolve` both ask for the tier, and a Customer
		# without one is not a party FieldMate sells through.
		# Tier only, not territory. Nothing in the order path reads the distributor's territory,
		# and writing it here would make this Customer an answer to "who covers the rep's
		# territory" - so a second fixture doing the same would turn an unrelated test's shop
		# onboarding into "more than one distributor covers your area".
		frappe.db.set_value(
			"Customer", self.outlet.distributor,
			{"fm_tier": "Distributor", "fm_buys_from": "Company"},
			update_modified=False)
		frappe.clear_document_cache("Customer", self.outlet.distributor)
		self.distributor = frappe.get_doc("Customer", self.outlet.distributor)
		self.price_item(self.item, 100)

	def territory_for_orders(self):
		if not getattr(self, "_territory", None):
			self._territory = self.make_territory()
		return self._territory

	def cleanup_targets(self):
		"""The orders this rep booked through the service, which `track` never saw.

		Handed to the base rather than deleted here. Deleting them here ran **before** the base
		had taken down what those orders led to: a FieldMate Order's `on_cancel` cancels its
		Sales Order, so by the time the base reached a Delivery Note raised against it ERPNext
		refused with "Sales Order is cancelled or closed", the whole cleanup stopped there, and
		everything after it leaked.
		"""
		rows = []
		for dt in ("FieldMate Scheme Ledger", "FieldMate Order"):
			rows += [(dt, name) for name in frappe.get_all(
				dt, pluck="name", filters={"field_user": self.rep.name})]
		return list(super().cleanup_targets()) + rows

	def tearDown(self):
		frappe.set_user("Administrator")
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


class TestOnlyADirectlyBilledOutletIsOurs(OrderFixture):
	"""One case, and only one, puts the company on the other side of the counter."""

	def test_the_seller_test_lives_only_in_credit(self):
		answer = order_service.credit_service.we_are_the_seller(self.outlet.name, self.rep.name)
		self.assertFalse(answer["we_bill"])
		self.assertTrue(answer["routes_to_distributor"])

	def test_a_directly_billed_outlet_is_not_routed_to_a_distributor(self):
		"""ADR-001's escape hatch: an outlet the company genuinely invoices itself."""
		billed = self.make_distributor()
		self.outlet.db_set("customer", billed, update_modified=False)
		answer = order_service.credit_service.we_are_the_seller(self.outlet.name, self.rep.name)

		self.assertTrue(answer["we_bill"])
		self.assertFalse(answer["routes_to_distributor"])
		# `why` rather than `reason` since step 5: `reason` now carries the refusal from
		# `channel.resolve` - why this sale cannot be made - and two meanings of the same key in
		# one dict is how a caller ends up showing "directly billed outlet" to a rep as an error.
		self.assertEqual(answer["why"], "directly billed outlet")

	def test_the_bill_goes_to_the_shop_we_invoice_and_not_its_distributor(self):
		"""The defect this wiring fixes. `billing_party` answered `doc.distributor` whatever the
		shop's own `customer` said, so a directly-billed outlet priced, credit-checked and raised
		its Sales Order against the distributor - the one party ADR-024 says is not involved."""
		billed = self.make_distributor()
		self.outlet.db_set("customer", billed, update_modified=False)

		answer = order_service.credit_service.billing_party(self.outlet.name, self.rep.name)
		self.assertEqual(answer["party"], billed)
		self.assertNotEqual(answer["party"], self.outlet.distributor)
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


class TestTheSiteSwitchActuallyGates(OrderFixture):
	"""`enable_primary_sales` and `enable_secondary_sales` were written, were read by
	`channel.resolve` and gated nothing, because nothing called it. Step 5 wires it in, and this
	is what "whichever is enabled on a site is what that site does" actually means."""

	SETTINGS = ("enable_secondary_sales", "enable_primary_sales")

	def setUp(self):
		super().setUp()
		self._before = {k: self.fresh_settings().get(k) for k in self.SETTINGS}

	def tearDown(self):
		self.apply_settings(**self._before)
		super().tearDown()

	def test_a_shop_cannot_be_booked_with_secondary_sales_switched_off(self):
		self.apply_settings(enable_secondary_sales=0, enable_primary_sales=1)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.book()
		self.assertIn("switched off", frappe.utils.strip_html(str(ctx.exception)))

	def test_the_message_says_who_can_turn_it_on(self):
		"""A rep standing at a counter cannot act on "not allowed"."""
		self.apply_settings(enable_secondary_sales=0, enable_primary_sales=1)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.book()
		self.assertIn("manager", frappe.utils.strip_html(str(ctx.exception)).lower())

	def test_nothing_is_left_half_written_when_it_refuses(self):
		self.apply_settings(enable_secondary_sales=0, enable_primary_sales=1)
		before = frappe.db.count("FieldMate Order")
		with self.assertRaises(frappe.ValidationError):
			self.book()
		self.assertEqual(frappe.db.count("FieldMate Order"), before)

	def test_a_shop_books_normally_with_secondary_sales_on(self):
		self.apply_settings(enable_secondary_sales=1, enable_primary_sales=0)
		result = self.book()
		self.assertEqual(result["order_status"], "Sent To Distributor")

	def test_a_directly_billed_shop_is_refused_when_primary_is_off(self):
		"""The other half of the switch. That shop is a primary sale - we invoice it - so a site
		that does not make primary sales cannot book it, however ordinary the shop looks."""
		self.apply_settings(enable_secondary_sales=1, enable_primary_sales=0)
		self.outlet.db_set("customer", self.make_distributor(), update_modified=False)

		with self.assertRaises(frappe.ValidationError) as ctx:
			self.book()
		self.assertIn("switched off", frappe.utils.strip_html(str(ctx.exception)))


class TestAnOrderOnAPartyWeBill(OrderFixture):
	"""Phase 1, step 5c: a primary sale. The rep is at a super stockist's office, not a kirana,
	and the party is an ERPNext Customer rather than a FieldMate Outlet."""

	SETTINGS = ("enable_secondary_sales", "enable_primary_sales")

	def setUp(self):
		super().setUp()
		self._before = {k: self.fresh_settings().get(k) for k in self.SETTINGS}
		self.apply_settings(enable_secondary_sales=1, enable_primary_sales=1)
		# A party we sell to: a Customer with a channel tier, priced off its own list. **Named**,
		# not "whichever selling list MariaDB returns first" - that is not a rule, and the moment
		# another fixture leaves a selling list behind it moves. It did: a leaked
		# `SEASON-PL-` list from the season fixture won that query and these six tests failed
		# with "these have no price yet", which names the symptom and hides the cause. The same
		# lesson `default_selling_price_list` and `_guard.selling_price_list` were both written
		# for, in the one class that had not learned it.
		self.party_price_list = default_selling_price_list()
		self.party = self.outlet.distributor
		frappe.db.set_value("Customer", self.party, {
			"fm_tier": "Super Stockist", "fm_buys_from": "Company",
			"default_price_list": self.party_price_list,
		}, update_modified=False)
		frappe.clear_document_cache("Customer", self.party)

	def tearDown(self):
		self.apply_settings(**self._before)
		super().tearDown()

	def book_party(self, qty=10, **extra):
		payload = {"party_type": "Customer", "customer": self.party,
		           "lines": self.cart(qty), "client_uuid": self.uid("PORD")}
		payload.update(extra)
		created = self.as_rep(order_service.create, payload, self.rep.name)
		self.track("FieldMate Order", created["name"])
		return created

	def test_an_order_can_name_a_customer_instead_of_a_shop(self):
		created = self.book_party()
		doc = frappe.get_doc("FieldMate Order", created["name"])
		self.assertEqual(doc.party_type, "Customer")
		self.assertEqual(doc.customer, self.party)
		self.assertFalse(doc.outlet, "a primary order is on nobody's shop")

	def test_the_party_is_the_one_billed(self):
		doc = frappe.get_doc("FieldMate Order", self.book_party()["name"])
		self.assertEqual(doc.distributor, self.party,
		                 "on a primary sale the party we bill is the party itself")

	def test_it_is_priced_off_the_partys_own_list(self):
		doc = frappe.get_doc("FieldMate Order", self.book_party()["name"])
		self.assertEqual(doc.price_list, self.party_price_list)
		self.assertEqual(doc.net_total, 1000)

	def test_primary_sales_switched_off_refuses_it(self):
		self.apply_settings(enable_secondary_sales=1, enable_primary_sales=0)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.book_party()
		self.assertIn("switched off", frappe.utils.strip_html(str(ctx.exception)))

	def test_an_order_with_no_party_at_all_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.as_rep(order_service.create,
			            {"party_type": "Customer", "lines": self.cart(),
			             "client_uuid": self.uid("PORD")}, self.rep.name)

	def test_a_customer_with_no_tier_is_not_a_party_we_sell_to(self):
		"""Most Customers on an ERPNext site have nothing to do with FieldMate."""
		frappe.db.set_value("Customer", self.party, "fm_tier", None, update_modified=False)
		frappe.clear_document_cache("Customer", self.party)
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.book_party()
		self.assertIn("channel tier", frappe.utils.strip_html(str(ctx.exception)))

	def test_a_shop_order_still_says_it_is_a_shop_order(self):
		"""The field is inferred where a caller does not send one, so every build of the phone
		already in a pocket goes on working."""
		doc = frappe.get_doc("FieldMate Order", self.book()["name"])
		self.assertEqual(doc.party_type, "Outlet")
		self.assertFalse(doc.customer)

	def test_submitting_one_posts_a_sales_order_to_that_party(self):
		"""The whole point of a primary sale: it is ours, so it reaches the company order book.

		A retailer order is the opposite and `TestAnOrderIsASecondarySale` asserts that - the two
		tests are each other's mirror and both are needed, because the bug worth catching is one
		branch quietly taking the other's path.
		"""
		created = self.book_party()
		before = frappe.db.count("Sales Order")
		result = self.as_rep(order_service.submit_order, created["name"])

		doc = frappe.get_doc("FieldMate Order", created["name"])
		self.assertEqual(doc.order_status, "Approved")
		self.assertTrue(doc.sales_order, "a primary sale posts a Sales Order")
		self.track("Sales Order", doc.sales_order)
		self.assertEqual(frappe.db.count("Sales Order"), before + 1, "exactly one")
		self.assertEqual(
			frappe.db.get_value("Sales Order", doc.sales_order, "customer"), self.party,
			"billed to the party we sold to, not to anybody else")
		self.assertEqual(result["order_status"], "Approved")

	def test_it_is_not_handed_to_a_distributors_queue(self):
		"""There is no distributor in a primary sale - we are the seller."""
		created = self.book_party()
		self.as_rep(order_service.submit_order, created["name"])
		doc = frappe.get_doc("FieldMate Order", created["name"])
		self.track("Sales Order", doc.sales_order)
		self.assertNotEqual(doc.order_status, "Sent To Distributor")
		self.assertFalse(doc.sent_to_distributor_on)

	def test_submitting_twice_posts_one_sales_order(self):
		"""A dropped connection must not become two company commitments."""
		created = self.book_party()
		self.as_rep(order_service.submit_order, created["name"])
		doc = frappe.get_doc("FieldMate Order", created["name"])
		self.track("Sales Order", doc.sales_order)
		first = doc.sales_order

		self.as_rep(order_service.submit_order, created["name"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Order", created["name"], "sales_order"), first)


class TestWhichBranchIsSelling(OrderFixture):
	"""`location` — which of our own branches makes a primary sale.

	ERPNext models it as an Accounting Dimension. A site that has enabled one makes it mandatory
	on the Sales Order, the Delivery Note and the invoice, and the document's naming series, the
	company address and the GSTIN can all hang off it.

	**Nothing fills it server-side.** `dimension_tree_filter.js` applies a dimension's per-company
	default in the Desk form with `frm.set_value`, and no server path does the same — so every
	order this app posted onto such a site was refused with "Select Location before Saving", a
	message naming a field the rep had never heard of and no screen offered.

	So the rep chooses, and the party's usual branch is what they are offered.
	"""

	SETTINGS = ("enable_secondary_sales", "enable_primary_sales")

	def setUp(self):
		super().setUp()
		self._before = {k: self.fresh_settings().get(k) for k in self.SETTINGS}
		self.apply_settings(enable_secondary_sales=1, enable_primary_sales=1)
		self.party = self.outlet.distributor
		frappe.db.set_value("Customer", self.party, {
			"fm_tier": "Super Stockist", "fm_buys_from": "Company",
			"default_price_list": default_selling_price_list(),
		}, update_modified=False)
		frappe.clear_document_cache("Customer", self.party)

	def tearDown(self):
		self.apply_settings(**self._before)
		super().tearDown()

	def branch(self, is_group=0, parent=None):
		doc = frappe.get_doc({
			"doctype": "Location", "location_name": self.uid("BRANCH"),
			"is_group": is_group, "parent_location": parent,
		}).insert(ignore_permissions=True)
		return self.track("Location", doc.name)

	def book_party(self, **extra):
		payload = {"party_type": "Customer", "customer": self.party,
		           "lines": self.cart(10), "client_uuid": self.uid("PORD")}
		payload.update(extra)
		created = self.as_rep(order_service.create, payload, self.rep.name)
		return self.track("FieldMate Order", created["name"])

	# ------------------------------------------------------------------ what the phone is told

	def test_only_the_leaves_are_offered(self):
		"""A Location is a tree and its groups are folders. "Delhi" holding two depots is a shape
		somebody made to tidy a list, not a place a sale happens at."""
		group = self.branch(is_group=1)
		leaf = self.branch(parent=group)
		offered = [row["name"] for row in order_service.locations_for()]
		self.assertIn(leaf, offered)
		self.assertNotIn(group, offered)

	def test_the_partys_usual_branch_is_the_default(self):
		branch = self.branch()
		frappe.db.set_value("Customer", self.party, "fm_location", branch, update_modified=False)
		frappe.clear_document_cache("Customer", self.party)
		self.assertEqual(order_service.default_location_for(self.party), branch)

	def test_a_party_with_no_branch_defaults_to_nothing(self):
		"""Which is every party on a site that does not use Locations."""
		self.assertIsNone(order_service.default_location_for(self.party))

	def test_a_group_is_never_offered_as_a_default(self):
		"""Posting against a folder is not posting against a place, and ERPNext would take it."""
		group = self.branch(is_group=1)
		frappe.db.set_value("Customer", self.party, "fm_location", group, update_modified=False)
		frappe.clear_document_cache("Customer", self.party)
		self.assertIsNone(order_service.default_location_for(self.party))

	# ------------------------------------------------------------------ what the order carries

	def test_the_rep_choice_is_recorded(self):
		branch = self.branch()
		doc = frappe.get_doc("FieldMate Order", self.book_party(location=branch))
		self.assertEqual(doc.location, branch)

	def test_it_falls_back_to_the_partys_branch(self):
		branch = self.branch()
		frappe.db.set_value("Customer", self.party, "fm_location", branch, update_modified=False)
		frappe.clear_document_cache("Customer", self.party)
		doc = frappe.get_doc("FieldMate Order", self.book_party())
		self.assertEqual(doc.location, branch)

	def test_the_rep_beats_the_party_default(self):
		"""The whole reason it is a choice on the order rather than copied off the Customer: a
		party served by two branches."""
		usual, today = self.branch(), self.branch()
		frappe.db.set_value("Customer", self.party, "fm_location", usual, update_modified=False)
		frappe.clear_document_cache("Customer", self.party)
		doc = frappe.get_doc("FieldMate Order", self.book_party(location=today))
		self.assertEqual(doc.location, today)

	def test_a_shop_order_carries_no_branch(self):
		"""A retailer order is the distributor's own sale and posts nothing, so no branch of ours
		is involved in it at all."""
		created = self.as_rep(order_service.create, {
			"outlet": self.outlet.name, "lines": self.cart(10),
			"client_uuid": self.uid("ORD"),
		}, self.rep.name)
		self.track("FieldMate Order", created["name"])
		self.assertFalse(frappe.db.get_value("FieldMate Order", created["name"], "location"))

	# ------------------------------------------------------------------ what ERPNext is sent

	def test_it_reaches_the_sales_order(self):
		"""Asserted on the payload rather than the posted document: this bench has no Location
		dimension, so a Sales Order here has no such column to read back. What matters is that
		the adapter is handed the branch - `compat.make_sales_order` writes it only where the
		site actually has the field, which is the site that needs it."""
		branch = self.branch()
		name = self.book_party(location=branch)

		with patch("fieldmate.compat.make_sales_order", return_value=None) as posted:
			self.as_rep(order_service.submit_order, name)

		self.assertTrue(posted.called, "a primary order posted no Sales Order at all")
		self.assertEqual(posted.call_args[0][0]["location"], branch)
