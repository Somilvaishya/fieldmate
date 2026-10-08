"""Phase 2, step 7 — where a season has got to, who is late, and adding to a booking.

Everything the cockpit answers is **read from the documents that hold it**: the booking, the
reservations ERPNext holds, the Delivery Notes that went out, the invoices behind them and the
collections against the order. So these tests build the real documents and then ask.

A cockpit that kept its own numbers would be a fifth opinion to reconcile, and it would be the
one nobody trusts the morning it disagrees — which is why there is no test here for a stored
figure, and why there should never be one.
"""

import frappe
from frappe.utils import add_days, flt, today

from fieldmate import compat
from fieldmate.services import allocation as allocation_service
from fieldmate.services import cockpit as cockpit_service
from fieldmate.services import collection as collection_service
from fieldmate.services import order as order_service
from fieldmate.tests.test_season import SeasonFixture


class CockpitFixture(SeasonFixture):
	def setUp(self):
		super().setUp()
		self.price_item(self.item, 100)
		self.close_other_seasons()
		self.season = self.make_season(price_list=self.season_price_list(100), advance_pct=0)

	def close_other_seasons(self):
		for name in frappe.get_all("FieldMate Season",
		                           filters={"company": self.company, "is_active": 1},
		                           pluck="name"):
			frappe.db.set_value("FieldMate Season", name, "is_active", 0, update_modified=False)
		frappe.db.commit()

	def tearDown(self):
		try:
			frappe.db.set_value("FieldMate Season", self.season, "is_active", 0,
			                    update_modified=False)
			frappe.db.commit()
		except Exception:
			pass
		super().tearDown()

	def book(self, qty=10, submit=True, **extra):
		payload = {"party_type": "Customer", "customer": self.party,
		           "lines": [{"item": self.item, "qty": qty}],
		           "client_uuid": self.uid("BOOK")}
		payload.update(extra)
		created = self.as_rep(order_service.create, payload, self.rep.name)
		name = self.track("FieldMate Order", created["name"])
		if submit:
			self.as_rep(order_service.submit_order, name)
			so = frappe.db.get_value("FieldMate Order", name, "sales_order")
			if so:
				self.track("Sales Order", so)
		return name

	def pay(self, order, amount):
		result = self.as_rep(collection_service.create, {
			"party_type": "Distributor", "distributor": self.party, "amount": amount,
			"mode": "Cash", "client_uuid": self.uid("COL"),
			"allocations": [{"reference_type": "FieldMate Order", "reference_name": order,
			                 "allocated_amount": amount}],
		}, self.rep.name)
		return self.track("FieldMate Collection", result["name"])


class TestWhereASeasonHasGotTo(CockpitFixture):
	def test_a_fresh_booking_reads_as_booked(self):
		self.book()
		states = {row["state"]: row for row in cockpit_service.by_state(self.season)}
		self.assertEqual(states["Booked"]["bookings"], 1)
		self.assertEqual(states["Delivered"]["bookings"], 0)

	def test_every_state_is_listed_even_when_empty(self):
		"""A row missing from a summary reads as a state that does not exist, and "nothing has
		been delivered yet" is an answer somebody needs."""
		self.book()
		listed = [row["state"] for row in cockpit_service.by_state(self.season)]
		self.assertEqual(listed, list(cockpit_service.STATES))

	def test_a_booking_waiting_for_its_advance_says_so(self):
		frappe.db.set_value("FieldMate Season", self.season, "advance_pct", 50,
		                    update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)
		self.book()

		states = {row["state"]: row for row in cockpit_service.by_state(self.season)}
		self.assertEqual(states["Awaiting advance"]["bookings"], 1)
		self.assertEqual(states["Booked"]["bookings"], 0)

	def test_the_value_is_the_bill_not_the_goods(self):
		"""What the party is asked for. A cockpit short by the tax is a cockpit somebody
		reconciles against the ledger and gives up on."""
		name = self.book()
		doc = frappe.get_doc("FieldMate Order", name)
		total = flt(doc.grand_total) or flt(doc.net_total)
		self.assertEqual(cockpit_service.summary(self.season)["value"], total)


class TestWhoToTelephone(CockpitFixture):
	def test_one_line_per_party_with_what_they_owe(self):
		name = self.book(qty=10)
		doc = frappe.get_doc("FieldMate Order", name)
		self.pay(name, 100)

		rows = cockpit_service.by_party(self.season)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["customer"], self.party)
		self.assertEqual(rows[0]["paid"], 100)
		self.assertEqual(rows[0]["owing"],
		                 flt((flt(doc.grand_total) or flt(doc.net_total)) - 100, 2))

	def test_two_bookings_of_one_party_are_one_line(self):
		self.book()
		self.book()
		rows = cockpit_service.by_party(self.season)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["bookings"], 2)

	def test_a_party_is_shown_at_its_furthest_back_booking(self):
		"""Because that is the one holding them up, and the cockpit is opened to find out who to
		telephone."""
		frappe.db.set_value("FieldMate Season", self.season, "advance_pct", 50,
		                    update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)
		self.book()      # held for its advance
		frappe.db.set_value("FieldMate Season", self.season, "advance_pct", 0,
		                    update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)
		self.book()      # goes straight through

		rows = cockpit_service.by_party(self.season)
		self.assertEqual(rows[0]["state"], "Awaiting advance")


class TestWhatWeAreShortOf(CockpitFixture):
	def test_one_line_per_item_with_what_was_booked(self):
		self.book(qty=10)
		rows = cockpit_service.by_sku(self.season)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["item_code"], self.item)
		self.assertEqual(rows[0]["booked_qty"], 10)

	def test_nothing_reserved_is_all_short(self):
		self.book(qty=10)
		self.assertEqual(cockpit_service.by_sku(self.season)[0]["short"], 10)

	def test_what_is_reserved_comes_off_the_shortfall(self):
		if not compat.stock_reservation_enabled():
			self.skipTest("stock reservation is switched off on this site")

		warehouse = frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not warehouse:
			self.skipTest("this company has no leaf warehouse")
		frappe.db.set_value("Customer", self.party, "fm_warehouse", warehouse,
		                    update_modified=False)
		frappe.clear_document_cache("Customer", self.party)

		self.book(qty=10)
		entry = frappe.get_doc({
			"doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
			"company": self.company,
			"items": [{"item_code": self.item, "qty": 10, "t_warehouse": warehouse,
			           "basic_rate": 50}],
		})
		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()
		self.track("Stock Entry", entry.name)

		allocation_service.apply(self.season, allocation_service.PRO_RATA)
		self.addCleanup(lambda: allocation_service.revert(self.season))

		row = cockpit_service.by_sku(self.season)[0]
		self.assertEqual(row["reserved_qty"], 10)
		self.assertEqual(row["short"], 0)


class TestWhoIsLate(CockpitFixture):
	def overdue_booking(self, days_late=5):
		"""A submitted booking whose Sales Order has a payment schedule row in the past."""
		name = self.book()
		sales_order = frappe.db.get_value("FieldMate Order", name, "sales_order")
		schedule = frappe.get_doc({
			"doctype": "Payment Schedule", "parent": sales_order,
			"parenttype": "Sales Order", "parentfield": "payment_schedule",
			"due_date": add_days(today(), -days_late), "invoice_portion": 100,
			"payment_amount": 500, "outstanding": 500, "idx": 1,
		})
		schedule.flags.ignore_permissions = True
		schedule.insert(ignore_permissions=True)
		self.track("Payment Schedule", schedule.name)
		return name

	def test_a_booking_past_its_due_date_is_listed(self):
		name = self.overdue_booking(days_late=5)
		late = [row for row in cockpit_service.overdue_payments() if row["order"] == name]
		self.assertEqual(len(late), 1)
		self.assertEqual(late[0]["days_late"], 5)
		self.assertEqual(late[0]["short"], 500)

	def test_one_that_has_been_paid_is_not(self):
		name = self.overdue_booking()
		self.pay(name, 500)
		self.assertNotIn(name, [row["order"] for row in cockpit_service.overdue_payments()])

	def test_a_booking_with_no_schedule_is_not_late(self):
		"""A season sold on open terms has none, and that is a decision rather than an
		oversight."""
		name = self.book()
		self.assertNotIn(name, [row["order"] for row in cockpit_service.overdue_payments()])

	def test_the_rep_and_their_manager_are_told(self):
		name = self.overdue_booking()
		answer = cockpit_service.remind_overdue()
		self.assertGreaterEqual(answer["overdue"], 1)

		told = frappe.get_all("Notification Log",
		                      filters={"document_type": "FieldMate Order",
		                               "document_name": name},
		                      pluck="for_user")
		self.assertIn(self.rep.user, told)

	def test_nobody_is_told_twice_in_a_day(self):
		"""A job that runs twice must not telephone a rep twice about the same booking."""
		name = self.overdue_booking()
		cockpit_service.remind_overdue()
		first = frappe.db.count("Notification Log", {"document_type": "FieldMate Order",
		                                            "document_name": name})
		cockpit_service.remind_overdue()
		self.assertEqual(
			frappe.db.count("Notification Log", {"document_type": "FieldMate Order",
			                                     "document_name": name}), first)


class TestTheCutoffLock(CockpitFixture):
	def test_a_season_inside_its_cutoff_is_open(self):
		frappe.db.set_value("FieldMate Season", self.season, "change_cutoff",
		                    add_days(today(), 7), update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)
		self.assertFalse(cockpit_service.is_locked(self.season))

	def test_and_one_past_it_is_locked(self):
		frappe.db.set_value("FieldMate Season", self.season, "change_cutoff",
		                    add_days(today(), -1), update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)
		self.assertTrue(cockpit_service.is_locked(self.season))

	def test_the_summary_says_so(self):
		frappe.db.set_value("FieldMate Season", self.season, "change_cutoff",
		                    add_days(today(), -1), update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)
		self.assertTrue(cockpit_service.summary(self.season)["locked"])


class TestToppingUpABooking(CockpitFixture):
	def test_a_second_booking_can_name_the_first(self):
		"""A party that booked in November and wants more in January books again, at the
		season's terms, against the same season."""
		first = self.book()
		second = self.book(tops_up=first)
		self.assertEqual(frappe.db.get_value("FieldMate Order", second, "tops_up"), first)

	def test_it_must_be_the_same_party(self):
		first = self.book()
		other = frappe.get_doc({
			"doctype": "Customer", "customer_name": self.uid("OTHER"),
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": self.rep.territory,
		}).insert(ignore_permissions=True)
		self.track("Customer", other.name)
		frappe.db.set_value("Customer", other.name,
		                    {"fm_tier": "Distributor", "fm_buys_from": "Company"},
		                    update_modified=False)
		frappe.clear_document_cache("Customer", other.name)

		with self.assertRaises(frappe.ValidationError) as caught:
			self.as_rep(order_service.create, {
				"party_type": "Customer", "customer": other.name,
				"lines": [{"item": self.item, "qty": 5}],
				"client_uuid": self.uid("BOOK"), "tops_up": first,
			}, self.rep.name)
		self.assertIn("same party", str(caught.exception))

	def test_it_cannot_top_up_an_unsubmitted_booking(self):
		draft = self.book(submit=False)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.book(tops_up=draft)
		self.assertIn("not been submitted", str(caught.exception))

	def test_it_cannot_top_up_something_that_is_not_a_booking(self):
		"""No season open, so this is an ordinary primary order."""
		frappe.db.set_value("FieldMate Season", self.season, "is_active", 0,
		                    update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)
		plain = self.book()

		frappe.db.set_value("FieldMate Season", self.season, "is_active", 1,
		                    update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)
		with self.assertRaises(frappe.ValidationError) as caught:
			self.book(tops_up=plain)
		self.assertIn("not a booking", str(caught.exception))

	def test_a_top_up_counts_in_the_cockpit_like_any_other_booking(self):
		first = self.book()
		self.book(tops_up=first)
		self.assertEqual(cockpit_service.summary(self.season)["bookings"], 2)
		self.assertEqual(cockpit_service.by_party(self.season)[0]["bookings"], 2)

	def test_the_cutoff_does_not_stop_a_top_up(self):
		"""Adding to a booking is not amending one: the original is untouched and nothing already
		planned moves. The booking window is what closes the book, and `channel.resolve` enforces
		that by refusing to call a late order a booking at all."""
		first = self.book()
		frappe.db.set_value("FieldMate Season", self.season, "change_cutoff",
		                    add_days(today(), -1), update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)

		second = self.book(tops_up=first)
		self.assertEqual(frappe.db.get_value("FieldMate Order", second, "order_kind"), "Booking")


class TestThePageItself(CockpitFixture):
	"""The whitelisted methods behind the cockpit page.

	Checked because of what `/distributor/sales` turned out to be: a page with a test that called
	its context builder and never drew anything, passing for weeks over a 500. These at least
	prove the methods answer and that the wrong person is refused.
	"""

	def page(self):
		from fieldmate.fieldmate.page.fieldmate_season_cockpit import (
			fieldmate_season_cockpit as module,
		)
		return module

	def test_a_manager_can_read_the_season(self):
		self.book()
		answer = self.page().summary(self.season)
		self.assertEqual(answer["season"], self.season)
		self.assertEqual(answer["bookings"], 1)

	def test_the_season_list_names_only_seasons_that_exist(self):
		listed = [row["name"] for row in self.page().seasons()]
		self.assertIn(self.season, listed)

	def test_a_rep_cannot_read_a_season_book(self):
		"""A season's book is commercial information: who booked what, who has paid, who has
		not. A rep sells; they do not get the whole company's position."""
		frappe.set_user(self.rep.user)
		try:
			with self.assertRaises(frappe.PermissionError):
				self.page().summary(self.season)
		finally:
			frappe.set_user("Administrator")

	def test_the_overdue_list_can_be_narrowed_to_one_season(self):
		self.book()
		rows = self.page().overdue(self.season)
		self.assertTrue(all(row["season"] == self.season for row in rows))
