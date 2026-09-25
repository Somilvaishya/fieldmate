from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from fieldmate import compat
from fieldmate.services import catalogue as catalogue_service
from fieldmate.tests.test_masters import MasterFixture


class CatalogueFixture(MasterFixture):
	"""Everything the order screen reads, built from nothing.

	Nothing here leans on site data. A catalogue somebody left on testerp2 would otherwise decide
	whether a test about scoping passes, and the answer would differ between two machines.
	"""

	def setUp(self):
		super().setUp()
		self.company = frappe.db.get_value("Company", {}, "name")
		if not self.company:
			self.skipTest("no company on this site")

		self.north = self.make_territory()
		self.delhi = self.make_territory(parent=self.north)
		self.mumbai = self.make_territory(parent=self.north)

		self.price_list = self.make_price_list()
		self.rep = self.make_field_user(
			territory=self.delhi, company=self.company, default_price_list=self.price_list
		)
		self.outlet = self.make_outlet(territory=self.delhi, approval_status="Approved")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	# ---------------------------------------------------------------- fixtures

	def make_price_list(self) -> str:
		doc = frappe.get_doc({
			"doctype": "Price List",
			"price_list_name": self.uid("PL"),
			"selling": 1,
			"enabled": 1,
			"currency": frappe.db.get_value("Currency", {"enabled": 1}, "name") or "INR",
		}).insert(ignore_permissions=True)
		self.track("Price List", doc.name)
		return doc.name

	def make_item_price(self, item_code: str, rate) -> str:
		doc = frappe.get_doc({
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": self.price_list,
			"price_list_rate": rate,
		}).insert(ignore_permissions=True)
		self.track("Item Price", doc.name)
		return doc.name

	def priced_item(self, rate=100) -> str:
		item = self.make_item()
		self.make_item_price(item, rate)
		return item

	def make_channel(self) -> str:
		doc = frappe.get_doc({
			"doctype": "FieldMate Outlet Channel",
			"channel_name": self.uid("CHAN"),
		}).insert(ignore_permissions=True)
		self.track("FieldMate Outlet Channel", doc.name)
		return doc.name

	def make_catalogue(self, items=None, **kwargs):
		data = {
			"doctype": "FieldMate Product Catalogue",
			"catalogue_name": self.uid("CAT"),
			"items": [{"item_code": i} if isinstance(i, str) else i for i in (items or [])],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Product Catalogue", doc.name)
		return doc

	def make_must_sell(self, items=None, **kwargs):
		data = {
			"doctype": "FieldMate Must Sell List",
			"list_name": self.uid("MSL"),
			"items": [{"item_code": i} if isinstance(i, str) else i for i in (items or [])],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Must Sell List", doc.name)
		return doc

	def make_distributor_profile(self, customer: str) -> str:
		# Named after the Customer, so a shop's second order would collide on the primary key.
		if frappe.db.exists("FieldMate Distributor Profile", customer):
			return customer
		doc = frappe.get_doc({
			"doctype": "FieldMate Distributor Profile",
			"customer": customer,
			"territory": self.delhi,
		}).insert(ignore_permissions=True)
		self.track("FieldMate Distributor Profile", doc.name)
		return doc.name

	def make_order(self, outlet, lines, **kwargs):
		"""A submitted FieldMate Order, which is where the repeat-order prefill comes from.

		Nothing downstream of it exists: a retailer order is a secondary sale, terminal in our
		books, and creates no Sales Order and no GL entry (ADR-023).
		"""
		data = {
			"doctype": "FieldMate Order",
			"order_date": kwargs.pop("order_date", None) or today(),
			"outlet": outlet.name,
			"field_user": self.rep.name,
			"distributor": self.make_distributor_profile(outlet.distributor),
			"company": self.company,
			"price_list": self.price_list,
			"currency": frappe.db.get_value("Price List", self.price_list, "currency"),
			"payment_term": "Credit",
			"client_uuid": self.uid("ORD"),
			"items": lines,
		}
		data.update(kwargs)
		doc = frappe.get_doc(data)
		# Inserted in the rep's own session, not Administrator's. A Field Rep reads
		# FieldMate Order only `if_owner`, and `owner` is stamped from the session at insert -
		# assigning it beforehand does not survive. An order the rep cannot read back is a shape
		# the field never produces, and a prefill tested against it proves nothing.
		frappe.set_user(self.rep.user)
		try:
			doc.flags.ignore_permissions = True
			doc.insert()
			self.track("FieldMate Order", doc.name)
			doc.submit()
		finally:
			frappe.set_user("Administrator")
		return doc

	# ---------------------------------------------------------------- helpers

	def as_user(self, user, fn, *args, **kwargs):
		frappe.set_user(user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def catalogue_for(self, outlet=None, user=None):
		outlet = outlet or self.outlet
		return self.as_user(
			user or self.rep.user, catalogue_service.for_outlet, outlet.name, self.rep.name
		)

	def codes_in(self, payload) -> set:
		return {row["item_code"] for row in payload["items"]}

	def queries_for(self, fn, *args, **kwargs) -> int:
		"""How many statements one call actually runs.

		The point is never the absolute number - it moves with framework versions - but whether
		it grows with the length of the catalogue. That is the shape of an N+1, and on a market
		uplink it is the difference between a screen that opens and one a rep abandons.
		"""
		count = 0
		original = frappe.db.__class__.sql

		def counted(*args, **kwargs):
			nonlocal count
			count = count + 1
			return original(*args, **kwargs)

		frappe.db.__class__.sql = counted
		try:
			fn(*args, **kwargs)
		finally:
			frappe.db.__class__.sql = original
		return count


class TestCatalogueScope(CatalogueFixture):
	def test_a_catalogue_scoped_to_a_parent_reaches_a_shop_below_it(self):
		"""The shop is in North / Delhi and the range was written for North (ADR-020)."""
		item = self.priced_item()
		self.make_catalogue(items=[item], territory=self.north)
		self.assertIn(item, self.codes_in(self.catalogue_for()))

	def test_a_catalogue_scoped_to_another_branch_does_not_reach_it(self):
		item = self.priced_item()
		self.make_catalogue(items=[item], territory=self.mumbai)
		self.assertNotIn(item, self.codes_in(self.catalogue_for()))

	def test_a_catalogue_with_no_scope_reaches_everywhere(self):
		item = self.priced_item()
		self.make_catalogue(items=[item])
		self.assertIn(item, self.codes_in(self.catalogue_for()))

	def test_a_channel_scoped_catalogue_only_reaches_that_channel(self):
		wholesale, kirana = self.make_channel(), self.make_channel()
		theirs, mine = self.priced_item(), self.priced_item()
		self.make_catalogue(items=[theirs], channel=wholesale)
		self.make_catalogue(items=[mine], channel=kirana)

		shop = self.make_outlet(territory=self.delhi, channel=kirana, approval_status="Approved")
		codes = self.codes_in(self.catalogue_for(shop))
		self.assertIn(mine, codes)
		self.assertNotIn(theirs, codes)

	def test_an_expired_catalogue_is_not_offered(self):
		item = self.priced_item()
		self.make_catalogue(items=[item], valid_to=add_days(today(), -1))
		self.assertNotIn(item, self.codes_in(self.catalogue_for()))

	def test_an_inactive_catalogue_is_not_offered(self):
		item = self.priced_item()
		self.make_catalogue(items=[item], is_active=0)
		self.assertNotIn(item, self.codes_in(self.catalogue_for()))

	def test_the_narrower_catalogue_owns_the_line(self):
		"""A region that made a SKU a focus line meant it; the national range did not."""
		item = self.priced_item()
		self.make_catalogue(items=[{"item_code": item, "is_focus": 0}])
		regional = self.make_catalogue(
			items=[{"item_code": item, "is_focus": 1}], territory=self.delhi
		)

		row = next(r for r in self.catalogue_for()["items"] if r["item_code"] == item)
		self.assertTrue(row["is_focus"])
		self.assertEqual(row["catalogue"], regional.name)

	def test_a_rep_cannot_read_another_territory(self):
		"""Territory is the security boundary, so it is checked before anything is priced."""
		theirs = self.make_outlet(territory=self.mumbai, approval_status="Approved")
		self.make_catalogue(items=[self.priced_item()])
		with self.assertRaises(frappe.PermissionError):
			self.catalogue_for(theirs)

	def test_a_must_sell_item_is_flagged(self):
		item = self.priced_item()
		self.make_catalogue(items=[item])
		self.make_must_sell(items=[{"item_code": item, "min_qty": 6, "weightage": 1}])

		row = next(r for r in self.catalogue_for()["items"] if r["item_code"] == item)
		self.assertTrue(row["is_must_sell"])
		self.assertEqual(row["must_sell_min_qty"], 6)

	def test_an_item_outside_the_must_sell_list_is_not_flagged(self):
		item = self.priced_item()
		self.make_catalogue(items=[item])
		row = next(r for r in self.catalogue_for()["items"] if r["item_code"] == item)
		self.assertFalse(row["is_must_sell"])
		self.assertIsNone(row["must_sell_min_qty"])


class TestCataloguePricing(CatalogueFixture):
	def test_an_unpriced_item_comes_back_unpriceable_and_not_free(self):
		"""0.00 here lets a rep book a pallet for nothing, and nobody finds out for weeks."""
		unpriced = self.make_item()
		self.make_catalogue(items=[unpriced])

		row = next(r for r in self.catalogue_for()["items"] if r["item_code"] == unpriced)
		self.assertTrue(row["unpriceable"])
		self.assertIsNone(row["rate"])
		self.assertIsNone(row["order_uom_rate"])
		self.assertNotEqual(row["rate"], 0)

	def test_an_unpriced_item_is_still_listed_and_counted(self):
		"""Hiding it would leave the rep wondering where the SKU went. Naming it gets it fixed."""
		unpriced = self.make_item()
		self.make_catalogue(items=[self.priced_item(), unpriced])

		payload = self.catalogue_for()
		self.assertIn(unpriced, self.codes_in(payload))
		row = next(r for r in payload["items"] if r["item_code"] == unpriced)
		self.assertTrue(row["unpriceable"], "the SKU itself has to carry the flag")
		self.assertGreaterEqual(payload["unpriceable_count"], 1,
		                        "and the count has to include it")

	def test_a_rate_of_zero_is_a_real_rate(self):
		"""A sample or a trial pack is genuinely free, and that is not the same as unpriced."""
		item = self.make_item()
		self.make_item_price(item, 0)
		self.make_catalogue(items=[item])

		row = next(r for r in self.catalogue_for()["items"] if r["item_code"] == item)
		self.assertFalse(row["unpriceable"])
		self.assertEqual(row["rate"], 0.0)

	def test_a_priced_item_carries_its_units_and_currency(self):
		item = self.priced_item(rate=122.5)
		self.make_catalogue(items=[item])

		row = next(r for r in self.catalogue_for()["items"] if r["item_code"] == item)
		self.assertEqual(row["rate"], 122.5)
		self.assertEqual(row["conversion_factor"], 1.0)
		self.assertEqual(row["order_uom"], row["stock_uom"])
		self.assertEqual(row["order_uom_rate"], 122.5)
		self.assertTrue(row["currency"])

	def test_zero_min_and_max_read_as_no_limit(self):
		"""A Float column is NOT NULL DEFAULT 0, so zero is a field nobody filled in."""
		item = self.priced_item()
		self.make_catalogue(items=[{"item_code": item, "min_order_qty": 0, "max_order_qty": 0}])

		row = next(r for r in self.catalogue_for()["items"] if r["item_code"] == item)
		self.assertIsNone(row["min_order_qty"])
		self.assertIsNone(row["max_order_qty"])

	def test_a_real_minimum_survives(self):
		item = self.priced_item()
		self.make_catalogue(items=[{"item_code": item, "min_order_qty": 6, "max_order_qty": 60}])

		row = next(r for r in self.catalogue_for()["items"] if r["item_code"] == item)
		self.assertEqual(row["min_order_qty"], 6)
		self.assertEqual(row["max_order_qty"], 60)

	def test_a_catalogue_unit_the_item_cannot_convert_falls_back_to_the_base_unit(self):
		"""Booking "2 Case" against a per-piece rate bills a twelfth of what was sold."""
		item = self.priced_item(rate=100)
		other_uom = frappe.db.get_value(
			"UOM", {"name": ["!=", frappe.db.get_value("Item", item, "stock_uom")]}, "name"
		)
		self.make_catalogue(items=[{"item_code": item, "uom": other_uom}])

		row = next(r for r in self.catalogue_for()["items"] if r["item_code"] == item)
		self.assertTrue(row["order_uom_fallback"])
		self.assertEqual(row["order_uom"], row["stock_uom"])
		self.assertEqual(row["conversion_factor"], 1.0)
		self.assertEqual(row["order_uom_rate"], 100)


class TestCatalogueIsNotNPlusOne(CatalogueFixture):
	"""This screen asks for hundreds of SKUs on a 2G link. One round trip, or it is unusable."""

	def test_prices_are_fetched_in_one_bulk_call(self):
		items = [self.priced_item() for _ in range(6)]
		self.make_catalogue(items=items)

		with patch.object(catalogue_service.compat, "get_item_details",
		                  wraps=compat.get_item_details) as bulk:
			with patch.object(compat, "get_item_price") as per_item:
				payload = self.catalogue_for()

		self.assertEqual(bulk.call_count, 1, "one bulk call, never one per SKU")
		self.assertEqual(per_item.call_count, 0)
		# A superset, not an exact list: any catalogue scoped to everywhere legitimately adds
		# its own SKUs to this shop, and asserting equality made the test depend on the site
		# being empty of real masters.
		self.assertTrue(set(items).issubset(set(bulk.call_args.args[0])),
		                "every item in this catalogue has to be in the one call")
		self.assertTrue(set(items).issubset(self.codes_in(payload)))

	def test_the_query_count_does_not_grow_with_the_catalogue(self):
		small = self.make_outlet(territory=self.delhi, approval_status="Approved")
		large = self.make_outlet(territory=self.delhi, approval_status="Approved")
		self.make_catalogue(items=[self.priced_item() for _ in range(2)], outlet_class=None,
		                    catalogue_name=self.uid("SMALL"))
		big = [self.priced_item() for _ in range(12)]

		# Both shops see both catalogues, so the only difference between the two calls is
		# twelve more item rows to price.
		self.make_catalogue(items=big, catalogue_name=self.uid("BIG"))

		# Warm the document cache first; a cold read is a different measurement.
		self.catalogue_for(small)
		self.catalogue_for(large)

		baseline = self.queries_for(self.catalogue_for, small)
		with_more = self.queries_for(self.catalogue_for, large)

		self.assertLessEqual(
			with_more, baseline + 2,
			f"catalogue reads grew from {baseline} to {with_more} queries - that is an N+1",
		)

	def test_a_cart_refresh_prices_in_one_call_too(self):
		items = [self.priced_item() for _ in range(5)]
		self.make_catalogue(items=items)

		with patch.object(catalogue_service.compat, "get_item_details",
		                  wraps=compat.get_item_details) as bulk:
			payload = self.as_user(
				self.rep.user, catalogue_service.prices_for, self.outlet.name,
				[{"item_code": code, "qty": 6} for code in items], self.rep.name,
			)

		self.assertEqual(bulk.call_count, 1)
		self.assertEqual(len(payload["items"]), 5)


class TestCartRefresh(CatalogueFixture):
	def test_an_item_outside_this_shops_catalogue_is_refused(self):
		"""Otherwise the endpoint is a way to read the whole price book from a phone."""
		mine, theirs = self.priced_item(), self.priced_item()
		self.make_catalogue(items=[mine])

		payload = self.as_user(
			self.rep.user, catalogue_service.prices_for, self.outlet.name, [mine, theirs],
			self.rep.name,
		)
		self.assertIn(mine, payload["items"])
		self.assertEqual(payload["not_in_catalogue"], [theirs])

	def test_an_unpriced_line_is_named_rather_than_zeroed(self):
		unpriced = self.make_item()
		self.make_catalogue(items=[unpriced])

		payload = self.as_user(
			self.rep.user, catalogue_service.prices_for, self.outlet.name, [unpriced],
			self.rep.name,
		)
		self.assertIsNone(payload["items"][unpriced]["rate"])
		self.assertEqual(payload["unpriceable"], [unpriced])

	def test_an_unpriced_line_is_named_and_left_out_of_the_total(self):
		"""Named, not thrown, and never priced at zero.

		A rep with forty lines and one unpriced SKU has to see the other thirty-nine total up
		and be told which one is the problem; throwing kills the whole cart and leaves them
		nothing to sell. Committing is where it is refused - see
		`test_order.TestAnOrderIsASecondarySale` - because silently dropping a line from an
		order the rep believes they booked is worse than either.
		"""
		unpriced = self.make_item()
		priced = self.priced_item(rate=100)
		self.make_catalogue(items=[unpriced, priced])

		cart = self.as_user(
			self.rep.user, catalogue_service.cart_for, self.outlet.name,
			[{"item_code": unpriced, "qty": 2}, {"item_code": priced, "qty": 3}], self.rep.name
		)

		self.assertEqual(cart["unpriced_items"], [unpriced])
		self.assertEqual([line["item"] for line in cart["lines"]], [priced],
		                 "the unpriced line is left out rather than booked free")

	def test_a_cart_arrives_at_the_engine_in_integer_paise(self):
		item = self.priced_item(rate=122.5)
		self.make_catalogue(items=[item])

		cart = self.as_user(self.rep.user, catalogue_service.cart_for, self.outlet.name,
		                    [{"item_code": item, "qty": 24}], self.rep.name)
		self.assertEqual(cart["lines"], [{"item": item, "qty": 24, "rate_paise": 12250}])
		self.assertIsInstance(cart["lines"][0]["rate_paise"], int)


class TestRepeatOrderPrefill(CatalogueFixture):
	def test_a_shop_that_has_never_ordered_says_so(self):
		payload = self.as_user(
			self.rep.user, catalogue_service.last_order_for, self.outlet.name, self.rep.name
		)
		self.assertFalse(payload["has_order_history"])
		self.assertIsNone(payload["order"])
		self.assertEqual(payload["items"], {})

	def test_an_item_ordered_at_zero_is_not_an_item_never_ordered(self):
		"""Opposite instructions to a rep: one is a line to pitch, the other one to stop."""
		skipped, bought, never = self.priced_item(), self.priced_item(), self.priced_item()
		self.make_catalogue(items=[skipped, bought, never])
		uom = frappe.db.get_value("Item", bought, "stock_uom")

		self.make_order(self.outlet, [
			{"item_code": skipped, "qty_display": 0, "display_uom": uom, "conversion_factor": 1},
			{"item_code": bought, "qty_display": 5, "display_uom": uom, "conversion_factor": 1},
		])

		payload = self.as_user(
			self.rep.user, catalogue_service.last_order_for, self.outlet.name, self.rep.name
		)

		self.assertTrue(payload["has_order_history"])
		self.assertTrue(payload["items"][skipped]["has_order_history"])
		self.assertEqual(payload["items"][skipped]["last_ordered_qty"], 0)
		self.assertEqual(payload["items"][bought]["last_ordered_qty"], 5)
		self.assertNotIn(never, payload["items"])

	def test_the_most_recent_order_is_the_one_that_prefills(self):
		item = self.priced_item()
		self.make_catalogue(items=[item])
		uom = frappe.db.get_value("Item", item, "stock_uom")

		self.make_order(self.outlet, [
			{"item_code": item, "qty_display": 3, "display_uom": uom, "conversion_factor": 1},
		], order_date=add_days(today(), -30))
		latest = self.make_order(self.outlet, [
			{"item_code": item, "qty_display": 9, "display_uom": uom, "conversion_factor": 1},
		])

		payload = self.as_user(
			self.rep.user, catalogue_service.last_order_for, self.outlet.name, self.rep.name
		)
		self.assertEqual(payload["order"], latest.name)
		self.assertEqual(payload["items"][item]["last_ordered_qty"], 9)
		self.assertEqual(payload["items"][item]["last_ordered_on"], str(latest.order_date))

	def test_free_goods_are_not_prefilled(self):
		"""They were granted by a scheme. Prefilling them re-orders the gift, and pays for it."""
		bought, gift = self.priced_item(), self.priced_item()
		self.make_catalogue(items=[bought, gift])
		uom = frappe.db.get_value("Item", bought, "stock_uom")

		self.make_order(self.outlet, [
			{"item_code": bought, "qty_display": 10, "display_uom": uom, "conversion_factor": 1},
			{"item_code": gift, "qty_display": 1, "display_uom": uom, "conversion_factor": 1,
			 "is_free_item": 1},
		])

		payload = self.as_user(
			self.rep.user, catalogue_service.last_order_for, self.outlet.name, self.rep.name
		)
		self.assertIn(bought, payload["items"])
		self.assertNotIn(gift, payload["items"])

	def test_the_same_sku_twice_is_summed(self):
		"""A rep can add the same soap on two lines; the prefill has to be one number."""
		item = self.priced_item()
		self.make_catalogue(items=[item])
		uom = frappe.db.get_value("Item", item, "stock_uom")

		self.make_order(self.outlet, [
			{"item_code": item, "qty_display": 4, "display_uom": uom, "conversion_factor": 1},
			{"item_code": item, "qty_display": 6, "display_uom": uom, "conversion_factor": 1},
		])

		payload = self.as_user(
			self.rep.user, catalogue_service.last_order_for, self.outlet.name, self.rep.name
		)
		self.assertEqual(payload["items"][item]["last_ordered_qty"], 10)

	def test_a_cancelled_order_does_not_prefill(self):
		item = self.priced_item()
		self.make_catalogue(items=[item])
		uom = frappe.db.get_value("Item", item, "stock_uom")

		order = self.make_order(self.outlet, [
			{"item_code": item, "qty_display": 7, "display_uom": uom, "conversion_factor": 1},
		])
		order.flags.ignore_permissions = True
		order.cancel()

		payload = self.as_user(
			self.rep.user, catalogue_service.last_order_for, self.outlet.name, self.rep.name
		)
		self.assertFalse(payload["has_order_history"])
