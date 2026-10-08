"""Phase 2, step 5 — who gets the stock when a season is short of it.

Two halves, tested apart on purpose.

The **split** is arithmetic over plain dicts: no site, no stock, no ERPNext. A rule that divides
short stock between distributors is the thing people will argue about at month end, and it has to
be possible to read its test and see what it does.

The **reservation** is ERPNext's, so those tests build real stock and read back real Stock
Reservation Entries. They skip where the feature is switched off rather than asserting nothing:
a green test on a site that reserved nothing would be worse than no test.
"""

import frappe
from frappe.utils import add_days, today

from fieldmate import compat
from fieldmate.services import allocation as allocation_service
from fieldmate.services import collection as collection_service
from fieldmate.services import order as order_service
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_season import SeasonFixture


def rows(*asks):
	"""Bookings as `split` sees them: (order, asked, advance share, order date)."""
	return [
		{"order": name, "asked": asked, "advance_share": share, "order_date": date}
		for name, asked, share, date in asks
	]


class TestHowShortStockIsDivided(FieldMateTestCase):
	"""Pure arithmetic. The three rules are the three arguments people actually have."""

	def test_everybody_gets_everything_when_there_is_enough(self):
		table = rows(("A", 10, 0.0, "2026-11-01"), ("B", 20, 0.0, "2026-11-02"))
		allocation_service.split(table, 30, allocation_service.PRO_RATA)
		self.assertEqual([r["allocated"] for r in table], [10, 20])

	def test_and_when_there_is_more_than_enough(self):
		table = rows(("A", 10, 0.0, "2026-11-01"))
		allocation_service.split(table, 999, allocation_service.FIRST_BOOKED)
		self.assertEqual(table[0]["allocated"], 10)

	def test_nothing_available_allocates_nothing(self):
		table = rows(("A", 10, 1.0, "2026-11-01"))
		allocation_service.split(table, 0, allocation_service.ADVANCE_FIRST)
		self.assertEqual(table[0]["allocated"], 0)

	# ------------------------------------------------------------------ first booked

	def test_first_booked_serves_the_queue_in_order(self):
		table = rows(("LATE", 60, 1.0, "2026-11-20"), ("EARLY", 60, 0.0, "2026-11-01"))
		allocation_service.split(table, 100, allocation_service.FIRST_BOOKED)
		got = {r["order"]: r["allocated"] for r in table}
		self.assertEqual(got, {"EARLY": 60, "LATE": 40})

	def test_first_booked_ignores_who_paid(self):
		"""Which is the whole difference between it and Advance First."""
		table = rows(("PAID", 60, 1.0, "2026-11-20"), ("UNPAID", 60, 0.0, "2026-11-01"))
		allocation_service.split(table, 60, allocation_service.FIRST_BOOKED)
		got = {r["order"]: r["allocated"] for r in table}
		self.assertEqual(got, {"UNPAID": 60, "PAID": 0})

	# ------------------------------------------------------------------ advance first

	def test_advance_first_serves_whoever_committed_hardest(self):
		table = rows(("HALF", 60, 0.5, "2026-11-01"), ("FULL", 60, 1.0, "2026-11-20"))
		allocation_service.split(table, 60, allocation_service.ADVANCE_FIRST)
		got = {r["order"]: r["allocated"] for r in table}
		self.assertEqual(got, {"FULL": 60, "HALF": 0})

	def test_it_is_a_share_of_their_own_booking_not_a_figure(self):
		"""A small distributor who has paid for all of theirs has committed harder than a large
		one who has paid for a tenth, and the rule is about who committed hardest."""
		table = rows(("SMALL", 10, 1.0, "2026-11-01"), ("LARGE", 500, 0.1, "2026-11-01"))
		allocation_service.split(table, 10, allocation_service.ADVANCE_FIRST)
		got = {r["order"]: r["allocated"] for r in table}
		self.assertEqual(got, {"SMALL": 10, "LARGE": 0})

	def test_a_tie_on_the_advance_falls_back_to_who_booked_first(self):
		"""So the order is total: two previews of the same figures cannot differ."""
		table = rows(("LATER", 60, 0.5, "2026-11-20"), ("SOONER", 60, 0.5, "2026-11-01"))
		allocation_service.split(table, 60, allocation_service.ADVANCE_FIRST)
		got = {r["order"]: r["allocated"] for r in table}
		self.assertEqual(got, {"SOONER": 60, "LATER": 0})

	# ------------------------------------------------------------------ pro rata

	def test_pro_rata_cuts_everybody_by_the_same_proportion(self):
		table = rows(("A", 100, 0.0, "2026-11-01"), ("B", 100, 0.0, "2026-11-02"))
		allocation_service.split(table, 100, allocation_service.PRO_RATA)
		self.assertEqual([r["allocated"] for r in table], [50, 50])

	def test_pro_rata_splits_unequal_asks_in_proportion(self):
		table = rows(("A", 300, 0.0, "2026-11-01"), ("B", 100, 0.0, "2026-11-02"))
		allocation_service.split(table, 200, allocation_service.PRO_RATA)
		got = {r["order"]: r["allocated"] for r in table}
		self.assertEqual(got, {"A": 150, "B": 50})

	def test_pro_rata_gives_nothing_away_to_rounding(self):
		"""Flooring leaves a unit over and it has to land somewhere - on the largest ask, ties
		by order name, so every machine that computes this lands it in the same place."""
		table = rows(("A", 10, 0.0, "2026-11-01"), ("B", 10, 0.0, "2026-11-02"),
		             ("C", 10, 0.0, "2026-11-03"))
		allocation_service.split(table, 10, allocation_service.PRO_RATA)
		self.assertEqual(sum(r["allocated"] for r in table), 10)

	def test_pro_rata_is_the_same_whatever_order_the_rows_arrive_in(self):
		forwards = rows(("A", 7, 0.0, "2026-11-01"), ("B", 13, 0.0, "2026-11-02"))
		backwards = rows(("B", 13, 0.0, "2026-11-02"), ("A", 7, 0.0, "2026-11-01"))
		allocation_service.split(forwards, 11, allocation_service.PRO_RATA)
		allocation_service.split(backwards, 11, allocation_service.PRO_RATA)
		self.assertEqual({r["order"]: r["allocated"] for r in forwards},
		                 {r["order"]: r["allocated"] for r in backwards})

	def test_an_unknown_rule_is_refused_rather_than_guessed_at(self):
		with self.assertRaises(frappe.ValidationError):
			allocation_service.preview("no-such-season", "Whoever Shouts Loudest")


class TestAllocatingARealSeason(SeasonFixture):
	"""The other half: real bookings, real stock, real Stock Reservation Entries."""

	def setUp(self):
		super().setUp()
		if not compat.stock_reservation_enabled():
			self.skipTest("stock reservation is switched off on this site")
		self.price_item(self.item, 100)
		self.season = self.make_season(price_list=self.season_price_list(100), advance_pct=0)
		self.warehouse = frappe.db.get_value(
			"Warehouse", {"company": self.company, "is_group": 0}, "name")
		if not self.warehouse:
			self.skipTest("this company has no leaf warehouse")
		# The depot that serves this party, which is where its bookings will be reserved from.
		# Without it ERPNext defaults a warehouse per line from the Item master, and a test that
		# stocks one warehouse while the Sales Order names another proves nothing at all - which
		# is exactly how these first ran.
		frappe.db.set_value("Customer", self.party, "fm_warehouse", self.warehouse,
		                    update_modified=False)
		frappe.clear_document_cache("Customer", self.party)

	def tearDown(self):
		try:
			allocation_service.revert(self.season)
		except Exception:
			pass
		super().tearDown()

	def booking(self, qty, on=None, advance=0):
		payload = {"party_type": "Customer", "customer": self.party,
		           "lines": [{"item": self.item, "qty": qty}],
		           "client_uuid": self.uid("BOOK")}
		if on:
			payload["order_date"] = on
		created = self.as_rep(order_service.create, payload, self.rep.name)
		name = self.track("FieldMate Order", created["name"])
		if advance:
			result = self.as_rep(collection_service.create, {
				"party_type": "Distributor", "distributor": self.party, "amount": advance,
				"mode": "Cash", "client_uuid": self.uid("COL"),
				"allocations": [{"reference_type": "FieldMate Order", "reference_name": name,
				                 "allocated_amount": advance}],
			}, self.rep.name)
			self.track("FieldMate Collection", result["name"])
		self.as_rep(order_service.submit_order, name)
		so = frappe.db.get_value("FieldMate Order", name, "sales_order")
		self.track("Sales Order", so)
		return name, so

	def stock(self, qty):
		"""Put real stock in the party's own warehouse, so ERPNext has something to reserve."""
		entry = frappe.get_doc({
			"doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
			"company": self.company,
			"items": [{"item_code": self.item, "qty": qty, "t_warehouse": self.warehouse,
			           "basic_rate": 50}],
		})
		entry.flags.ignore_permissions = True
		entry.insert(ignore_permissions=True)
		entry.submit()
		self.track("Stock Entry", entry.name)

	def test_a_released_booking_is_what_gets_allocated(self):
		name, _ = self.booking(10)
		found = [row["name"] for row in allocation_service.bookings_of(self.season)]
		self.assertIn(name, found)

	def test_a_booking_still_waiting_for_its_advance_is_not(self):
		"""It has no Sales Order, so there is no line to reserve - and reserving stock for an
		order nobody has paid for is what the advance hold exists to prevent."""
		frappe.db.set_value("FieldMate Season", self.season, "advance_pct", 50,
		                    update_modified=False)
		frappe.clear_document_cache("FieldMate Season", self.season)

		payload = {"party_type": "Customer", "customer": self.party,
		           "lines": [{"item": self.item, "qty": 10}], "client_uuid": self.uid("BOOK")}
		created = self.as_rep(order_service.create, payload, self.rep.name)
		held = self.track("FieldMate Order", created["name"])
		self.as_rep(order_service.submit_order, held)

		self.assertEqual(
			frappe.db.get_value("FieldMate Order", held, "order_status"), "Awaiting Advance")
		self.assertNotIn(held, [r["name"] for r in allocation_service.bookings_of(self.season)])

	def test_a_preview_changes_nothing(self):
		self.booking(10)
		self.stock(100)
		plan = allocation_service.preview(self.season, allocation_service.PRO_RATA)
		self.assertTrue(plan["items"])
		self.assertEqual(allocation_service.held_by(self.season), [],
		                 "a preview is a preview")

	def test_applying_reserves_in_erpnext(self):
		so = self.booking(10)[1]
		self.stock(100)
		allocation_service.apply(self.season, allocation_service.PRO_RATA)

		held = compat.reserved_for_sales_order(so)
		self.assertTrue(held, "ERPNext is holding stock against the booking")
		self.assertEqual(sum(row["reserved_qty"] for row in held), 10)

	def test_short_stock_is_divided_rather_than_refused(self):
		"""The point of allocating is that somebody gets less than they asked for."""
		first, so_first = self.booking(60, on=add_days(today(), -2))
		second, so_second = self.booking(60, on=today())

		self.stock(100)
		allocation_service.apply(self.season, allocation_service.FIRST_BOOKED)

		got = {
			first: sum(r["reserved_qty"] for r in compat.reserved_for_sales_order(so_first)),
			second: sum(r["reserved_qty"] for r in compat.reserved_for_sales_order(so_second)),
		}
		self.assertEqual(got[first], 60, "booked first, served first")
		self.assertEqual(got[second], 40, "and the rest got what was left")

	def test_reverting_gives_it_all_back(self):
		so = self.booking(10)[1]
		self.stock(100)
		allocation_service.apply(self.season, allocation_service.PRO_RATA)
		self.assertTrue(compat.reserved_for_sales_order(so))

		answer = allocation_service.revert(self.season)
		self.assertTrue(answer["released"])
		self.assertFalse(compat.reserved_for_sales_order(so))

	def test_reverting_twice_is_not_an_error(self):
		"""The ordinary state of a Desk button somebody pressed twice."""
		self.booking(10)
		self.stock(100)
		allocation_service.apply(self.season, allocation_service.PRO_RATA)
		allocation_service.revert(self.season)
		self.assertEqual(allocation_service.revert(self.season)["released"], 0)

	def test_what_is_held_is_read_back_from_erpnext(self):
		"""The answer to "what did we allocate" is never a figure we kept."""
		name, _ = self.booking(10)
		self.stock(100)
		allocation_service.apply(self.season, allocation_service.PRO_RATA)

		held = allocation_service.held_by(self.season)
		self.assertEqual(len(held), 1)
		self.assertEqual(held[0]["order"], name)
		self.assertEqual(held[0]["reserved"], 10)

	def test_a_second_preview_sees_what_is_left_not_what_was_there(self):
		"""ERPNext subtracts live reservations from what it calls available, so a preview run
		after an apply is of the remainder. Reverting first is what gives a clean slate."""
		self.booking(10)
		self.stock(10)
		before = allocation_service.preview(self.season, allocation_service.PRO_RATA)
		self.assertEqual(before["items"][0]["available"], 10)

		allocation_service.apply(self.season, allocation_service.PRO_RATA)
		after = allocation_service.preview(self.season, allocation_service.PRO_RATA)
		self.assertEqual(after["items"][0]["available"], 0)
		self.assertTrue(after["already_reserved"], "and it says so")
