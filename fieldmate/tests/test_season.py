"""Phase 2, step 1 — a season, and the one rule that makes an order a booking of it.

    a primary order dated inside the booking window of its company's active season
    is a booking of that season

There is no booking flag for a rep to tick and no rule table scoring a season against a party.
The dates say what the order was, the same way the party says what kind of sale it is.
"""

import frappe
from frappe.utils import add_days, getdate, today

from fieldmate.services import order as order_service
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
		self.make_season(price_list=season_list)
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
