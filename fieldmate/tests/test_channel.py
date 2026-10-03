import frappe

from fieldmate.services import channel as svc
from fieldmate.services import settings as settings_service
from fieldmate.tests.test_outlet import OutletFixture


class ChannelFixture(OutletFixture):
	SETTINGS = ("enable_secondary_sales", "enable_primary_sales", "default_company")

	def setUp(self):
		super().setUp()
		self.apply_settings(enable_secondary_sales=1, enable_primary_sales=1)

	def party(self, **values):
		"""A Customer with the channel fields filled in."""
		doc = frappe.get_doc({
			"doctype": "Customer",
			"customer_name": self.uid("CH-PARTY"),
			"customer_type": "Company",
			# Named rather than inherited, for the reason `leaf_customer_group` gives.
			"customer_group": self.leaf_customer_group(),
			**values,
		})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		return self.track("Customer", doc.name)

	def price_list(self, prefix="CH-PL"):
		doc = frappe.get_doc({
			"doctype": "Price List",
			"price_list_name": self.uid(prefix),
			"selling": 1,
			"currency": frappe.db.get_value("Company", {}, "default_currency") or "INR",
		}).insert(ignore_permissions=True)
		return self.track("Price List", doc.name)


class TestAShopIsASecondarySale(ChannelFixture):
	def test_a_shop_bills_its_distributor(self):
		dist = self.party(fm_tier="Distributor", fm_buys_from="Company")
		outlet = self.make_outlet(distributor=dist)

		answer = svc.resolve(outlet.name)
		self.assertEqual(answer["kind"], settings_service.SECONDARY)
		self.assertEqual(answer["party_type"], "Outlet")
		self.assertEqual(answer["bill_to"], dist, "the distributor bills the shop, not us")
		self.assertTrue(answer["allowed"])

	def test_a_shop_is_priced_at_its_distributors_ptr_list(self):
		ptr = self.price_list("CH-PTR")
		dist = self.party(fm_tier="Distributor", fm_buys_from="Company",
		                  fm_ptr_price_list=ptr)
		outlet = self.make_outlet(distributor=dist)
		self.assertEqual(svc.resolve(outlet.name)["price_list"], ptr)

	def test_a_shop_with_no_distributor_has_nobody_to_bill(self):
		outlet = self.make_outlet()
		frappe.db.set_value("FieldMate Outlet", outlet.name, "distributor", None)
		answer = svc.resolve(outlet.name)
		self.assertFalse(answer["allowed"])
		self.assertIn("no distributor", answer["reason"])


class TestADirectlyBilledShopIsOurs(ChannelFixture):
	"""ADR-024's escape hatch, and the bug it used to hide."""

	def test_a_directly_billed_shop_is_a_primary_sale(self):
		billed = self.party(fm_tier="Wholesaler", fm_buys_from="Company")
		outlet = self.make_outlet(customer=billed)

		answer = svc.resolve(outlet.name)
		self.assertEqual(answer["kind"], settings_service.PRIMARY)
		self.assertTrue(answer["direct_billed"])

	def test_the_bill_goes_to_the_shop_not_its_distributor(self):
		"""The defect this replaces: `billing_party` always answered with the distributor, so a
		directly-billed shop's Sales Order was raised against the wrong party."""
		dist = self.party(fm_tier="Distributor", fm_buys_from="Company")
		billed = self.party(fm_tier="Wholesaler", fm_buys_from="Company")
		outlet = self.make_outlet(distributor=dist, customer=billed)

		self.assertEqual(svc.resolve(outlet.name)["bill_to"], billed)


class TestACustomerIsAPrimarySale(ChannelFixture):
	def test_a_party_that_buys_from_us_is_billed_itself(self):
		ss = self.party(fm_tier="Super Stockist", fm_buys_from="Company")
		answer = svc.resolve(ss, party_type="Customer")
		self.assertEqual(answer["kind"], settings_service.PRIMARY)
		self.assertEqual(answer["bill_to"], ss)
		self.assertEqual(answer["tier"], "Super Stockist")

	def test_a_party_under_a_super_stockist_bills_the_super_stockist(self):
		ss = self.party(fm_tier="Super Stockist", fm_buys_from="Company")
		under = self.party(fm_tier="Distributor", fm_buys_from="Parent",
		                   fm_parent_customer=ss)

		answer = svc.resolve(under, party_type="Customer")
		self.assertTrue(answer["allowed"])
		self.assertEqual(answer["party"], under, "they are still the party being visited")
		self.assertEqual(answer["bill_to"], ss, "but our sale is to the super stockist")

	def test_buys_from_parent_with_no_parent_named_is_refused(self):
		orphan = self.party(fm_tier="Distributor", fm_buys_from="Parent")
		answer = svc.resolve(orphan, party_type="Customer")
		self.assertFalse(answer["allowed"])
		self.assertIn("no parent is named", answer["reason"])

	def test_a_customer_with_no_tier_is_not_a_channel_party(self):
		"""Most Customers on an ERPNext site have nothing to do with FieldMate."""
		plain = self.party()
		answer = svc.resolve(plain, party_type="Customer")
		self.assertFalse(answer["allowed"])
		self.assertIn("no channel tier", answer["reason"])

	def test_a_cfa_is_not_a_party_we_sell_to(self):
		depot = self.party(fm_tier="CFA", fm_buys_from="Company")
		answer = svc.resolve(depot, party_type="Customer")
		self.assertFalse(answer["allowed"])
		self.assertIn("our own stock", answer["reason"])


class TestTheSiteSwitch(ChannelFixture):
	"""Settings says which kinds this site makes at all; the party says which kind this is."""

	def test_primary_is_refused_when_the_site_does_not_make_primary_sales(self):
		self.apply_settings(enable_secondary_sales=1, enable_primary_sales=0)
		ss = self.party(fm_tier="Super Stockist", fm_buys_from="Company")

		answer = svc.resolve(ss, party_type="Customer")
		self.assertEqual(answer["kind"], settings_service.PRIMARY, "still what it is")
		self.assertFalse(answer["allowed"], "but not something this site may do")
		self.assertIn("switched off", answer["reason"])

	def test_secondary_is_refused_on_a_primary_only_site(self):
		self.apply_settings(enable_secondary_sales=0, enable_primary_sales=1)
		dist = self.party(fm_tier="Distributor", fm_buys_from="Company")
		outlet = self.make_outlet(distributor=dist)

		answer = svc.resolve(outlet.name)
		self.assertFalse(answer["allowed"])
		self.assertIn("switched off", answer["reason"])

	def test_both_on_lets_a_rep_do_either(self):
		dist = self.party(fm_tier="Distributor", fm_buys_from="Company")
		outlet = self.make_outlet(distributor=dist)
		self.assertTrue(svc.resolve(outlet.name)["allowed"])
		self.assertTrue(svc.resolve(dist, party_type="Customer")["allowed"])


class TestWorkingOutThePartyType(ChannelFixture):
	def test_an_outlet_name_resolves_without_being_told(self):
		dist = self.party(fm_tier="Distributor", fm_buys_from="Company")
		outlet = self.make_outlet(distributor=dist)
		self.assertEqual(svc.resolve(outlet.name)["party_type"], "Outlet")

	def test_a_customer_name_resolves_without_being_told(self):
		ss = self.party(fm_tier="Super Stockist", fm_buys_from="Company")
		self.assertEqual(svc.resolve(ss)["party_type"], "Customer")

	def test_a_name_that_is_neither_is_refused_rather_than_guessed(self):
		answer = svc.resolve("CH-NO-SUCH-PARTY")
		self.assertFalse(answer["allowed"])
		# No kind at all, rather than a default that a caller might act on.
		self.assertIsNone(answer["kind"])
