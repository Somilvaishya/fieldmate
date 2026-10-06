import frappe
from frappe.utils import add_days, today

from fieldmate.services import scheme_compile
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_masters import MasterFixture


class SchemeFixture(MasterFixture):
	"""Schemes, items and a territory tree, all built here rather than taken from the site.

	Nothing in this file leans on a Territory, an Item Group or a UOM that happens to exist on
	the bench, because a compiler test that passes only where somebody already set up a case
	size proves nothing about the sites it will actually run on.
	"""

	def setUp(self):
		super().setUp()
		self.item = self.make_item()
		self.price_item(self.item, 122)

	def price_item(self, item_code, rate):
		"""Every item a cart can hold needs a price on the selling list.

		`cart_for` resolves the server's own rate and deliberately ignores whatever the phone
		sent, so an unpriced item stops the whole cart rather than booking itself free. A fixture
		that skips this tests a shape no real site has.
		"""
		price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
		# Upsert, because a subclass routinely re-prices the same item at a rate its own
		# arithmetic depends on, and ERPNext allows one price per item per list.
		existing = frappe.db.get_value(
			"Item Price", {"item_code": item_code, "price_list": price_list}, "name"
		)
		if existing:
			frappe.db.set_value("Item Price", existing, "price_list_rate", rate)
			return frappe.get_doc("Item Price", existing)

		doc = frappe.get_doc({
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": price_list,
			"selling": 1,
			"price_list_rate": rate,
		}).insert(ignore_permissions=True)
		self.track("Item Price", doc.name)
		return doc

	def make_item(self, **kwargs):
		code = self.uid("ITEM")
		data = {
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": kwargs.pop("item_group", None) or self.leaf_item_group(),
			"stock_uom": kwargs.pop("stock_uom", None) or self.base_uom(),
			# Stocked, though nothing here moves stock. A non-stock item needs an expense account
			# on this bench, and a fixture that has to be told about somebody else app is a
			# fixture that breaks on the next site.
			"is_stock_item": 1,
		}
		data.update(kwargs)
		# india_compliance, where the site has it, refuses an Item with no HSN code. FieldMate has
		# no opinion about GST; the fixture only has to produce an item this site will accept.
		if frappe.get_meta("Item").has_field("gst_hsn_code") and not data.get("gst_hsn_code"):
			data["gst_hsn_code"] = frappe.db.get_value("GST HSN Code", {}, "name")
		for fieldname, value in self.site_required_fields("Item").items():
			data.setdefault(fieldname, value)

		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("Item", doc.name)
		return doc.name

	def site_required_fields(self, doctype: str) -> dict:
		"""Whatever this particular site has added to a DocType and made mandatory.

		A test bench is somebody working site as well as ours - it carries other apps custom
		fields, and one of them is a required Select on Item. Naming that field here would pass
		on this site and fail on the next one, so the question is asked generically: take what
		the site insists on and give it the first answer it will accept.
		"""
		values = {}
		for field in frappe.get_all(
			"Custom Field",
			filters={"dt": doctype, "reqd": 1, "fieldtype": "Select"},
			fields=["fieldname", "options"],
		):
			choices = [choice for choice in (field.options or "").split(chr(10)) if choice]
			if choices:
				values[field.fieldname] = choices[0]
		return values

	def leaf_item_group(self) -> str:
		return frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"

	def base_uom(self) -> str:
		return "Nos" if frappe.db.exists("UOM", "Nos") else frappe.db.get_value("UOM", {}, "name")

	def make_uom(self) -> str:
		doc = frappe.get_doc({"doctype": "UOM", "uom_name": self.uid("CASE")}).insert(
			ignore_permissions=True
		)
		self.track("UOM", doc.name)
		return doc.name

	def make_item_group(self, parent=None, is_group=0) -> str:
		doc = frappe.get_doc({
			"doctype": "Item Group",
			"item_group_name": self.uid("IG"),
			"parent_item_group": parent or "All Item Groups",
			"is_group": is_group,
		}).insert(ignore_permissions=True)
		self.track("Item Group", doc.name)
		return doc.name

	def make_brand(self) -> str:
		doc = frappe.get_doc({"doctype": "Brand", "brand": self.uid("BRND")}).insert(
			ignore_permissions=True
		)
		self.track("Brand", doc.name)
		return doc.name

	def make_territory_node(self, parent=None, is_group=0) -> str:
		"""A territory anywhere in the tree. `make_territory` only builds roots and leaves."""
		doc = frappe.get_doc({
			"doctype": "Territory",
			"territory_name": self.uid("TERR"),
			"parent_territory": parent or "All Territories",
			"is_group": is_group,
		}).insert(ignore_permissions=True)
		self.track("Territory", doc.name)
		return doc.name

	def make_scheme(self, **kwargs):
		data = {
			"doctype": "FieldMate Scheme",
			"scheme_name": kwargs.pop("scheme_name", None) or self.uid("SCH"),
			"scheme_type": "Volume Slab",
			"priority": 10,
			"is_active": 1,
			"basis": "Qty",
			"basis_uom": "Unit",
			"measured_over": "Item Set",
			"stacking": "Stackable",
			"valid_from": add_days(today(), -7),
			"on_exhaust": "Block",
			"items": kwargs.pop("items", None) or [{"item_code": self.item}],
			"slabs": kwargs.pop("slabs", None) or [{
				"slab_idx": 1, "from_value": 10, "is_open_ended": 1,
				"benefit_kind": "Percent Discount", "per": "Slab", "discount_pct": 5,
			}],
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Scheme", doc.name)
		doc.submit()
		return doc

	def compiled_names(self, outlet, **kwargs) -> list[str]:
		return [spec["scheme"] for spec in scheme_compile.for_outlet(outlet, None, **kwargs)["specs"]]

	def compiled_spec(self, outlet, scheme, **kwargs) -> dict:
		for spec in scheme_compile.for_outlet(outlet, None, **kwargs)["specs"]:
			if spec["scheme"] == scheme:
				return spec
		self.fail(f"{scheme} was not compiled for {outlet}")


class TestMoneyConversion(FieldMateTestCase):
	"""The one boundary where a rupee becomes an integer, and the only float in the money path."""

	def test_rupees_become_paise(self):
		self.assertEqual(scheme_compile.to_paise(12.34), 1234)
		self.assertEqual(scheme_compile.to_paise(0), 0)
		self.assertEqual(scheme_compile.to_paise(None), 0)

	def test_half_a_paise_rounds_up_not_to_even(self):
		"""Python's round() is banker's rounding and would send both of these down.

		A scheme is exactly the code where halves land on boundaries all day, and a gate that
		allows zero divergence across 60 carts finds every one of them (ADR-022).
		"""
		self.assertEqual(scheme_compile.to_paise(12.345), 1235)
		self.assertEqual(round(12.345 * 100), 1234)

		self.assertEqual(scheme_compile.to_paise(0.125), 13)
		self.assertEqual(round(0.125 * 100), 12)

	def test_paise_come_back_as_rupees_for_desk(self):
		self.assertEqual(scheme_compile.in_rupees(1235), 12.35)
		self.assertEqual(scheme_compile.in_rupees(0), 0.0)

	def test_percent_becomes_basis_points(self):
		self.assertEqual(scheme_compile.to_bp(5), 500)
		self.assertEqual(scheme_compile.to_bp(12.5), 1250)


class TestSchemeScope(SchemeFixture):
	def test_a_parent_territory_reaches_a_shop_three_levels_down(self):
		"""A scheme for North must reach a shop in North / Delhi / South Delhi.

		Comparing the two names for equality would exclude every shop not pinned to the exact
		node the planner picked, which is almost all of them (ADR-020).
		"""
		north = self.make_territory_node(is_group=1)
		delhi = self.make_territory_node(parent=north, is_group=1)
		south_delhi = self.make_territory_node(parent=delhi)

		shop = self.make_outlet(territory=south_delhi)
		scheme = self.make_scheme(scopes=[{"territory": north}])

		self.assertIn(scheme.name, self.compiled_names(shop.name))

	def test_a_sibling_territory_does_not_reach_the_shop(self):
		north = self.make_territory_node(is_group=1)
		east = self.make_territory_node(is_group=1)
		shop = self.make_outlet(territory=self.make_territory_node(parent=north))
		scheme = self.make_scheme(scopes=[{"territory": east}])

		self.assertNotIn(scheme.name, self.compiled_names(shop.name))

	def test_an_unscoped_scheme_reaches_every_shop(self):
		scheme = self.make_scheme()
		shop = self.make_outlet(territory=self.make_territory_node())

		self.assertTrue(scheme.applies_everywhere)
		self.assertIn(scheme.name, self.compiled_names(shop.name))

	def test_a_scope_row_pinned_by_a_session_default_still_reaches_everywhere(self):
		"""The ADR-020 trap, in the form a scheme meets it.

		A manager adds a scope row and leaves it empty. Frappe fills the blank Territory link
		from the session's own defaults on insert, so a scheme nobody scoped arrives looking
		scoped - pinned to the root nobody chose. Matched by name that reaches nothing at all;
		matched against the tree, the root is simply the ancestor of everything.
		"""
		root = "All Territories"
		frappe.defaults.set_user_default("territory", root)
		# The new-doc template is cached per request, so a scope row built earlier in this test
		# run would otherwise be handed back without the default ever being applied.
		frappe.local.new_doc_templates = {}
		try:
			scheme = self.make_scheme(scopes=[{}])
		finally:
			frappe.defaults.clear_user_default("territory")
			frappe.local.new_doc_templates = {}

		self.assertEqual(scheme.scopes[0].territory, root)
		self.assertTrue(scheme.applies_everywhere)

		shop = self.make_outlet(territory=self.make_territory_node())
		self.assertIn(scheme.name, self.compiled_names(shop.name))


class TestSchemeValidity(SchemeFixture):
	def test_an_expired_scheme_is_left_out(self):
		shop = self.make_outlet()
		scheme = self.make_scheme(
			valid_from=add_days(today(), -30), valid_to=add_days(today(), -1)
		)
		self.assertNotIn(scheme.name, self.compiled_names(shop.name))

	def test_a_scheme_that_has_not_started_is_left_out(self):
		shop = self.make_outlet()
		scheme = self.make_scheme(valid_from=add_days(today(), 1))
		self.assertNotIn(scheme.name, self.compiled_names(shop.name))

	def test_the_date_is_asked_for_not_read_off_a_clock(self):
		"""An order synced three days late must price against the schemes that were live then."""
		shop = self.make_outlet()
		scheme = self.make_scheme(
			valid_from=add_days(today(), -30), valid_to=add_days(today(), -2)
		)
		self.assertIn(scheme.name, self.compiled_names(shop.name, on_date=add_days(today(), -3)))

	def test_an_inactive_scheme_is_left_out(self):
		shop = self.make_outlet()
		scheme = self.make_scheme()
		frappe.db.set_value("FieldMate Scheme", scheme.name, "is_active", 0)
		self.assertNotIn(scheme.name, self.compiled_names(shop.name))


class TestItemExpansion(SchemeFixture):
	def test_an_item_group_expands_to_its_items_and_its_children(self):
		"""A scheme for Detergents is meant for the packs filed under it, not only on the node."""
		detergents = self.make_item_group(is_group=1)
		powders = self.make_item_group(parent=detergents)
		on_the_node = self.make_item(item_group=detergents)
		one_below = self.make_item(item_group=powders)

		shop = self.make_outlet()
		scheme = self.make_scheme(items=[{"item_group": detergents}])

		spec = self.compiled_spec(shop.name, scheme.name)
		self.assertEqual(spec["qualifying_items"], sorted([on_the_node, one_below]))

	def test_a_brand_expands_to_its_items(self):
		brand = self.make_brand()
		branded = self.make_item(brand=brand)
		self.make_item()

		shop = self.make_outlet()
		scheme = self.make_scheme(items=[{"brand": brand}])

		self.assertEqual(self.compiled_spec(shop.name, scheme.name)["qualifying_items"], [branded])

	def test_a_group_with_no_items_is_left_out_entirely(self):
		"""Measured over an empty set, no cart can qualify - and a near miss against it would
		nudge a rep towards an offer that does not exist."""
		shop = self.make_outlet()
		scheme = self.make_scheme(items=[{"item_group": self.make_item_group()}])
		self.assertNotIn(scheme.name, self.compiled_names(shop.name))


class TestCaseConversion(SchemeFixture):
	def setUp(self):
		super().setUp()
		self.case = self.make_uom()
		self.cased_item = self.make_item(uoms=[{"uom": self.case, "conversion_factor": 12}])

	def cased_scheme(self, **kwargs):
		data = {
			"basis_uom": "Case",
			"items": [{"item_code": self.cased_item, "case_uom": self.case}],
		}
		data.update(kwargs)
		return self.make_scheme(**data)

	def test_a_slab_typed_in_cases_compiles_to_base_units(self):
		"""The engine holds no Item master, so it may never divide by a case."""
		shop = self.make_outlet()
		scheme = self.cased_scheme(slabs=[
			{"slab_idx": 1, "from_value": 2, "to_value": 4, "benefit_kind": "Value Discount",
			 "per": "Slab", "discount_amount": 50},
			{"slab_idx": 2, "from_value": 5, "is_open_ended": 1,
			 "benefit_kind": "Value Discount", "per": "Slab", "discount_amount": 150},
		])

		spec = self.compiled_spec(shop.name, scheme.name)
		self.assertEqual([slab["from"] for slab in spec["slabs"]], [24, 60])
		self.assertEqual(spec["slabs"][0]["to"], 48)
		self.assertIsNone(spec["slabs"][1]["to"])
		self.assertEqual(spec["base_units_per_case"], 12)

	def test_an_amount_typed_per_case_is_restated_per_unit(self):
		"""`per: Unit` multiplies by base units, so a per-case rate has to arrive per unit."""
		shop = self.make_outlet()
		scheme = self.cased_scheme(slabs=[{
			"slab_idx": 1, "from_value": 2, "is_open_ended": 1,
			"benefit_kind": "Rate Off", "per": "Unit", "rate_off": 50,
		}])

		benefit = self.compiled_spec(shop.name, scheme.name)["slabs"][0]["benefits"][0]
		self.assertEqual(benefit["amount_paise"], 417)

	def test_a_scheme_counted_in_units_is_left_alone(self):
		shop = self.make_outlet()
		scheme = self.make_scheme(slabs=[{
			"slab_idx": 1, "from_value": 10, "is_open_ended": 1,
			"benefit_kind": "Rate Off", "per": "Unit", "rate_off": 50,
		}])

		spec = self.compiled_spec(shop.name, scheme.name)
		self.assertEqual(spec["slabs"][0]["from"], 10)
		self.assertEqual(spec["slabs"][0]["benefits"][0]["amount_paise"], 5000)

	def test_a_case_nobody_has_defined_counts_as_one_piece(self):
		"""Case is the field's default, so a manager who types piece counts lands here. Refusing
		to compile would delete most schemes on a site that has never entered a UOM conversion."""
		shop = self.make_outlet()
		scheme = self.make_scheme(basis_uom="Case", items=[{"item_code": self.item}])
		self.assertEqual(self.compiled_spec(shop.name, scheme.name)["slabs"][0]["from"], 10)


class TestCompiledSpec(SchemeFixture):
	def test_a_percent_arrives_as_basis_points_and_a_rupee_as_paise(self):
		shop = self.make_outlet()
		scheme = self.make_scheme(slabs=[
			{"slab_idx": 1, "from_value": 10, "to_value": 19, "benefit_kind": "Percent Discount",
			 "per": "Slab", "discount_pct": 12.5},
			{"slab_idx": 2, "from_value": 20, "is_open_ended": 1,
			 "benefit_kind": "Value Discount", "per": "Slab", "discount_amount": 125.5},
		])

		spec = self.compiled_spec(shop.name, scheme.name)
		self.assertEqual(spec["slabs"][0]["benefits"][0]["pct_bp"], 1250)
		self.assertEqual(spec["slabs"][1]["benefits"][0]["amount_paise"], 12550)

	def test_a_budget_nobody_set_is_uncapped(self):
		"""A Currency column is NOT NULL DEFAULT 0, so the alternative reading exhausts every
		scheme on the day it is written."""
		shop = self.make_outlet()
		scheme = self.make_scheme()
		self.assertIsNone(self.compiled_spec(shop.name, scheme.name)["budget_paise"])

	def test_a_budget_is_carried_in_paise_with_what_it_has_spent(self):
		shop = self.make_outlet()
		scheme = self.make_scheme(budget_amount=50000, consumed_amount=12345.60,
		                          on_exhaust="Warn")

		spec = self.compiled_spec(shop.name, scheme.name)
		self.assertEqual(spec["budget_paise"], 5000000)
		self.assertEqual(spec["consumed_paise"], 1234560)
		self.assertEqual(spec["on_exhaust"], "Warn")

	def test_rows_sharing_a_slab_number_are_one_tier_granting_both(self):
		shop = self.make_outlet()
		scheme = self.make_scheme(slabs=[
			{"slab_idx": 1, "from_value": 10, "is_open_ended": 1,
			 "benefit_kind": "Percent Discount", "per": "Slab", "discount_pct": 5},
			{"slab_idx": 1, "from_value": 10, "is_open_ended": 1,
			 "benefit_kind": "Free Goods", "per": "Slab", "free_item": self.item, "free_qty": 1},
		])

		slabs = self.compiled_spec(shop.name, scheme.name)["slabs"]
		self.assertEqual(len(slabs), 1)
		self.assertEqual([b["kind"] for b in slabs[0]["benefits"]],
		                 ["Percent Discount", "Free Goods"])

	def test_specs_come_back_in_the_order_the_engine_runs_them(self):
		shop = self.make_outlet()
		second = self.make_scheme(priority=20)
		first = self.make_scheme(priority=5)

		names = self.compiled_names(shop.name)
		self.assertLess(names.index(first.name), names.index(second.name))


class TestMalformedSpec(SchemeFixture):
	def test_slabs_that_collapse_onto_each_other_drop_the_scheme_not_the_rest(self):
		"""Two bands a manager wrote apart can land on the same base unit once a case size is
		applied. The DocType never saw that, and a spec that reaches a phone overlapping cannot
		be fixed from here - so it is asserted again after conversion, and only that offer is
		lost."""
		case = self.make_uom()
		item = self.make_item(uoms=[{"uom": case, "conversion_factor": 10}])
		shop = self.make_outlet()

		broken = self.make_scheme(
			basis_uom="Case",
			items=[{"item_code": item, "case_uom": case}],
			slabs=[
				{"slab_idx": 1, "from_value": 1, "to_value": 1.55,
				 "benefit_kind": "Value Discount", "per": "Slab", "discount_amount": 50},
				{"slab_idx": 2, "from_value": 1.6, "is_open_ended": 1,
				 "benefit_kind": "Value Discount", "per": "Slab", "discount_amount": 90},
			],
		)
		healthy = self.make_scheme()

		names = self.compiled_names(shop.name)
		self.assertNotIn(broken.name, names)
		self.assertIn(healthy.name, names)


class TestEvaluateFor(SchemeFixture):
	def test_one_path_from_a_cart_to_a_priced_result(self):
		"""The order service and the scheme API both come through here. Two paths to the same
		answer are two places for that answer to differ."""
		shop = self.make_outlet()
		scheme = self.make_scheme(slabs=[{
			"slab_idx": 1, "from_value": 10, "is_open_ended": 1,
			"benefit_kind": "Percent Discount", "per": "Slab", "discount_pct": 5,
		}])

		result = scheme_compile.evaluate_for(
			shop.name, None, [{"item": self.item, "qty": 12, "rate_paise": 12200}]
		)

		self.assertEqual(result["cart_gross_paise"], 146400)
		self.assertEqual(result["discount_paise"], 7320)
		self.assertEqual(result["net_paise"], 139080)
		self.assertEqual([entry["scheme"] for entry in result["applied"]], [scheme.name])
		self.assertEqual(result["unpriced_items"], [])

	def test_a_line_nothing_prices_is_named_rather_than_silently_free(self):
		shop = self.make_outlet()
		self.make_scheme()
		# Deliberately never priced. The fixture prices `self.item`, because almost every other
		# test needs a cart that totals; this one needs the opposite.
		unpriced = self.make_item()

		result = scheme_compile.evaluate_for(shop.name, None, [{"item": unpriced, "qty": 12}])

		self.assertEqual(result["cart_gross_paise"], 0)
		self.assertEqual(result["unpriced_items"], [unpriced])


class TestWhichKindOfSaleASchemeIsFor(SchemeFixture):
	"""Phase 1, step 8. A scheme written for a shop must not fire on a distributor's own
	purchase: a retailer offer landing on a primary order is trade spend nobody budgeted, and it
	would land silently - the engine would simply find a scheme scoped to everywhere.

	This is why step 5c compiled no schemes at all for a primary order. `applies_to` is what
	makes it safe to compile them."""

	def party(self):
		"""A Customer we sell to, priced off the same list the cart uses."""
		name = self.make_distributor()
		frappe.db.set_value("Customer", name, {
			"fm_tier": "Super Stockist", "fm_buys_from": "Company",
			"default_price_list": frappe.db.get_value(
				"Price List", {"selling": 1, "enabled": 1}, "name"),
		}, update_modified=False)
		frappe.clear_document_cache("Customer", name)
		return name

	def names_for_party(self, party, kind="Primary") -> list[str]:
		return [spec["scheme"] for spec in scheme_compile.for_outlet(
			party, None, party_type="Customer", kind=kind)["specs"]]

	def test_a_scheme_says_nothing_and_is_a_retailer_scheme(self):
		"""Every scheme written before this field existed, and the one a manager creates without
		thinking about it. The default is the safe direction."""
		scheme = self.make_scheme()
		self.assertEqual(scheme.applies_to, "Secondary")
		self.assertIn(scheme.name, self.compiled_names(self.make_outlet().name))

	def test_a_retailer_scheme_does_not_reach_a_primary_order(self):
		scheme = self.make_scheme()
		self.assertNotIn(scheme.name, self.names_for_party(self.party()))

	def test_a_primary_scheme_does_not_reach_a_shop(self):
		scheme = self.make_scheme(applies_to="Primary")
		self.assertNotIn(scheme.name, self.compiled_names(self.make_outlet().name))

	def test_a_primary_scheme_reaches_a_party_we_bill(self):
		scheme = self.make_scheme(applies_to="Primary")
		self.assertIn(scheme.name, self.names_for_party(self.party()))

	def test_both_reaches_either(self):
		scheme = self.make_scheme(applies_to="Both")
		self.assertIn(scheme.name, self.compiled_names(self.make_outlet().name))
		self.assertIn(scheme.name, self.names_for_party(self.party()))

	def test_a_primary_scheme_can_be_scoped_to_one_party(self):
		"""On a primary order the scope row's `distributor` means the party itself, not the shops
		under it - and the two cannot be confused, because `applies_to` has already decided which
		kind of scheme is being asked about."""
		mine, theirs = self.party(), self.party()
		scheme = self.make_scheme(applies_to="Primary", scopes=[{"distributor": mine}])

		self.assertIn(scheme.name, self.names_for_party(mine))
		self.assertNotIn(scheme.name, self.names_for_party(theirs))

	def test_a_channel_scoped_scheme_never_reaches_a_party(self):
		"""A channel is a kind of shop. A party we bill is not one, so a scheme that names a
		channel is a shop scheme whatever else it says."""
		channel = frappe.get_doc({
			"doctype": "FieldMate Outlet Channel", "channel_name": self.uid("CH"),
		}).insert(ignore_permissions=True)
		self.track("FieldMate Outlet Channel", channel.name)

		scheme = self.make_scheme(applies_to="Both", scopes=[{"channel": channel.name}])
		self.assertNotIn(scheme.name, self.names_for_party(self.party()))

	def test_a_directly_billed_shop_is_a_primary_sale_not_an_outlet_one(self):
		"""The case that makes the party type the wrong thing to read. This shop is a
		FieldMate Outlet and the sale is ours, so it gets primary schemes."""
		shop = self.make_outlet()
		retailer = self.make_scheme()
		primary = self.make_scheme(applies_to="Primary")

		names = [spec["scheme"] for spec in scheme_compile.for_outlet(
			shop.name, None, kind="Primary")["specs"]]
		self.assertIn(primary.name, names)
		self.assertNotIn(retailer.name, names)
