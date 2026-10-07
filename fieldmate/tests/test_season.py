"""Phase 2, step 1 — a season, and the one rule that makes an order a booking of it.

    a primary order dated inside the booking window of its company's active season
    is a booking of that season

There is no booking flag for a rep to tick and no rule table scoring a season against a party.
The dates say what the order was, the same way the party says what kind of sale it is.
"""

import frappe
from frappe.utils import add_days, today

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
