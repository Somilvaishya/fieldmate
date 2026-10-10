"""Phase 2, step 9 — what the phone is told about a season, a booking and a share link.

Everything Phase 2 built up to now happens on the server: the season decides the kind, the
advance gate holds the booking, allocation reserves the stock, dispatch ships it. **None of it
reached the handset.** The catalogue payload said nothing about a season, the order summary said
nothing about a booking, the orders list could not tell one from a shop order, and the deposit
screen could not tell a post-dated cheque from money.

So this file is about the shape of the answers rather than the rules behind them. The rules have
their own tests in `test_season`, `test_allocation` and `test_dispatch`; these say that what a rep
is holding can actually draw them.

One thing is asserted harder than the rest: **what has arrived and what has merely been promised
are two different figures, and both travel.** A phone given one number cannot tell a rep that the
advance is covered by a cheque that is not due for three weeks, and that is the sentence the whole
Phase 2 gate depends on somebody saying at a counter.
"""

import frappe
from frappe.utils import add_days, flt, today

from fieldmate.services import catalogue as catalogue_service
from fieldmate.services import collection as collection_service
from fieldmate.services import order as order_service
from fieldmate.services import scheme_compile
from fieldmate.services import season as season_service
from fieldmate.services import showcase as showcase_service
from fieldmate.tests.test_season import SeasonFixture


class PhoneFixture(SeasonFixture):
	"""A priced item, a season to book into, and a booking submitted against it."""

	def open_season(self, advance_pct=25, rate=100, **extra):
		self.price_item(self.item, rate)
		return self.make_season(
			price_list=self.season_price_list(rate), advance_pct=advance_pct, **extra)

	def booking(self):
		name = self.book_party()
		self.as_rep(order_service.submit_order, name)
		self.claim_sales_order(name)
		return name

	def claim_sales_order(self, order):
		"""Track the Sales Order a released booking raised, if it raised one.

		**Submitting a Sales Order commits**, so it outlives FrappeTestCase's per-class rollback.
		Left behind it holds the FieldMate Order's name in a unique key - and the naming series
		counter *is* rolled back, so the next run that reaches that name fails on a duplicate with
		nothing in the traceback to say which test left it. Called after anything that might
		release a booking, which is everything that pays one.
		"""
		name = frappe.db.get_value("FieldMate Order", order, "sales_order")
		if name:
			self.track("Sales Order", name)
		return name

	def pay(self, order, amount, **extra):
		payload = {
			"party_type": "Distributor", "distributor": self.party,
			"amount": amount, "mode": "Cash", "client_uuid": self.uid("COL"),
			"allocations": [{"reference_type": "FieldMate Order", "reference_name": order,
			                 "allocated_amount": amount}],
		}
		payload.update(extra)
		result = self.as_rep(collection_service.create, payload, self.rep.name)
		# The money may have just released the booking, and what that raised has to be tracked
		# here rather than in each test that happens to pay in full.
		self.claim_sales_order(order)
		return self.track("FieldMate Collection", result["name"])

	def cheque(self, order, amount, dated):
		return self.pay(order, amount, mode="Cheque", instrument_no=self.uid("CHQ"),
		                instrument_date=dated, instrument_bank="Test Bank")


class TestWhatTheCatalogueSaysAboutTheSeason(PhoneFixture):
	"""The cart screen has to know it is building a booking **before** the rep builds it.

	A rep who finds out at submit has already read a price out, promised a delivery week and not
	asked for an advance.
	"""

	def payload(self):
		return catalogue_service.for_outlet(self.party, self.rep.name, party_type="Customer")

	def test_an_ordinary_primary_order_carries_no_season(self):
		"""`None`, so the screen tests one block rather than a flag. There is no second way to
		ask whether this is a booking."""
		answer = self.payload()
		self.assertIsNone(answer["season"])
		self.assertEqual(answer["order_kind"], "Primary")

	def test_a_cart_inside_the_book_is_named_a_booking(self):
		self.open_season()
		answer = self.payload()
		self.assertEqual(answer["order_kind"], season_service.BOOKING)
		self.assertTrue(answer["season"])

	def test_it_carries_the_advance_rate_and_not_an_amount(self):
		"""The rate. A cart total moves with every tap, and the phone has the same integer
		arithmetic the server does."""
		self.open_season(advance_pct=25)
		self.assertEqual(self.payload()["season"]["advance_pct"], 25)

	def test_it_carries_the_delivery_window(self):
		"""Without it the screen cannot bound a date picker, and the server refuses a line
		outside the window at submit - one item at a time."""
		self.open_season()
		season = self.payload()["season"]
		self.assertTrue(season["delivery_from"])
		self.assertTrue(season["delivery_to"])
		self.assertLess(season["delivery_from"], season["delivery_to"])

	def test_it_says_whether_the_book_is_still_open_to_changes(self):
		self.open_season()
		self.assertTrue(self.payload()["season"]["may_change"])

	def test_it_says_so_once_the_cutoff_has_passed(self):
		"""And carries the sentence, so the screen does not write its own."""
		self.open_season(change_cutoff=add_days(today(), -1))
		season = self.payload()["season"]
		self.assertFalse(season["may_change"])
		self.assertIn("closed for changes", season["change_note"])

	def test_it_names_the_season_rather_than_its_id(self):
		self.open_season()
		self.assertTrue(self.payload()["season"]["season_name"])

	def test_a_shop_order_is_untouched_by_any_of_it(self):
		"""A kirana's cart is a secondary sale whatever month it falls in."""
		self.open_season()
		answer = catalogue_service.for_outlet(self.outlet.name, self.rep.name)
		self.assertIsNone(answer["season"])
		self.assertEqual(answer["order_kind"], "Secondary")


class TestWhatTheOrderSummarySays(PhoneFixture):
	def test_a_booking_says_it_is_one(self):
		self.open_season()
		doc = frappe.get_doc("FieldMate Order", self.booking())
		answer = order_service.summarise(doc)
		self.assertEqual(answer["order_kind"], season_service.BOOKING)
		self.assertTrue(answer["season"])

	def test_it_says_the_rates_are_final(self):
		"""The promise the party was given at the counter, and the thing a rep is asked about
		most: has the price moved."""
		self.open_season()
		doc = frappe.get_doc("FieldMate Order", self.booking())
		self.assertTrue(order_service.summarise(doc)["rates_locked_on"])

	def test_it_carries_the_advance_position(self):
		"""On the order the phone has just submitted as much as on one it re-reads. A rep who
		books a season order has to be told at the counter how much to collect."""
		self.open_season(advance_pct=25)
		doc = frappe.get_doc("FieldMate Order", self.booking())
		advance = order_service.summarise(doc)["advance"]
		self.assertGreater(advance["required"], 0)
		self.assertEqual(advance["in_hand"], 0)
		self.assertTrue(advance["held"])

	def test_an_ordinary_order_carries_no_advance_block_at_all(self):
		"""Two reads nobody should pay for on a shop order."""
		plain = self.book()
		answer = order_service.summarise(frappe.get_doc("FieldMate Order", plain["name"]))
		self.assertNotIn("advance", answer)

	def test_the_list_can_tell_a_booking_from_a_shop_order(self):
		"""It could not. `mine` named its columns explicitly and `order_kind` was not among
		them, so every card on the phone drew the same way."""
		self.open_season()
		self.booking()
		rows = {row["name"]: row for row in order_service.mine(self.rep.name)}
		kinds = {row["order_kind"] for row in rows.values()}
		self.assertIn(season_service.BOOKING, kinds)


class TestTheSeasonBook(PhoneFixture):
	"""`order.my_bookings` — one call that draws the whole screen.

	A list of its own rather than a filter on `mine`, because the figures a booking is read for
	are not on the order: what must be collected lives on the season, what has arrived lives in
	the collections allocated to it.
	"""

	# `book_season`, not `book`. `OrderFixture.book` books a **shop** order, and a helper called
	# `book` here shadowed it - so the test below that wanted a plain order got a second season
	# instead, and the master refused it as an overlap. Every large regression this phase came
	# out of a fixture, and this is the shape of all of them.
	def book_season(self, advance_pct=25, rate=100):
		self.open_season(advance_pct=advance_pct, rate=rate)
		return self.booking()

	def row_for(self, order):
		rows = [r for r in order_service.my_bookings(self.rep.name) if r["name"] == order]
		self.assertTrue(rows, f"{order} is not in this rep's season book")
		return rows[0]

	def test_it_lists_only_bookings(self):
		self.open_season()
		self.booking()
		plain = self.book()["name"]
		names = [row["name"] for row in order_service.my_bookings(self.rep.name)]
		self.assertNotIn(plain, names)

	def test_a_rep_with_no_bookings_gets_an_empty_list_not_an_error(self):
		self.assertEqual(order_service.my_bookings(self.rep.name), [])

	def test_every_row_says_what_is_still_to_collect(self):
		"""The one figure a day plan comes off."""
		order = self.book_season()
		row = self.row_for(order)
		self.assertGreater(row["advance_required"], 0)
		self.assertEqual(row["advance_in_hand"], 0)
		self.assertEqual(row["advance_short"], row["advance_required"])

	def test_money_that_has_arrived_moves_the_figure(self):
		order = self.book_season()
		required = self.row_for(order)["advance_required"]
		self.pay(order, required / 2)
		row = self.row_for(order)
		self.assertEqual(row["advance_in_hand"], required / 2)
		self.assertEqual(row["advance_short"], required / 2)

	def test_a_post_dated_cheque_does_not(self):
		"""**The line this whole screen exists to draw.** The cheque is recorded, allocated and
		reported - and the booking is still short, because releasing it means reserving stock
		against a promise."""
		order = self.book_season()
		required = self.row_for(order)["advance_required"]
		self.cheque(order, required, add_days(today(), 30))

		row = self.row_for(order)
		self.assertEqual(row["advance_in_hand"], 0)
		self.assertEqual(row["advance_short"], required)
		self.assertEqual(row["pdc_total"], required, "reported, not hidden")
		self.assertTrue(row["held"])

	def test_a_cheque_dated_today_is_money(self):
		"""The line is the date, not the instrument."""
		order = self.book_season()
		required = self.row_for(order)["advance_required"]
		self.cheque(order, required, today())

		row = self.row_for(order)
		self.assertEqual(row["advance_in_hand"], required)
		self.assertEqual(row["pdc_total"], 0)

	def test_each_row_names_its_season_and_delivery_window(self):
		order = self.book_season()
		row = self.row_for(order)
		self.assertTrue(row["season_name"])
		self.assertTrue(row["delivery_from"])
		self.assertTrue(row["delivery_to"])

	def test_each_row_says_the_rates_are_held(self):
		row = self.row_for(self.book_season())
		self.assertTrue(row["rates_locked"])

	def test_a_season_with_no_advance_asks_for_nothing(self):
		"""A season sold on open terms is an ordinary thing, not an oversight."""
		row = self.row_for(self.book_season(advance_pct=0))
		self.assertEqual(row["advance_required"], 0)
		self.assertEqual(row["advance_short"], 0)
		self.assertFalse(row["held"])

	def test_the_bill_total_travels_and_not_only_the_goods(self):
		"""The orders list drew `net_total` as the order's value for weeks - a figure short by
		the whole of the GST on the bill the party receives."""
		row = self.row_for(self.book_season())
		self.assertIn("grand_total", row)
		self.assertIn("tax_total", row)

	def test_another_reps_booking_is_not_in_it(self):
		"""The list is scoped by field user, not filtered on the screen."""
		order = self.book_season()
		other = self.make_field_user(territory=self.rep.territory)
		self.assertNotIn(
			order, [row["name"] for row in order_service.my_bookings(other.name)])


class TestPostDatedChequesInBatch(PhoneFixture):
	"""`collection.pdc_total_by_order` — the companion to `in_hand_by_order`.

	`pdcs_for` answers one order and a booking list needs fifty. Fifty calls for a figure that is
	two queries is how a screen stops being opened on a market uplink.
	"""

	def setUp(self):
		super().setUp()
		self.open_season()
		self.order = self.booking()
		self.required = order_service.advance_position(
			frappe.get_doc("FieldMate Order", self.order))["required"]

	def test_it_counts_a_future_cheque(self):
		self.cheque(self.order, self.required, add_days(today(), 20))
		self.assertEqual(
			collection_service.pdc_total_by_order([self.order])[self.order], self.required)

	def test_it_ignores_a_cheque_that_has_fallen_due(self):
		self.cheque(self.order, self.required, today())
		self.assertEqual(collection_service.pdc_total_by_order([self.order]), {})

	def test_it_ignores_cash(self):
		self.pay(self.order, self.required)
		self.assertEqual(collection_service.pdc_total_by_order([self.order]), {})

	def test_it_agrees_with_the_single_order_reader(self):
		"""Two answers to one question is how they come apart."""
		self.cheque(self.order, self.required, add_days(today(), 20))
		one = sum(row["amount"] for row in collection_service.pdcs_for(self.order))
		self.assertEqual(collection_service.pdc_total_by_order([self.order])[self.order], one)

	def test_an_empty_ask_is_an_empty_answer(self):
		self.assertEqual(collection_service.pdc_total_by_order([]), {})


class TestWhatTheDepositScreenIsTold(PhoneFixture):
	"""A post-dated cheque goes in the envelope and is **not** money.

	It was drawn among the ordinary cheques under a heading that said "Cheques in the envelope",
	so the rep was told to hand in something no bank would take today - and then told nothing at
	all, for three weeks, about why it had not cleared.
	"""

	def setUp(self):
		super().setUp()
		self.open_season()
		self.order = self.booking()

	def satchel(self):
		return collection_service.undeposited(self.rep.name)

	def row_for(self, collection):
		rows = [r for r in self.satchel()["collections"] if r["name"] == collection]
		self.assertTrue(rows, "that receipt is not in the satchel")
		return rows[0]

	def test_a_future_cheque_is_marked(self):
		name = self.cheque(self.order, 1000, add_days(today(), 30))
		self.assertTrue(self.row_for(name)["is_pdc"])

	def test_it_carries_the_date_it_falls_due(self):
		"""A rep who cannot say when it clears cannot answer the one question they are asked."""
		name = self.cheque(self.order, 1000, add_days(today(), 30))
		self.assertEqual(str(self.row_for(name)["instrument_date"]), add_days(today(), 30))

	def test_a_cheque_dated_today_is_not_marked(self):
		name = self.cheque(self.order, 1000, today())
		self.assertFalse(self.row_for(name)["is_pdc"])

	def test_cash_is_not_marked(self):
		name = self.pay(self.order, 1000)
		self.assertFalse(self.row_for(name)["is_pdc"])

	def test_the_marking_is_the_servers_date_not_the_handsets(self):
		"""A phone whose clock is a week out would otherwise call a cheque bankable when the
		bank will refuse it, which is why the comparison is made here."""
		name = self.cheque(self.order, 1000, add_days(today(), 1))
		self.assertTrue(self.row_for(name)["is_pdc"])

	def test_the_post_dated_total_is_part_of_the_cheque_total(self):
		"""Part of it, not on top. The money is in the envelope either way; it simply will not
		clear until its date."""
		self.cheque(self.order, 1000, add_days(today(), 30))
		self.cheque(self.order, 500, today())
		satchel = self.satchel()
		self.assertEqual(satchel["pdc_amount"], 1000)
		self.assertEqual(satchel["cheque_amount"], 1500)
		self.assertEqual(satchel["total_amount"], 1500)

	def test_an_all_cash_satchel_has_no_post_dated_money(self):
		self.pay(self.order, 1000)
		self.assertEqual(self.satchel()["pdc_amount"], 0)


class TestWhatTheShareScreenIsTold(PhoneFixture):
	"""The rep's side of a share link: what may be shared, what was shared, and the address.

	Enriched on the server rather than on the screen. A row needs the catalogue's name, the
	party's name and the URL itself before it is worth drawing, and none of the three is on the
	link - so a phone assembling them would make three calls a row, or print ids at a rep.
	"""

	def setUp(self):
		super().setUp()
		self.price_item(self.item, 100)
		self.showcase = self.catalogue_for(is_showcase=1)

	def catalogue_for(self, **kwargs):
		data = {
			"doctype": "FieldMate Product Catalogue",
			"catalogue_name": self.uid("CAT"),
			"is_active": 1,
			"items": [{"item_code": self.item, "sort_order": 1}],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		return self.track("FieldMate Product Catalogue", doc.name)

	def share(self, **kwargs):
		name = showcase_service.make_link(
			self.showcase, self.party, self.rep.name, "Customer", **kwargs)
		return self.track("FieldMate Share Link", name)

	# ------------------------------------------------------------------ what may be shared

	def test_a_showcase_catalogue_is_offered(self):
		names = [row["name"] for row in showcase_service.shareable_for(self.party)]
		self.assertIn(self.showcase, names)

	def test_an_ordinary_catalogue_is_not(self):
		"""It carries focus flags, minimum order quantities and notes written for the person
		selling. Putting one in front of a buyer is a leak, not a feature."""
		plain = self.catalogue_for(is_showcase=0)
		names = [row["name"] for row in showcase_service.shareable_for(self.party)]
		self.assertNotIn(plain, names)

	def test_each_one_says_how_big_it_is(self):
		row = next(r for r in showcase_service.shareable_for(self.party)
		           if r["name"] == self.showcase)
		self.assertEqual(row["line_count"], 1)
		self.assertTrue(row["catalogue_name"])

	def test_a_party_that_no_longer_exists_is_refused_rather_than_guessed(self):
		with self.assertRaises(frappe.DoesNotExistError):
			showcase_service.shareable_for("NOT-A-CUSTOMER")

	# ------------------------------------------------------------------- what was shared

	def test_the_address_is_built_by_the_server(self):
		"""A link pasted into a chat has to work for somebody who has never opened our app, so
		it cannot be assembled from whatever host the handset was served on."""
		token = frappe.db.get_value("FieldMate Share Link", self.share(), "token")
		url = showcase_service.url_for(token)
		self.assertIn(token, url)
		self.assertTrue(url.startswith("http"))

	def test_a_row_carries_the_names_and_the_url(self):
		self.share()
		row = showcase_service.links_of(self.rep.name)[0]
		self.assertTrue(row["catalogue_name"])
		self.assertTrue(row["party_name"])
		self.assertIn(row["token"], row["url"])

	def test_a_row_says_how_it_has_been_received(self):
		"""Which is the only thing a rep can learn from this screen, and the reason it is worth
		opening twice."""
		token = frappe.db.get_value("FieldMate Share Link", self.share(), "token")
		showcase_service.page(token)
		row = showcase_service.links_of(self.rep.name)[0]
		self.assertEqual(row["view_count"], 1)
		self.assertTrue(row["last_opened"])

	def test_a_row_says_whether_it_still_works(self):
		name = self.share()
		self.assertTrue(showcase_service.links_of(self.rep.name)[0]["live"])

		showcase_service.withdraw(name)
		row = showcase_service.links_of(self.rep.name)[0]
		self.assertFalse(row["live"])
		self.assertTrue(row["closed_because"])

	def test_the_verdict_is_the_documents_own(self):
		"""A link can be closed four ways - switched off, not open yet, expired, or opened more
		times than allowed - and a list that re-derived any of them would one day disagree with
		the page itself."""
		self.share(valid_from=add_days(today(), 3), valid_to=add_days(today(), 30))
		self.assertFalse(showcase_service.links_of(self.rep.name)[0]["live"])

	def test_it_says_which_rep_a_link_belongs_to(self):
		"""Asked before anything is done to one. A phone that could name a colleague could
		withdraw a live quotation out from under them."""
		name = self.share()
		self.assertEqual(showcase_service.owner_of(name), self.rep.name)

	def test_it_says_nothing_about_a_link_that_does_not_exist(self):
		self.assertIsNone(showcase_service.owner_of("FM-SHARE-NOPE"))


class TestOneAnswerAboutWhichList(PhoneFixture):
	"""Which price list a booking is quoted from, asked of all three readers.

	**This was wrong and the manual-test seeding found it.** A booking is priced from its season's
	list, and `cart_for` has done that since step 2 - but `for_outlet`, the catalogue a rep
	browses, and `prices_for`, the narrow re-pricing endpoint, were both still reading the party's
	own list. So during a season the rep browsed and quoted at one set of rates while the server
	booked the order at another: 8.20 on the screen against 7.38 in the order, on every line. The
	phone computes its totals from the catalogue, so the figure said at the counter was the wrong
	one and `totals_match` went to zero on every booking.

	`for_outlet` is the one that reached a rep. `prices_for` had the same defect and no caller -
	`api.cataloguePrices` is wired into the client and nothing invokes it - which is why it went
	unnoticed, and is exactly the reason to pin it here now.

	Three readers, one answer, and the fixture's two lists disagree on purpose - a test where the
	party's list and the season's list hold the same rate cannot see any of this.
	"""

	PARTY_RATE, SEASON_RATE = 100, 70

	def setUp(self):
		super().setUp()
		self.price_item(self.item, self.PARTY_RATE)
		self.season_list = self.season_price_list(self.SEASON_RATE)
		# A catalogue, which the order fixtures do not build and do not need: `cart_for` prices
		# whatever the cart names, while `for_outlet` and `prices_for` deliberately answer only
		# what the party is allowed to be sold. No channel and no outlet class on it, because
		# that is the whole of what makes a master reach a Customer rather than a shop.
		doc = frappe.get_doc({
			"doctype": "FieldMate Product Catalogue",
			"catalogue_name": self.uid("CAT"), "is_active": 1,
			"items": [{"item_code": self.item, "sort_order": 1}],
		}).insert(ignore_permissions=True)
		self.track("FieldMate Product Catalogue", doc.name)

	def open_the_book(self):
		return self.make_season(price_list=self.season_list, advance_pct=0)

	def catalogue(self):
		return catalogue_service.for_outlet(self.party, self.rep.name, party_type="Customer")

	def fresh_prices(self):
		return catalogue_service.prices_for(
			self.party, [{"item_code": self.item, "qty": 10}], self.rep.name,
			party_type="Customer")

	def cart(self):
		return catalogue_service.cart_for(
			self.party, [{"item": self.item, "qty": 10}], self.rep.name, party_type="Customer")

	def rate_on(self, payload):
		"""The rate this payload carries for the fixture item, in rupees.

		Three shapes, because the three readers answer three shapes: `for_outlet` a list of rows,
		`prices_for` a dict keyed by item code, `cart_for` a list in integer paise. Normalising
		here is the point - the test is that the number is the same however it is asked for.
		"""
		rows = payload.get("items") or payload.get("lines") or []

		if isinstance(rows, dict):
			row = rows.get(self.item)
			self.assertIsNotNone(row, "the item is not in that payload at all")
			return flt(row["rate"])

		for row in rows:
			if (row.get("item_code") or row.get("item")) == self.item:
				return (flt(row["rate"]) if row.get("rate") is not None
				        else scheme_compile.in_rupees(row["rate_paise"]))
		self.fail("the item is not in that payload at all")

	# -------------------------------------------------------------- inside a season

	def test_the_catalogue_is_priced_from_the_season(self):
		self.open_the_book()
		self.assertEqual(self.catalogue()["price_list"], self.season_list)

	def test_the_call_made_before_a_total_is_read_out_is_too(self):
		self.open_the_book()
		self.assertEqual(self.fresh_prices()["price_list"], self.season_list)

	def test_the_cart_is_too(self):
		self.open_the_book()
		self.assertEqual(self.cart()["price_list"], self.season_list)

	def test_all_three_agree_on_the_rate(self):
		"""To the paisa. A rep reads the first, the phone totals the second and the server books
		the third, and the whole money design rests on the three being one number."""
		self.open_the_book()
		rates = {self.rate_on(self.catalogue()),
		         self.rate_on(self.fresh_prices()),
		         self.rate_on(self.cart())}
		self.assertEqual(rates, {float(self.SEASON_RATE)},
		                 "the catalogue, the fresh-price call and the cart disagree")

	# ------------------------------------------------------------- outside a season

	def test_an_ordinary_primary_order_is_quoted_from_the_partys_own_list(self):
		"""The season's list governs a booking and nothing else. The day the book shuts, the
		party goes back to buying on its own terms."""
		rates = {self.rate_on(self.catalogue()),
		         self.rate_on(self.fresh_prices()),
		         self.rate_on(self.cart())}
		self.assertEqual(rates, {float(self.PARTY_RATE)})

	def test_a_shop_is_untouched_by_the_season(self):
		"""A kirana buys from its distributor whatever month it is."""
		self.open_the_book()
		shop = catalogue_service.for_outlet(self.outlet.name, self.rep.name)
		self.assertNotEqual(shop["price_list"], self.season_list)

	def test_the_fresh_price_call_knows_a_customer_from_a_shop(self):
		"""It passed no `party_type` at all, so a Customer was read as an Outlet - the same
		defect `_from_outlet` had, on the one call the phone makes before a rep speaks."""
		self.open_the_book()
		answer = self.fresh_prices()
		self.assertEqual(answer["outlet"], self.party)
		self.assertEqual(self.rate_on(answer), float(self.SEASON_RATE))
