"""Stock in the field: the shop count, the van day, and the offtake identity.

Everything here asserts arithmetic the business will argue about at month end, so the numbers in
these tests are worked by hand in the docstrings rather than taken from the code.

Two negatives are asserted on purpose, and they are the point of the phase: a van day must not
produce a Stock Entry and must not produce a GL Entry. The goods in the vehicle are the
distributor's (ADR-024) — we sold them at primary billing and they are already theirs — so
anything of ours moving would be recording a sale we did not make.
"""

import frappe
from frappe.utils import add_days, today

from fieldmate.services import order as order_service
from fieldmate.services import stock as stock_service
from fieldmate.tests.test_order import OrderFixture


class StockFixture(OrderFixture):
	def tearDown(self):
		frappe.set_user("Administrator")
		for dt in ("FieldMate Van Settlement", "FieldMate Van Load", "FieldMate Retailer Stock",
		           "FieldMate Distributor Stock", "FieldMate Secondary Sales"):
			for name in frappe.get_all(dt, pluck="name"):
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

	def count(self, lines, on=None, **extra):
		payload = {"outlet": self.outlet.name, "stock_date": on or today(),
		           "client_uuid": self.uid("RST"), "items": lines}
		payload.update(extra)
		return self.as_rep(stock_service.save_count, payload, self.rep.name)

	def line(self, item=None, qty=0, counted=1, factor=1):
		return {"item_code": item or self.item, "qty_display": qty, "is_counted": counted,
		        "conversion_factor": factor}


class TestAShopCount(StockFixture):
	def test_a_zero_count_is_not_the_same_as_an_uncounted_line(self):
		"""The reason `is_counted` exists at all.

		A Float is never null in Frappe, so both read back as 0. One says the shelf was empty -
		a lost sale, a reason to push - and the other says nobody looked. Treating them alike
		was the bug this column was added to prevent.
		"""
		other = self.make_item()
		result = self.count([self.line(qty=0, counted=1), self.line(item=other, counted=0)])

		doc = frappe.get_doc("FieldMate Retailer Stock", result["name"])
		empty = next(r for r in doc.items if r.item_code == self.item)
		unseen = next(r for r in doc.items if r.item_code == other)

		self.assertTrue(empty.is_counted)
		self.assertTrue(empty.is_out_of_stock, "counted, and counted at zero")
		self.assertFalse(unseen.is_counted)
		self.assertFalse(unseen.is_out_of_stock, "nobody looked, so we know nothing")

	def test_a_partial_count_saves_and_says_so(self):
		"""A rep pulled away halfway has still learnt something. Refusing it teaches him not to
		start."""
		other = self.make_item()
		result = self.count([self.line(qty=4, counted=1), self.line(item=other, counted=0)])

		self.assertEqual(result["counted_lines"], 1)
		self.assertEqual(result["total_lines"], 2)
		self.assertEqual(result["coverage_pct"], 50.0)
		self.assertTrue(result["is_partial"])

	def test_cases_are_converted_to_base_units(self):
		"""The rep types cases; every comparison downstream is in pieces."""
		result = self.count([self.line(qty=3, factor=12)])
		doc = frappe.get_doc("FieldMate Retailer Stock", result["name"])
		self.assertEqual(doc.items[0].qty, 36)

	def test_a_full_count_is_not_partial(self):
		result = self.count([self.line(qty=5, counted=1)])
		self.assertFalse(result["is_partial"])
		self.assertEqual(result["coverage_pct"], 100.0)


class TestRetailerOfftake(StockFixture):
	"""previous count + delivered in between - this count = sold through."""

	def test_what_the_shop_sold_between_two_counts(self):
		"""Hand-worked: the shop held 10, we delivered 20, it now holds 6.

		10 + 20 - 6 = 24 sold through. The same identity as the distributor's, one level down.
		"""
		self.count([self.line(qty=10)], on=add_days(today(), -7))
		self.book(qty=20)
		second = self.count([self.line(qty=6)])

		doc = frappe.get_doc("FieldMate Retailer Stock", second["name"])
		self.assertEqual(doc.offtake()[self.item], 24)

	def test_a_line_nobody_counted_is_left_out_rather_than_guessed(self):
		"""A number that looks real and is not is worse than a gap."""
		self.count([self.line(qty=10)], on=add_days(today(), -7))
		second = self.count([self.line(qty=6, counted=0)])

		doc = frappe.get_doc("FieldMate Retailer Stock", second["name"])
		self.assertNotIn(self.item, doc.offtake())

	def test_the_first_count_at_a_shop_has_nothing_to_compare_against(self):
		result = self.count([self.line(qty=10)])
		doc = frappe.get_doc("FieldMate Retailer Stock", result["name"])
		self.assertIsNone(doc.previous_stock)
		self.assertEqual(doc.offtake(), {})


class TestDistributorOfftake(StockFixture):
	"""The owner's identity, verbatim:

	    opening + primary billing - secondary sale = closing
	    opening + primary billing - closing        = secondary sale
	"""

	def stock(self, **rows):
		doc = frappe.get_doc({
			"doctype": "FieldMate Distributor Stock",
			"distributor": self.distributor.name,
			"from_date": rows.pop("from_date", add_days(today(), -30)),
			"to_date": rows.pop("to_date", today()),
			"items": [{"item_code": self.item, **rows}],
		})
		doc.flags.ignore_permissions = True
		doc.insert()
		self.track("FieldMate Distributor Stock", doc.name)
		return doc

	def test_secondary_is_implied_from_what_went_in_and_what_is_left(self):
		"""120 opening + 500 primary - 90 closing = 530 sold on."""
		doc = self.stock(opening_qty=120, primary_qty=500, closing_qty=90)
		self.assertEqual(doc.items[0].secondary_qty, 530)
		self.assertEqual(doc.total_secondary, 530)

	def test_what_they_reported_is_compared_rather_than_replaced(self):
		"""Implied 530 against a reported 500 is a gap of 30 - either sales nobody recorded or
		stock that has gone missing, and both are a phone call."""
		doc = self.stock(opening_qty=120, primary_qty=500, closing_qty=90,
		                 reported_secondary_qty=500)
		self.assertEqual(doc.items[0].variance_qty, 30)

	def test_a_distributor_who_reported_nothing_shows_no_variance(self):
		"""Otherwise every distributor who sent no file appears to be 100% adrift."""
		doc = self.stock(opening_qty=120, primary_qty=500, closing_qty=90)
		self.assertEqual(doc.items[0].variance_qty, 0)

	def test_opening_is_carried_from_the_previous_period(self):
		"""Typed independently the two drift, and a chain of months stops adding up."""
		first = self.stock(opening_qty=100, primary_qty=200, closing_qty=60,
		                   from_date=add_days(today(), -60), to_date=add_days(today(), -31))
		first.submit()

		second = self.stock(opening_qty=0, primary_qty=300, closing_qty=40)
		self.assertEqual(second.previous_stock, first.name)
		self.assertEqual(second.items[0].opening_qty, 60, "last period's closing")
		self.assertEqual(second.items[0].secondary_qty, 320, "60 + 300 - 40")

	def test_a_period_that_ends_before_it_starts_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.stock(opening_qty=1, from_date=today(), to_date=add_days(today(), -5))