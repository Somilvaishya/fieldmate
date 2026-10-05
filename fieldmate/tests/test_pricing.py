"""Which list a shop is quoted from, and the price nobody may exceed.

Two rules with several callers each, so they are tested against the one module that owns them
rather than through whichever caller happens to reach them.
"""

import frappe

from fieldmate.services import catalogue as catalogue_service
from fieldmate.services import channel as channel_service
from fieldmate.services import order as order_service
from fieldmate.services import pricing
from fieldmate.tests.test_catalogue import CatalogueFixture


class PricingFixture(CatalogueFixture):
	def setUp(self):
		super().setUp()
		# Only FieldMate's own default is blanked here, so that the tests about the earlier steps
		# of the chain are not answered by it. It is safe to blank because nothing in ERPNext
		# writes to it.
		#
		# **Selling Settings is deliberately left alone.** Blanking it is what broke this site
		# once already, and the mechanism is worth stating because it is not obvious: ERPNext's
		# `Price List.on_update` promotes a newly inserted selling price list to the site default
		# whenever that default is empty, and it does so by *saving* Selling Settings, which
		# pushes the name into `frappe.defaults` as well. `frappe.new_doc("Sales Invoice")` then
		# prefills `selling_price_list` from there. So: blank the setting, let any test insert a
		# throwaway price list, let the fixture delete it again, and every Sales Invoice on the
		# site afterwards fails mandatory validation on a name that no longer exists - which is
		# how this was found, as eight unrelated claim-settlement failures.
		#
		# The one test that genuinely needs the whole chain empty blanks it for itself, inserts
		# nothing while it is blank, and restores it in a `finally`.
		self._fm_default = self._restorable(self.fresh_settings().get("default_price_list"))
		self.apply_settings(default_price_list=None)

	def tearDown(self):
		# `set_single_value` rather than `apply_settings`: a document save validates its links,
		# and an earlier version of this threw on a price list a previous test had deleted -
		# which skipped the rest of tearDown, including the base class's fixture cleanup.
		try:
			frappe.db.set_single_value(
				"FieldMate Settings", "default_price_list", self._fm_default)
		finally:
			# `settings.get()` reads through the cache, so the row alone is not enough.
			frappe.cache().delete_value("fieldmate_settings")
			super().tearDown()

	@staticmethod
	def _restorable(price_list):
		"""A name worth putting back: one that still exists. A test that set the default to a
		list of its own and had it torn down would otherwise hand the next test a dangling name
		to restore."""
		return price_list if price_list and frappe.db.exists("Price List", price_list) else None

	def outlet_with(self, **values):
		"""A shop whose price list and distributor this test controls."""
		doc = self.make_outlet(territory=self.delhi, approval_status="Approved", **values)
		return doc

	def ptr_on(self, distributor: str, price_list: str) -> str:
		"""Give a distributor the list its shops buy on."""
		frappe.db.set_value("Customer", distributor,
		                    {"fm_tier": "Distributor", "fm_buys_from": "Company",
		                     "fm_ptr_price_list": price_list},
		                    update_modified=False)
		frappe.clear_document_cache("Customer", distributor)
		return price_list


class TestWhichListAShopIsQuotedFrom(PricingFixture):
	def test_the_shops_own_list_answers(self):
		own = self.make_price_list()
		outlet = self.outlet_with(price_list=own)
		self.assertEqual(pricing.price_list_for(outlet, self.rep.name), own)

	def test_the_distributors_ptr_answers_for_an_ordinary_kirana(self):
		"""The step this release adds. Before it, a shop with no list of its own fell straight
		through to the rep's, and a PTR list set on the distributor was never read by anything."""
		ptr = self.make_price_list()
		outlet = self.outlet_with()
		self.ptr_on(outlet.distributor, ptr)
		self.assertEqual(pricing.price_list_for(outlet, self.rep.name), ptr)

	def test_the_shops_own_list_beats_its_distributors_ptr(self):
		"""Specific beats general, and this is the defect the ordering used to have in
		`channel.resolve`: a modern-trade account that negotiated its own prices would have been
		quoted the tier price every other shop under that distributor pays."""
		own, ptr = self.make_price_list(), self.make_price_list()
		outlet = self.outlet_with(price_list=own)
		self.ptr_on(outlet.distributor, ptr)
		self.assertEqual(pricing.price_list_for(outlet, self.rep.name), own)

	def test_the_reps_own_list_answers_when_neither_party_does(self):
		outlet = self.outlet_with()
		self.assertEqual(pricing.price_list_for(outlet, self.rep.name), self.price_list)

	def test_the_company_default_answers_when_nobody_nearer_does(self):
		ours = self.make_price_list()
		self.apply_settings(default_price_list=ours)
		outlet = self.outlet_with()
		self.assertEqual(pricing.price_list_for(outlet, None), ours)

	def test_selling_settings_is_the_last_word(self):
		"""Without this, an order on a site nobody had configured failed with "no price on
		None" - a message that names the symptom and hides the cause.

		Read rather than set. What this site's selling price list happens to be does not matter;
		that the chain ends there does. Setting it would mean blanking it first, and blanking it
		is what lets the next inserted price list promote itself to the site default - see the
		fixture.
		"""
		theirs = frappe.db.get_single_value("Selling Settings", "selling_price_list")
		if not theirs:
			self.skipTest("this site has no selling price list configured")
		outlet = self.outlet_with()
		self.assertEqual(pricing.price_list_for(outlet, None), theirs)

	def test_nothing_set_anywhere_answers_none_rather_than_guessing(self):
		"""Never `frappe.defaults`, which would answer with whatever the last Desk session
		touched and be silently wrong for every rep who has never opened Desk (ADR-020).

		The one test that empties the whole chain. The outlet is built **before** Selling
		Settings is blanked and nothing is inserted while it is, because a selling price list
		created in that window would promote itself to the site default and outlive this test.
		"""
		outlet = self.outlet_with()
		original = frappe.db.get_single_value("Selling Settings", "selling_price_list")
		frappe.db.set_single_value("Selling Settings", "selling_price_list", None)
		try:
			self.assertIsNone(pricing.price_list_for(outlet, None))
		finally:
			frappe.db.set_single_value("Selling Settings", "selling_price_list", original)

	def test_a_field_user_that_is_not_a_name_is_refused_loudly(self):
		"""Passing the arguments the other way round used to resolve to a price list silently."""
		outlet = self.outlet_with()
		with self.assertRaises(TypeError):
			pricing.price_list_for(outlet, {"name": self.rep.name})


class TestTheCatalogueAndTheChannelAgree(PricingFixture):
	"""Two modules read the chain. The point of the module is that they cannot disagree."""

	def test_the_catalogue_resolves_through_the_same_chain(self):
		ptr = self.make_price_list()
		outlet = self.outlet_with()
		self.ptr_on(outlet.distributor, ptr)
		self.assertEqual(
			catalogue_service.resolve_price_list(outlet, self.rep.name),
			pricing.price_list_for(outlet, self.rep.name),
		)

	def test_channel_resolve_reports_the_same_list(self):
		ptr = self.make_price_list()
		outlet = self.outlet_with()
		self.ptr_on(outlet.distributor, ptr)
		self.apply_settings(enable_secondary_sales=1)
		self.assertEqual(channel_service.resolve(outlet.name)["price_list"], ptr)

	def test_channel_resolve_honours_the_shops_own_list_too(self):
		own, ptr = self.make_price_list(), self.make_price_list()
		outlet = self.outlet_with(price_list=own)
		self.ptr_on(outlet.distributor, ptr)
		self.apply_settings(enable_secondary_sales=1)
		self.assertEqual(channel_service.resolve(outlet.name)["price_list"], own)


class TestTheMrpRule(PricingFixture):
	"""`is_above_mrp` on its own. Both figures are per stock UOM; the wiring tests below prove
	that the caller passes the base-unit rate and not a rate multiplied up into cases."""

	def test_a_rate_over_the_printed_price_is_above_it(self):
		self.assertTrue(pricing.is_above_mrp(125, 120))

	def test_the_printed_price_itself_is_not_above_it(self):
		"""Selling at exactly the MRP is legal, and common for a single-piece pack."""
		self.assertFalse(pricing.is_above_mrp(120, 120))

	def test_under_it_is_the_ordinary_case(self):
		self.assertFalse(pricing.is_above_mrp(96, 120))

	def test_an_item_with_no_mrp_on_file_is_not_a_breach(self):
		"""ERPNext has no MRP of its own, so most sites hold none. Refusing every line would
		make the app unusable in order to say something it does not know."""
		self.assertFalse(pricing.is_above_mrp(125, None))

	def test_an_unpriced_item_is_not_a_breach_either(self):
		"""It has its own refusal, with its own message."""
		self.assertFalse(pricing.is_above_mrp(None, 120))


class MrpFixture(PricingFixture):
	"""A site that records an MRP on the Item.

	FieldMate does not create this field and must not: `compat.MRP_FIELDS` probes for it and
	answers None where there is none, because a catalogue that invented an MRP would print a
	number on a phone that nobody in the company ever agreed to. A test may build what the app
	may not, so this does - and then clears the request cache, because the probe is memoised for
	the life of the request and would otherwise go on reporting the site as having no MRP.
	"""

	FIELD = "fm_mrp"

	def setUp(self):
		super().setUp()
		existing = frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": self.FIELD})
		if not existing:
			doc = frappe.get_doc({
				"doctype": "Custom Field", "dt": "Item", "fieldname": self.FIELD,
				"label": "MRP", "fieldtype": "Currency", "insert_after": "item_name",
			}).insert(ignore_permissions=True)
			self.track("Custom Field", doc.name)
		self.forget_probes()

	def tearDown(self):
		super().tearDown()
		self.forget_probes()

	def forget_probes(self):
		"""Drop the memoised column probes in `compat`, which outlive a single test."""
		if hasattr(frappe.local, "request_cache"):
			frappe.local.request_cache.clear()

	def priced_item(self, rate, mrp):
		item = self.make_item()
		self.make_item_price(item, rate)
		if mrp is not None:
			frappe.db.set_value("Item", item, self.FIELD, mrp, update_modified=False)
			frappe.clear_document_cache("Item", item)
		return item


class TestACartPricedOverTheMrp(MrpFixture):
	def test_the_cart_names_the_item_rather_than_throwing(self):
		"""A rep with forty lines and one bad price should see the other thirty-nine price up."""
		bad = self.priced_item(rate=150, mrp=120)
		good = self.priced_item(rate=90, mrp=120)
		self.make_catalogue(items=[bad, good])

		cart = catalogue_service.cart_for(
			self.outlet.name,
			[{"item_code": bad, "qty": 1}, {"item_code": good, "qty": 1}],
			self.rep.name,
			price_list=self.price_list,
		)
		self.assertEqual(cart["above_mrp_items"], [bad])
		self.assertEqual(len(cart["lines"]), 2, "the good line still prices up")

	def test_an_item_at_exactly_its_mrp_is_not_named(self):
		at_mrp = self.priced_item(rate=120, mrp=120)
		self.make_catalogue(items=[at_mrp])
		cart = catalogue_service.cart_for(
			self.outlet.name, [{"item_code": at_mrp, "qty": 1}], self.rep.name,
			price_list=self.price_list,
		)
		self.assertEqual(cart["above_mrp_items"], [])


class TestAnOrderWillNotTakeAPriceOverTheMrp(MrpFixture):
	"""The cart names a breach; this is where it bites.

	Refused rather than warned about: a shopkeeper cannot resell at a profit above the printed
	price, and in India selling over it is an offence under the Legal Metrology Act. It is a
	price list somebody set wrong, not a decision for the rep at the counter.
	"""

	def book(self, item, qty=1):
		frappe.set_user(self.rep.user)
		try:
			return order_service.create(
				{"outlet": self.outlet.name, "lines": [{"item": item, "qty": qty}],
				 "client_uuid": self.uid("ORD")},
				self.rep.name,
			)
		finally:
			frappe.set_user("Administrator")

	def test_an_order_holding_one_is_refused_and_names_it(self):
		bad = self.priced_item(rate=150, mrp=120)
		self.make_catalogue(items=[bad])

		before = frappe.db.count("FieldMate Order")
		with self.assertRaises(frappe.ValidationError) as ctx:
			self.book(bad)

		message = frappe.utils.strip_html(str(ctx.exception))
		self.assertIn(bad, message, "the rep has to know which SKU")
		self.assertIn("above their MRP", message)
		self.assertEqual(frappe.db.count("FieldMate Order"), before,
		                 "a refused order must not be left half-written")

	def test_an_order_priced_under_the_mrp_books_as_usual(self):
		good = self.priced_item(rate=96, mrp=120)
		self.make_catalogue(items=[good])
		created = self.book(good)
		self.track("FieldMate Order", created["name"])
		self.assertTrue(created["name"])

	def test_the_catalogue_flags_it_before_a_cart_is_built(self):
		bad = self.priced_item(rate=150, mrp=120)
		self.make_catalogue(items=[bad])
		payload = catalogue_service.for_outlet(self.outlet.name, self.rep.name,
		                                       price_list=self.price_list)
		row = next(i for i in payload["items"] if i["item_code"] == bad)
		self.assertTrue(row["above_mrp"])
		self.assertEqual(row["mrp"], 120)

	def test_an_item_nobody_recorded_an_mrp_for_flags_nothing(self):
		"""The ordinary case even on a site that has the field: a Currency column is NOT NULL
		DEFAULT 0, and `compat` turns that zero into None rather than into a pack that costs
		nothing. Refusing here would make the app unusable to say something it does not know."""
		item = self.priced_item(rate=150, mrp=None)
		self.assertEqual(frappe.db.get_value("Item", item, self.FIELD), 0)
		self.make_catalogue(items=[item])
		cart = catalogue_service.cart_for(
			self.outlet.name, [{"item_code": item, "qty": 1}], self.rep.name,
			price_list=self.price_list,
		)
		self.assertEqual(cart["above_mrp_items"], [])
