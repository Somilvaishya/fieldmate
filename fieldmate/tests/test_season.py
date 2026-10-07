"""Phase 2, step 1 — a season, and the one rule that makes an order a booking of it.

    a primary order dated inside the booking window of its company's active season
    is a booking of that season

There is no booking flag for a rep to tick and no rule table scoring a season against a party.
The dates say what the order was, the same way the party says what kind of sale it is.
"""

import frappe
from frappe.utils import add_days, getdate, today

from fieldmate.services import collection as collection_service
from fieldmate.services import order as order_service
from fieldmate.services import scheme_compile
from fieldmate.services import season as season_service
from fieldmate.services import settings as settings_service
from fieldmate.tests.test_order import OrderFixture


class SeasonFixture(OrderFixture):
	"""A party we bill, and a season for its company to book into."""

	SETTINGS = ("enable_secondary_sales", "enable_primary_sales")

	def setUp(self):
		super().setUp()
		self._before = {k: self.fresh_settings().get(k) for k in self.SETTINGS}
		self.apply_settings(enable_secondary_sales=1, enable_primary_sales=1)

		self.party_price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
		self.party = self.outlet.distributor
		frappe.db.set_value("Customer", self.party, {
			"fm_tier": "Super Stockist", "fm_buys_from": "Company",
			"default_price_list": self.party_price_list,
		}, update_modified=False)
		frappe.clear_document_cache("Customer", self.party)

		self.company = frappe.db.get_value("FieldMate Field User", self.rep.name, "company") \
			or settings_service.value("default_company")

	def tearDown(self):
		self.apply_settings(**self._before)
		super().tearDown()

	def season_price_list(self, rate=70):
		"""A list of the season's own, priced below the party's everyday one.

		Different on purpose: every test about which list a booking is priced from is only worth
		anything if the two lists disagree.
		"""
		name = self.uid("SEASON-PL")
		frappe.get_doc({"doctype": "Price List", "price_list_name": name, "selling": 1,
		                "enabled": 1, "currency": frappe.db.get_value(
			                "Price List", self.party_price_list, "currency") or "INR",
		                }).insert(ignore_permissions=True)
		self.track("Price List", name)
		row = frappe.get_doc({"doctype": "Item Price", "item_code": self.item,
		                      "price_list": name, "price_list_rate": rate}
		                     ).insert(ignore_permissions=True)
		self.track("Item Price", row.name)
		return name

	def make_season(self, **kwargs):
		data = {
			"doctype": "FieldMate Season",
			"season_name": self.uid("SEASON"),
			"company": self.company,
			"festival_date": add_days(today(), 120),
			"booking_from": add_days(today(), -5),
			"booking_to": add_days(today(), 30),
			"delivery_from": add_days(today(), 60),
			"delivery_to": add_days(today(), 110),
			"price_list": self.party_price_list,
			"advance_pct": 25,
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		return self.track("FieldMate Season", doc.name)

	def book_party(self, **extra):
		payload = {"party_type": "Customer", "customer": self.party,
		           "lines": self.cart(10), "client_uuid": self.uid("PORD")}
		payload.update(extra)
		created = self.as_rep(order_service.create, payload, self.rep.name)
		return self.track("FieldMate Order", created["name"])


class TestTheSeasonMaster(SeasonFixture):
	def test_a_book_that_shuts_before_it_opens_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_season(booking_from=add_days(today(), 10), booking_to=add_days(today(), 2))

	def test_delivery_before_booking_is_refused(self):
		"""Not a hard rule but a real mistake: a season delivering before its book opens is not
		being booked in advance, which is the whole point of a season."""
		with self.assertRaises(frappe.ValidationError):
			self.make_season(booking_from=add_days(today(), 10),
			                 delivery_from=add_days(today(), 1),
			                 delivery_to=add_days(today(), 20))

	def test_the_cutoff_defaults_to_the_book_shutting(self):
		"""Stored rather than worked out on every read: a cutoff is quoted to a distributor, and
		a figure nobody can point at on the document gets argued about."""
		name = self.make_season(change_cutoff=None)
		doc = frappe.get_doc("FieldMate Season", name)
		self.assertEqual(str(doc.change_cutoff), str(doc.booking_to))

	def test_two_seasons_booking_at_once_for_one_company_are_refused(self):
		"""`open_for` would have to pick one, and any rule for picking is the configuration
		language this design is trying not to have."""
		self.make_season()
		with self.assertRaises(frappe.ValidationError):
			self.make_season()

	def test_a_closed_season_does_not_clash(self):
		self.make_season()
		self.make_season(is_active=0)   # no exception


class TestWhichSeasonIsBooking(SeasonFixture):
	def test_none_when_the_company_has_no_season(self):
		self.assertIsNone(season_service.open_for(self.company))

	def test_the_one_whose_book_is_open(self):
		name = self.make_season()
		self.assertEqual(season_service.open_for(self.company), name)

	def test_not_before_the_book_opens(self):
		self.make_season(booking_from=add_days(today(), 5), booking_to=add_days(today(), 40))
		self.assertIsNone(season_service.open_for(self.company))

	def test_not_after_it_shuts(self):
		self.make_season(booking_from=add_days(today(), -40), booking_to=add_days(today(), -1))
		self.assertIsNone(season_service.open_for(self.company))

	def test_not_one_that_has_been_switched_off(self):
		self.make_season(is_active=0)
		self.assertIsNone(season_service.open_for(self.company))

	def test_not_another_company_s(self):
		self.make_season()
		self.assertIsNone(season_service.open_for("No Such Company"))


class TestWhatMakesAnOrderABooking(SeasonFixture):
	def test_a_primary_order_inside_the_window_is_a_booking(self):
		name = self.make_season()
		doc = frappe.get_doc("FieldMate Order", self.book_party())
		self.assertEqual(doc.order_kind, "Booking")
		self.assertEqual(doc.season, name)

	def test_a_primary_order_with_no_season_open_is_just_primary(self):
		doc = frappe.get_doc("FieldMate Order", self.book_party())
		self.assertEqual(doc.order_kind, "Primary")
		self.assertFalse(doc.season)

	def test_a_shop_order_is_never_a_booking(self):
		"""The distributor's own sale to a kirana is not something we book a season against,
		whatever month it falls in."""
		self.make_season()
		result = self.book()
		doc = frappe.get_doc("FieldMate Order", result["name"])
		self.assertEqual(doc.order_kind, "Secondary")
		self.assertFalse(doc.season)

	def test_the_kind_is_derived_and_not_taken_from_the_phone(self):
		"""A rep does not get to say what kind of sale they made. Same rule as the totals."""
		self.make_season()
		doc = frappe.get_doc("FieldMate Order", self.book_party(order_kind="Secondary"))
		self.assertEqual(doc.order_kind, "Booking")

	def test_an_order_dated_before_the_book_opened_is_not_a_booking(self):
		"""The order date, not the day it synced. A rep syncing in December must not have
		November's orders book into a season that opened after they were taken."""
		self.make_season(booking_from=add_days(today(), -2), booking_to=add_days(today(), 30))
		doc = frappe.get_doc("FieldMate Order", self.book_party(order_date=add_days(today(), -10)))
		self.assertEqual(doc.order_kind, "Primary")
		self.assertFalse(doc.season)


class TestChangingABooking(SeasonFixture):
	def test_a_booking_may_be_changed_before_the_cutoff(self):
		name = self.make_season(change_cutoff=add_days(today(), 7))
		allowed, why = season_service.may_amend(name)
		self.assertTrue(allowed)
		self.assertEqual(why, "")

	def test_and_not_after_it(self):
		"""A season's commercial point is that the company can plan against the book, so the
		book stops moving."""
		name = self.make_season(booking_from=add_days(today(), -20),
		                        booking_to=add_days(today(), 20),
		                        change_cutoff=add_days(today(), -1))
		allowed, why = season_service.may_amend(name)
		self.assertFalse(allowed)
		self.assertIn("closed for changes", why)

	def test_an_order_with_no_season_is_not_held_to_a_cutoff(self):
		allowed, _ = season_service.may_amend(None)
		self.assertTrue(allowed)


class TestABookingIsPricedFromItsSeason(SeasonFixture):
	"""A party that books Holi in November is buying at the season's terms, and those are the
	same for everyone booking it. Its own everyday list goes back to governing its ordinary
	primary orders the day the book shuts."""

	def test_the_season_s_list_wins_over_the_party_s(self):
		self.price_item(self.item, 100)              # the party's everyday rate
		season_list = self.season_price_list(70)     # the season's
		self.make_season(price_list=season_list)

		doc = frappe.get_doc("FieldMate Order", self.book_party())
		self.assertEqual(doc.order_kind, "Booking")
		self.assertEqual(doc.price_list, season_list)
		self.assertEqual(doc.items[0].rate, 70)

	def test_an_ordinary_primary_order_still_uses_the_party_s(self):
		self.price_item(self.item, 100)
		season_list = self.season_price_list(70)
		# Booking opens next week, so today's order is not a booking of it.
		self.make_season(price_list=season_list, booking_from=add_days(today(), 7),
		                 booking_to=add_days(today(), 40))

		doc = frappe.get_doc("FieldMate Order", self.book_party())
		self.assertEqual(doc.order_kind, "Primary")
		self.assertNotEqual(doc.price_list, season_list)
		self.assertEqual(doc.items[0].rate, 100)

	def test_a_shop_order_is_untouched_by_an_open_season(self):
		self.price_item(self.item, 100)
		season_list = self.season_price_list(70)
		self.make_season(price_list=season_list)

		doc = frappe.get_doc("FieldMate Order", self.book()["name"])
		self.assertEqual(doc.order_kind, "Secondary")
		self.assertNotEqual(doc.price_list, season_list)


class TestTheRateStopsMovingAtSubmit(SeasonFixture):
	"""A season is booked months before it is delivered, so the list it was taken from will have
	moved by then - and a party that booked in November is owed November's price."""

	def booked_and_submitted(self, rate=70):
		self.price_item(self.item, 100)
		season_list = self.season_price_list(rate)
		self.make_season(price_list=season_list, advance_pct=0)
		name = self.book_party()
		self.as_rep(order_service.submit_order, name)
		# Tracked, or it outlives the test: submitting a Sales Order commits, so it survives
		# FrappeTestCase's rollback while the FieldMate Order that keyed it does not - and the
		# next test is handed the same order name and collides on `fm_source_key`.
		self.track("Sales Order",
		           frappe.db.get_value("FieldMate Order", name, "sales_order"))
		return name, season_list

	def test_the_lock_is_recorded_when_it_is_submitted(self):
		name, _ = self.booked_and_submitted()
		doc = frappe.get_doc("FieldMate Order", name)
		self.assertTrue(doc.rates_locked_on, "a booking says when it stopped being repriced")

	def test_the_season_list_moving_does_not_reprice_a_booking(self):
		name, season_list = self.booked_and_submitted(rate=70)
		was = frappe.get_doc("FieldMate Order", name).items[0].rate
		self.assertEqual(was, 70)

		# The season's list is corrected in January, long after the book shut.
		frappe.db.set_value("Item Price",
		                    {"item_code": self.item, "price_list": season_list},
		                    "price_list_rate", 95)
		frappe.clear_document_cache("Item Price", frappe.db.get_value(
			"Item Price", {"item_code": self.item, "price_list": season_list}, "name"))

		doc = frappe.get_doc("FieldMate Order", name)
		order_service.price(doc)
		self.assertEqual(doc.items[0].rate, 70, "the rate the party was read out in November")

	def test_an_unsubmitted_booking_still_follows_the_list(self):
		"""The lock is at submit, not at creation. Until then the rep is still quoting."""
		self.price_item(self.item, 100)
		season_list = self.season_price_list(70)
		self.make_season(price_list=season_list)
		name = self.book_party()

		frappe.db.set_value("Item Price",
		                    {"item_code": self.item, "price_list": season_list},
		                    "price_list_rate", 95)
		doc = frappe.get_doc("FieldMate Order", name)
		order_service.price(doc)
		self.assertEqual(doc.items[0].rate, 95)

	def test_an_ordinary_order_is_never_locked(self):
		self.price_item(self.item, 100)
		result = self.book()
		self.assertFalse(
			frappe.db.get_value("FieldMate Order", result["name"], "rates_locked_on"))


class TestWhenEachLineIsWanted(SeasonFixture):
	"""The whole point of booking a season: a party asks for part of its order in January and the
	rest in February."""

	def test_a_blank_date_becomes_the_season_s_first_delivery_day(self):
		"""Most lines of most bookings are wanted as early as they can be had, and making a rep
		type the same date on forty lines is how a form stops being filled in honestly."""
		name = self.make_season()
		doc = frappe.get_doc("FieldMate Order", self.book_party())
		season = frappe.get_doc("FieldMate Season", name)
		self.assertEqual(str(doc.items[0].delivery_date), str(season.delivery_from))

	def test_a_date_outside_the_window_is_refused_and_names_the_item(self):
		self.make_season()
		with self.assertRaises(frappe.ValidationError) as caught:
			self.book_party(lines=[{"item": self.item, "qty": 10,
			                        "delivery_date": add_days(today(), 400)}])
		self.assertIn(self.item, str(caught.exception))

	def test_a_date_inside_the_window_is_kept(self):
		self.make_season()
		wanted = add_days(today(), 75)
		doc = frappe.get_doc("FieldMate Order", self.book_party(
			lines=[{"item": self.item, "qty": 10, "delivery_date": wanted}]))
		self.assertEqual(str(doc.items[0].delivery_date), str(wanted))

	def test_an_ordinary_order_has_no_window_to_be_inside(self):
		"""No season, nothing to check against. A date on such a line is the rep's own note."""
		result = self.book()
		doc = frappe.get_doc("FieldMate Order", result["name"])
		self.assertFalse(doc.items[0].delivery_date)


class TestTheSalesOrderABookingPosts(SeasonFixture):
	def submitted_booking(self, **season):
		# Open terms unless a test says otherwise. These tests are about what the Sales Order
		# carries; the advance gate has a class of its own below, and leaving it on here would
		# mean every one of them was really testing the hold.
		season.setdefault("advance_pct", 0)
		self.make_season(**season)
		name = self.book_party(lines=[{"item": self.item, "qty": 10,
		                               "delivery_date": add_days(today(), 75)}])
		self.as_rep(order_service.submit_order, name)
		doc = frappe.get_doc("FieldMate Order", name)
		self.track("Sales Order", doc.sales_order)
		return doc

	def test_it_posts_one_sales_order(self):
		doc = self.submitted_booking()
		self.assertTrue(doc.sales_order)

	def test_the_line_carries_the_date_the_party_asked_for(self):
		doc = self.submitted_booking()
		so = frappe.get_doc("Sales Order", doc.sales_order)
		self.assertEqual(str(so.items[0].delivery_date), str(add_days(today(), 75)))

	def test_the_header_date_is_not_after_the_soonest_line(self):
		"""ERPNext refuses a Sales Order whose header date is later than a line's, and a booking
		is exactly the document where the lines differ."""
		doc = self.submitted_booking()
		so = frappe.get_doc("Sales Order", doc.sales_order)
		self.assertLessEqual(getdate(so.delivery_date),
		                     min(getdate(r.delivery_date) for r in so.items))

	def test_the_season_s_payment_terms_build_the_schedule(self):
		"""Named rather than copied: the schedule finance maintains is the one on the template,
		and a second copy of it here is a second thing to keep in step."""
		# Built rather than found. A skip here is a test that never runs: this is the one
		# assertion that proves an advance and a balance due date reach the Sales Order at all,
		# and it was skipping on every site that had no template of its own.
		template = frappe.get_doc({
			"doctype": "Payment Terms Template",
			"template_name": self.uid("TERMS"),
			"terms": [
				{"payment_term": None, "description": "Advance", "invoice_portion": 25,
				 "due_date_based_on": "Day(s) after invoice date", "credit_days": 0},
				{"payment_term": None, "description": "Balance", "invoice_portion": 75,
				 "due_date_based_on": "Day(s) after invoice date", "credit_days": 30},
			],
		}).insert(ignore_permissions=True)
		self.track("Payment Terms Template", template.name)

		doc = self.submitted_booking(payment_terms_template=template.name)
		so = frappe.get_doc("Sales Order", doc.sales_order)
		self.assertEqual(so.payment_terms_template, template.name)
		self.assertTrue(so.payment_schedule, "ERPNext builds the schedule from the template")

	def test_a_season_with_no_terms_posts_without_a_schedule_of_its_own(self):
		"""Blank is a real answer - a season sold on plain terms has none."""
		doc = self.submitted_booking()
		so = frappe.get_doc("Sales Order", doc.sales_order)
		self.assertFalse(so.payment_terms_template)


class TestABookingStopsMovingAtTheCutoff(SeasonFixture):
	def test_it_may_be_amended_before_the_cutoff(self):
		self.make_season(change_cutoff=add_days(today(), 7))
		doc = frappe.get_doc("FieldMate Order", self.book_party())
		doc.remarks = "a change the rep is still allowed to make"
		doc.save(ignore_permissions=True)   # no exception

	def test_and_not_after_it(self):
		name = self.make_season(booking_from=add_days(today(), -20),
		                        booking_to=add_days(today(), 20))
		order = frappe.get_doc("FieldMate Order", self.book_party())

		# The cutoff passes while the order sits there.
		frappe.db.set_value("FieldMate Season", name, "change_cutoff", add_days(today(), -1),
		                    update_modified=False)
		frappe.clear_document_cache("FieldMate Season", name)

		order.remarks = "too late"
		with self.assertRaises(frappe.ValidationError) as caught:
			order.save(ignore_permissions=True)
		self.assertIn("closed for changes", str(caught.exception))

	def test_an_ordinary_order_is_not_held_to_any_cutoff(self):
		result = self.book()
		doc = frappe.get_doc("FieldMate Order", result["name"])
		doc.db_set("remarks", "fine", update_modified=False)   # no exception


class TestABookingWaitsForItsAdvance(SeasonFixture):
	"""A season is the company planning against a book, and the advance is what makes the book
	worth planning against. So a booking that has not been paid for goes nowhere - no Sales
	Order, no stock set aside, no dispatch.

	It is **not** an approval. Nobody decides it: the money has arrived or it has not, so no
	manager clears it and it does not sit in anybody's approval queue.
	"""

	def book_and_submit(self, advance_pct=25, rate=100):
		self.price_item(self.item, rate)
		self.make_season(price_list=self.season_price_list(rate), advance_pct=advance_pct)
		name = self.book_party()
		self.as_rep(order_service.submit_order, name)
		return name

	def pay(self, order, amount, **extra):
		payload = {
			"party_type": "Distributor", "distributor": self.party,
			"amount": amount, "mode": "Cash",
			"client_uuid": self.uid("COL"),
			"allocations": [{"reference_type": "FieldMate Order", "reference_name": order,
			                 "allocated_amount": amount}],
		}
		payload.update(extra)
		result = self.as_rep(collection_service.create, payload, self.rep.name)
		return self.track("FieldMate Collection", result["name"])

	def test_a_booking_with_no_advance_is_held(self):
		name = self.book_and_submit()
		doc = frappe.get_doc("FieldMate Order", name)
		self.assertEqual(doc.order_status, "Awaiting Advance")
		self.assertFalse(doc.sales_order, "nothing is committed until it is paid for")

	def test_the_hold_says_what_is_owed(self):
		name = self.book_and_submit(advance_pct=25, rate=100)
		doc = frappe.get_doc("FieldMate Order", name)
		position = order_service.advance_position(doc)

		self.assertEqual(position["required"], doc.net_total * 0.25)
		self.assertEqual(position["in_hand"], 0)
		self.assertTrue(position["held"])
		self.assertIn("held until", position["message"])

	def test_it_is_not_sitting_in_an_approval_queue(self):
		"""Nobody can act on it, so it must not look like something waiting to be acted on."""
		name = self.book_and_submit()
		doc = frappe.get_doc("FieldMate Order", name)
		self.assertFalse(doc.approval_required)
		self.assertNotEqual(doc.order_status, "Pending Approval")

	def test_a_part_payment_does_not_release_it(self):
		name = self.book_and_submit(advance_pct=25, rate=100)
		required = order_service.advance_position(
			frappe.get_doc("FieldMate Order", name))["required"]
		self.pay(name, required / 2)

		doc = frappe.get_doc("FieldMate Order", name)
		self.assertEqual(doc.order_status, "Awaiting Advance")

	def test_the_advance_arriving_releases_it(self):
		name = self.book_and_submit(advance_pct=25, rate=100)
		required = order_service.advance_position(
			frappe.get_doc("FieldMate Order", name))["required"]
		self.pay(name, required)

		doc = frappe.get_doc("FieldMate Order", name)
		self.assertNotEqual(doc.order_status, "Awaiting Advance")
		self.assertTrue(doc.sales_order, "released means committed")
		self.track("Sales Order", doc.sales_order)

	def test_a_season_asking_for_nothing_releases_at_once(self):
		"""Zero is a decision somebody made on the master, not an oversight."""
		name = self.book_and_submit(advance_pct=0)
		doc = frappe.get_doc("FieldMate Order", name)
		self.assertNotEqual(doc.order_status, "Awaiting Advance")
		self.track("Sales Order", doc.sales_order)

	def test_an_ordinary_primary_order_is_never_held_for_an_advance(self):
		self.price_item(self.item, 100)
		# A season that is not booking today, so this is a plain primary order.
		self.make_season(advance_pct=90, booking_from=add_days(today(), 7),
		                 booking_to=add_days(today(), 40))
		name = self.book_party()
		self.as_rep(order_service.submit_order, name)

		doc = frappe.get_doc("FieldMate Order", name)
		self.assertEqual(doc.order_kind, "Primary")
		self.assertNotEqual(doc.order_status, "Awaiting Advance")
		self.track("Sales Order", doc.sales_order)


class TestAPostDatedChequeIsNotYetMoney(SeasonFixture):
	"""A PDC is recorded, allocated and visible - and it does not release a booking until it
	falls due. Releasing against one means reserving stock and planning a dispatch on a promise.

	No doctype of its own, and there never needed to be: FieldMate Collection already carries the
	instrument number, its date, the bank and a Bounced status, which is the whole of what a PDC
	register holds.
	"""

	def setUp(self):
		super().setUp()
		self.price_item(self.item, 100)
		self.make_season(price_list=self.season_price_list(100), advance_pct=25)
		self.order = self.book_party()
		self.as_rep(order_service.submit_order, self.order)
		self.required = order_service.advance_position(
			frappe.get_doc("FieldMate Order", self.order))["required"]

	def cheque(self, amount, dated):
		result = self.as_rep(collection_service.create, {
			"party_type": "Distributor", "distributor": self.party,
			"amount": amount, "mode": "Cheque", "instrument_no": self.uid("CHQ"),
			"instrument_date": dated, "instrument_bank": "Test Bank",
			"client_uuid": self.uid("COL"),
			"allocations": [{"reference_type": "FieldMate Order",
			                 "reference_name": self.order, "allocated_amount": amount}],
		}, self.rep.name)
		return self.track("FieldMate Collection", result["name"])

	def test_a_future_cheque_does_not_release_the_booking(self):
		self.cheque(self.required, add_days(today(), 30))
		doc = frappe.get_doc("FieldMate Order", self.order)
		self.assertEqual(doc.order_status, "Awaiting Advance")

	def test_but_it_is_listed_as_a_pdc_against_the_order(self):
		self.cheque(self.required, add_days(today(), 30))
		pdcs = collection_service.pdcs_for(self.order)
		self.assertEqual(len(pdcs), 1)
		self.assertEqual(pdcs[0]["amount"], self.required)
		self.assertEqual(str(pdcs[0]["instrument_date"]), str(add_days(today(), 30)))

	def test_the_hold_message_says_the_cheque_is_there(self):
		"""A rep who has taken a cheque would otherwise read the hold as the office losing
		their paperwork."""
		self.cheque(self.required, add_days(today(), 30))
		position = order_service.advance_position(
			frappe.get_doc("FieldMate Order", self.order))
		self.assertEqual(position["pdc_total"], self.required)
		self.assertIn("post-dated", position["message"])

	def test_a_cheque_dated_today_is_money(self):
		"""The line is the date, not the instrument. A cheque handed over today is an advance."""
		self.cheque(self.required, today())
		doc = frappe.get_doc("FieldMate Order", self.order)
		self.assertNotEqual(doc.order_status, "Awaiting Advance")
		self.track("Sales Order", doc.sales_order)

	def test_a_cheque_that_has_fallen_due_stops_being_a_pdc(self):
		name = self.cheque(self.required, add_days(today(), 30))
		self.assertTrue(collection_service.pdcs_for(self.order))

		frappe.db.set_value("FieldMate Collection", name, "instrument_date", today(),
		                    update_modified=False)
		self.assertFalse(collection_service.pdcs_for(self.order))

	def test_a_bounced_cheque_is_neither_money_nor_a_pdc(self):
		name = self.cheque(self.required, add_days(today(), 30))
		frappe.db.set_value("FieldMate Collection", name, "status", "Bounced",
		                    update_modified=False)
		self.assertFalse(collection_service.pdcs_for(self.order))
		self.assertFalse(collection_service.in_hand_by_order([self.order]))


class TestAnEarlyBookingOffer(SeasonFixture):
	"""An offer that rewards booking early is two conditions the scheme did not have: when the
	order was **taken**, and whether the deal carries an advance.

	Both are about the order, not about where it was booked, so they sit beside `covers_sale`
	rather than inside the scope rows.
	"""

	def setUp(self):
		super().setUp()
		self.price_item(self.item, 100)

	def offer(self, **kwargs):
		"""A scheme that reaches everywhere, so only the new conditions decide anything.

		Returns the name. `make_scheme` hands back the document, and comparing a document to a
		list of names is a test that fails for a reason that has nothing to do with the code.
		"""
		data = {"applies_to": "Primary", "applies_everywhere": 1,
		        # Live well before any order these tests take, so that `is_live_on` is never
		        # what decides the answer - these tests are about the booking window.
		        "valid_from": add_days(today(), -90), "valid_to": add_days(today(), 90)}
		data.update(kwargs)
		return self.make_scheme(**data).name

	def specs_for_a_booking(self, **season):
		season.setdefault("advance_pct", 25)
		self.make_season(**season)
		doc = frappe.get_doc("FieldMate Order", self.book_party())
		compiled = scheme_compile.for_outlet(
			self.party, self.rep.name, on_date=doc.order_date, party_type="Customer",
			kind=doc.order_kind, season=doc.season)
		return [spec["scheme"] for spec in compiled["specs"]]

	# ------------------------------------------------------------------ the booking window

	def test_an_offer_with_no_window_reaches_every_order(self):
		"""Which is every ordinary scheme, and must stay true."""
		name = self.offer()
		self.assertIn(name, self.specs_for_a_booking())

	def test_an_order_taken_inside_the_window_earns_it(self):
		name = self.offer(booking_from=add_days(today(), -5), booking_to=add_days(today(), 5))
		self.assertIn(name, self.specs_for_a_booking())

	def test_an_order_taken_after_the_book_shut_does_not(self):
		name = self.offer(booking_from=add_days(today(), -20), booking_to=add_days(today(), -1))
		self.assertNotIn(name, self.specs_for_a_booking())

	def test_an_order_taken_before_it_opened_does_not(self):
		name = self.offer(booking_from=add_days(today(), 1))
		self.assertNotIn(name, self.specs_for_a_booking())

	def test_the_window_is_read_against_the_order_date_not_today(self):
		"""A rep syncing in December must not have November's orders judged against December.
		The order date is what the party was quoted on."""
		name = self.offer(booking_from=add_days(today(), -20), booking_to=add_days(today(), -10))
		self.make_season(advance_pct=0)
		doc = frappe.get_doc("FieldMate Order",
		                     self.book_party(order_date=add_days(today(), -15)))
		compiled = scheme_compile.for_outlet(
			self.party, self.rep.name, on_date=doc.order_date, party_type="Customer",
			kind=doc.order_kind, season=doc.season)
		self.assertIn(name, [spec["scheme"] for spec in compiled["specs"]])

	def test_it_is_a_different_question_from_being_live(self):
		"""Live from November to March because that is when it is billed; rewarding only the
		orders booked in November."""
		name = self.offer(valid_from=add_days(today(), -60), valid_to=add_days(today(), 60),
		                  booking_from=add_days(today(), -60), booking_to=add_days(today(), -1))
		scheme = frappe.get_doc("FieldMate Scheme", name)
		self.assertTrue(scheme.is_live_on(today()), "the offer exists today")
		self.assertFalse(scheme.books_in(today()), "but its book shut yesterday")

	# ------------------------------------------------------------------ the advance

	def test_an_offer_asking_for_an_advance_reaches_a_season_that_asks_for_as_much(self):
		name = self.offer(requires_advance_pct=25)
		self.assertIn(name, self.specs_for_a_booking(advance_pct=25))

	def test_and_a_season_that_asks_for_more(self):
		name = self.offer(requires_advance_pct=25)
		self.assertIn(name, self.specs_for_a_booking(advance_pct=50))

	def test_but_not_one_that_asks_for_less(self):
		name = self.offer(requires_advance_pct=50)
		self.assertNotIn(name, self.specs_for_a_booking(advance_pct=25))

	def test_nor_an_order_that_is_not_a_booking_at_all(self):
		"""There is no season behind it, so there is no advance for the offer to be met by."""
		name = self.offer(requires_advance_pct=25)
		self.make_season(booking_from=add_days(today(), 7), booking_to=add_days(today(), 40))
		doc = frappe.get_doc("FieldMate Order", self.book_party())
		self.assertEqual(doc.order_kind, "Primary")

		compiled = scheme_compile.for_outlet(
			self.party, self.rep.name, on_date=doc.order_date, party_type="Customer",
			kind=doc.order_kind, season=doc.season)
		self.assertNotIn(name, [spec["scheme"] for spec in compiled["specs"]])

	def test_an_offer_asking_for_nothing_is_unaffected(self):
		name = self.offer(requires_advance_pct=0)
		self.assertIn(name, self.specs_for_a_booking(advance_pct=0))

	# ------------------------------------------------------------------ what reaches the phone

	def test_the_window_travels_in_the_spec(self):
		"""So a phone three days behind on its sync retires the offer itself rather than
		quoting one whose book shut on Sunday. The JS half of `liveSpecs` reads these."""
		opens, closes = add_days(today(), -5), add_days(today(), 5)
		name = self.offer(booking_from=opens, booking_to=closes)
		self.make_season(advance_pct=0)
		doc = frappe.get_doc("FieldMate Order", self.book_party())
		compiled = scheme_compile.for_outlet(
			self.party, self.rep.name, on_date=doc.order_date, party_type="Customer",
			kind=doc.order_kind, season=doc.season)

		spec = next(s for s in compiled["specs"] if s["scheme"] == name)
		self.assertEqual(spec["booking_from"], str(opens))
		self.assertEqual(spec["booking_to"], str(closes))

	def test_an_offer_with_no_window_says_so_rather_than_omitting_it(self):
		"""A key the phone can read as "no window" beats a key it has to guess about."""
		name = self.offer()
		self.make_season(advance_pct=0)
		doc = frappe.get_doc("FieldMate Order", self.book_party())
		compiled = scheme_compile.for_outlet(
			self.party, self.rep.name, on_date=doc.order_date, party_type="Customer",
			kind=doc.order_kind, season=doc.season)

		spec = next(s for s in compiled["specs"] if s["scheme"] == name)
		self.assertIn("booking_from", spec)
		self.assertIsNone(spec["booking_from"])

	def test_a_scheme_read_before_the_migration_has_run_does_not_crash(self):
		"""The same deploy window `covers_sale` was found in: the code has landed, the columns
		have not, and reading them as attributes fails every order on that site."""
		scheme = frappe.get_doc("FieldMate Scheme", self.offer())
		del scheme.booking_from
		del scheme.booking_to
		del scheme.requires_advance_pct
		self.assertTrue(scheme.books_in(today()))
		self.assertTrue(scheme.advance_met(0))
