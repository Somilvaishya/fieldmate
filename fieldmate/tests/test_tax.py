"""Tax arithmetic, and the rate resolution underneath it.

The arithmetic is tested as arithmetic. It has to produce the same paise on a phone with no
signal as it does here, so every rule it follows - the rounding, the apportionment, the tie-break
- is pinned by a case rather than left to be inferred from the code.
"""

import frappe

from fieldmate import compat
from fieldmate.services import order as order_service
from fieldmate.services import tax
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_catalogue import CatalogueFixture


def line(item, qty, rate_paise, gross_paise=None):
	return {"item": item, "qty": qty, "rate_paise": rate_paise,
	        "gross_paise": qty * rate_paise if gross_paise is None else gross_paise}


# These are arithmetic and build no fixtures. `FieldMateTestCase` rather than the catalogue's,
# because a site full of items and prices is two and a half seconds per case to prove that
# eighteen per cent of a hundred rupees is eighteen rupees.
class TestRounding(FieldMateTestCase):
	"""`on_paise` is the whole money path for tax. Half-up, per line, once."""

	def test_eighteen_per_cent_of_a_hundred_rupees(self):
		self.assertEqual(tax.on_paise(10_000, 1800), 1_800)

	def test_five_per_cent_of_a_hundred_rupees(self):
		self.assertEqual(tax.on_paise(10_000, 500), 500)

	def test_a_half_paisa_rounds_up_not_to_even(self):
		"""Python's `round()` sends 0.5 to the nearest even number, so 2.5 would go down and 3.5
		up. Nobody expects that from a bill, so this rounds half away from zero."""
		# 5 paise at 5% is 0.25 of a paisa -> 0. 10 paise at 5% is 0.5 -> 1.
		self.assertEqual(tax.on_paise(5, 500), 0)
		self.assertEqual(tax.on_paise(10, 500), 1)
		# 30 paise at 5% is 1.5 -> 2, which bankers' rounding would have sent to 2 as well; 50
		# paise at 5% is 2.5, which it would have sent to 2 and this sends to 3.
		self.assertEqual(tax.on_paise(50, 500), 3)

	def test_no_rate_is_no_tax(self):
		self.assertEqual(tax.on_paise(10_000, 0), 0)

	def test_nothing_taxable_is_no_tax(self):
		self.assertEqual(tax.on_paise(0, 1800), 0)


class TestACartWithNoDiscount(FieldMateTestCase):
	def test_each_line_carries_its_own_tax(self):
		got = tax.for_lines(
			[line("A", 2, 10_000), line("B", 1, 5_000)],
			{"A": 1800, "B": 500},
		)
		self.assertEqual([r["tax_paise"] for r in got["lines"]], [3_600, 250])
		self.assertEqual(got["tax_paise"], 3_850)

	def test_an_item_with_no_rate_is_not_taxed_and_not_an_error(self):
		"""Most ERPNext sites have no tax templates at all."""
		got = tax.for_lines([line("A", 1, 10_000)], {})
		self.assertEqual(got["tax_paise"], 0)
		self.assertEqual(got["lines"][0]["tax_bps"], 0)

	def test_the_total_is_the_sum_of_the_lines_not_a_second_calculation(self):
		"""An invoice carries tax per line and totals them. A total taxed in one go differs by a
		paisa or two, which is exactly what turns into "the app said something else"."""
		rows = [line(c, 1, 3_333) for c in "ABC"]
		got = tax.for_lines(rows, {c: 1800 for c in "ABC"})
		self.assertEqual(got["tax_paise"], sum(r["tax_paise"] for r in got["lines"]))


class TestTheCartDiscountIsApportioned(FieldMateTestCase):
	"""The engine keeps one cart-level discount rather than marking down each line, so taxing a
	line's gross would charge tax on money the shop is not paying."""

	def test_the_taxable_amounts_sum_to_the_net(self):
		rows = [line("A", 1, 10_000), line("B", 1, 5_000)]
		got = tax.for_lines(rows, {"A": 1800, "B": 1800}, discount_paise=3_000)
		self.assertEqual(sum(r["taxable_paise"] for r in got["lines"]), 15_000 - 3_000)

	def test_the_split_is_by_gross(self):
		rows = [line("A", 1, 10_000), line("B", 1, 5_000)]
		got = tax.for_lines(rows, {"A": 1800, "B": 1800}, discount_paise=3_000)
		self.assertEqual([r["taxable_paise"] for r in got["lines"]], [8_000, 4_000])

	def test_which_line_the_discount_lands_on_changes_the_tax(self):
		"""Why apportioning matters at all. One line at 5% and one at 18%: taxing the gross
		overstates the bill, and dropping the whole discount on either line is simply wrong."""
		rows = [line("CHEAP", 1, 10_000), line("DEAR", 1, 10_000)]
		apportioned = tax.for_lines(rows, {"CHEAP": 500, "DEAR": 1800}, discount_paise=4_000)
		on_gross = tax.for_lines(rows, {"CHEAP": 500, "DEAR": 1800})

		# Half the discount to each: 8000 at 5% plus 8000 at 18% = 400 + 1440.
		self.assertEqual(apportioned["tax_paise"], 1_840)
		self.assertEqual(on_gross["tax_paise"], 2_300)
		self.assertLess(apportioned["tax_paise"], on_gross["tax_paise"])

	def test_the_paise_left_over_by_flooring_go_to_the_largest_line(self):
		"""Three equal lines and a discount that does not divide by three."""
		rows = [line(c, 1, 10_000) for c in ("A", "B", "C")]
		got = tax.for_lines(rows, {c: 1800 for c in "ABC"}, discount_paise=1_000)
		shares = [10_000 - r["taxable_paise"] for r in got["lines"]]
		self.assertEqual(sum(shares), 1_000, "the shares account for every paisa")
		# 333 each, and the odd paisa to the line the tie-break picks - C, by item code.
		self.assertEqual(shares, [333, 333, 334])

	def test_the_order_of_the_lines_does_not_change_the_answer(self):
		"""Two carts holding the same lines must not disagree, or the phone and the server will
		disagree the moment one of them sorts."""
		rows = [line(c, 1, 10_000) for c in ("A", "B", "C")]
		forwards = tax.for_lines(rows, {c: 1800 for c in "ABC"}, discount_paise=1_000)
		backwards = tax.for_lines(list(reversed(rows)), {c: 1800 for c in "ABC"},
		                          discount_paise=1_000)
		self.assertEqual(forwards["tax_paise"], backwards["tax_paise"])

	def test_a_discount_larger_than_the_cart_taxes_nothing(self):
		rows = [line("A", 1, 10_000)]
		got = tax.for_lines(rows, {"A": 1800}, discount_paise=99_999)
		self.assertEqual(got["tax_paise"], 0)
		self.assertEqual(got["lines"][0]["taxable_paise"], 0)

	def test_an_empty_cart_is_not_a_division_by_zero(self):
		self.assertEqual(tax.for_lines([], {"A": 1800}, discount_paise=500)["tax_paise"], 0)


class TaxedCatalogueFixture(CatalogueFixture):
	"""A site that taxes things. Built here rather than leaned on, as everywhere else in these
	fixtures - whether a test about tax passes must not depend on which sales-tax fixtures
	somebody's ERPNext happens to ship."""

	def setUp(self):
		super().setUp()
		# A tax Account is company infrastructure and part of the chart of accounts, so it is
		# found rather than created. Everything above it is this test's own.
		self.tax_account = frappe.db.get_value(
			"Account", {"account_type": "Tax", "is_group": 0, "company": self.company}, "name")
		if not self.tax_account:
			self.skipTest("no tax account in this company's chart of accounts")

	def template_at(self, percent) -> str:
		data = {
			"doctype": "Item Tax Template",
			"title": self.uid("TAX"),
			"company": self.company,
			"taxes": [{"tax_type": self.tax_account, "tax_rate": percent}],
		}
		# india_compliance, where the site has it, adds its own two fields to this document and
		# will not accept it without them: `gst_treatment` defaults to Taxable, and a Taxable
		# template with a `gst_rate` of zero is refused outright. It cannot work the rate out
		# from the rows either - that is read from the recognised CGST/SGST/IGST accounts, and
		# this fixture builds its own plain tax account on purpose so that a test about *our*
		# arithmetic does not depend on which GST accounts somebody's chart happens to hold.
		#
		# A nil-rated template is how a real site records an item it charges nothing on, so
		# that is what zero means here rather than a Taxable template claiming zero.
		if frappe.get_meta("Item Tax Template").has_field("gst_treatment"):
			data["gst_treatment"] = "Taxable" if percent else "Nil-Rated"
			data["gst_rate"] = percent

		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		return self.track("Item Tax Template", doc.name)

	def taxed_item(self, rate, percent) -> str:
		"""A priced item with a tax template on the item itself."""
		item = self.make_item()
		self.make_item_price(item, rate)
		doc = frappe.get_doc("Item", item)
		doc.append("taxes", {"item_tax_template": self.template_at(percent)})
		doc.flags.ignore_permissions = True
		doc.save(ignore_permissions=True)
		return item


class TestResolvingTheRate(TaxedCatalogueFixture):
	def test_a_template_at_eighteen_per_cent_answers_eighteen_hundred_basis_points(self):
		item = self.taxed_item(rate=100, percent=18)
		rates = compat.item_tax_rates([item], company=self.company)
		self.assertEqual(rates.get(item), 1800)

	def test_an_item_no_template_covers_is_absent_rather_than_zero(self):
		"""Absent and zero mean the same thing to the caller, but absent is the honest shape:
		FieldMate was not told, rather than told nothing is due."""
		plain = self.priced_item()
		self.assertNotIn(plain, compat.item_tax_rates([plain], company=self.company))

	def test_a_site_with_no_templates_at_all_is_answered_without_reading_the_items(self):
		"""Most ERPNext sites. Answered from one count, not from the item list."""
		self.assertEqual(compat.item_tax_rates(["anything"], company=None), {})

	def test_the_rates_in_a_template_are_summed(self):
		"""CGST 9 and SGST 9 are one eighteen per cent to the shopkeeper. FieldMate does not
		split them - the split depends on two states and belongs on the distributor's invoice.

		Two accounts, because ERPNext refuses the same one twice in a template, which is what a
		real pair looks like anyway.
		"""
		accounts = frappe.get_all(
			"Account", filters={"account_type": "Tax", "is_group": 0, "company": self.company},
			pluck="name", limit=2)
		if len(accounts) < 2:
			self.skipTest("this chart of accounts has only one tax account")

		item = self.make_item()
		self.make_item_price(item, 100)
		template = frappe.get_doc({
			"doctype": "Item Tax Template", "title": self.uid("SPLIT"),
			# Same two fields as `template_at`, for the same reason.
			**({"gst_treatment": "Taxable", "gst_rate": 18}
			   if frappe.get_meta("Item Tax Template").has_field("gst_treatment") else {}),
			"company": self.company,
			"taxes": [{"tax_type": accounts[0], "tax_rate": 9},
			          {"tax_type": accounts[1], "tax_rate": 9}],
		}).insert(ignore_permissions=True)
		self.track("Item Tax Template", template.name)

		item_doc = frappe.get_doc("Item", item)
		item_doc.append("taxes", {"item_tax_template": template.name})
		item_doc.flags.ignore_permissions = True
		item_doc.save(ignore_permissions=True)

		self.assertEqual(compat.item_tax_rates([item], company=self.company).get(item), 1800)


class TestTheCatalogueCarriesTheRate(TaxedCatalogueFixture):
	def test_the_phone_is_sent_basis_points_not_an_amount(self):
		"""An amount would go stale on the next tap. The phone has the same rounding primitive
		this server uses, so one number per item is enough."""
		item = self.taxed_item(rate=100, percent=18)
		self.make_catalogue(items=[item])
		payload = self.catalogue_for()
		row = next(i for i in payload["items"] if i["item_code"] == item)
		self.assertEqual(row["tax_bps"], 1800)

	def test_an_untaxed_item_is_sent_zero(self):
		item = self.priced_item()
		self.make_catalogue(items=[item])
		row = next(i for i in self.catalogue_for()["items"] if i["item_code"] == item)
		self.assertEqual(row["tax_bps"], 0)


class TestAnOrderCarriesTheTaxItDoesNotPost(TaxedCatalogueFixture):
	"""`FieldMate Order.tax_total` used to be pinned at zero. It is the distributor's tax and
	FieldMate still posts none of it - but the rep has to quote the figure the shop will be
	billed, not one short by the whole of the GST."""

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

	def test_the_tax_total_is_real(self):
		item = self.taxed_item(rate=100, percent=18)
		self.make_catalogue(items=[item])
		created = self.book(item, qty=10)
		self.track("FieldMate Order", created["name"])

		doc = frappe.get_doc("FieldMate Order", created["name"])
		self.assertEqual(doc.net_total, 1000)
		self.assertEqual(doc.tax_total, 180)
		self.assertEqual(doc.grand_total, 1180)

	def test_an_untaxed_cart_still_totals_to_its_net(self):
		item = self.priced_item()
		self.make_catalogue(items=[item])
		created = self.book(item, qty=3)
		self.track("FieldMate Order", created["name"])

		doc = frappe.get_doc("FieldMate Order", created["name"])
		self.assertEqual(doc.tax_total, 0)
		self.assertEqual(doc.grand_total, doc.net_total)

	def test_nothing_is_posted_for_it(self):
		"""ADR-023 is unchanged by any of this. Showing a figure is not charging it."""
		item = self.taxed_item(rate=100, percent=18)
		self.make_catalogue(items=[item])
		before = frappe.db.count("GL Entry"), frappe.db.count("Sales Invoice")
		created = self.book(item, qty=10)
		self.track("FieldMate Order", created["name"])
		self.assertEqual((frappe.db.count("GL Entry"), frappe.db.count("Sales Invoice")), before)


class TestAPrimarySalePostsItsTax(TaxedCatalogueFixture):
	"""The other half of GST. A secondary order shows the distributor's tax and posts nothing; a
	primary sale is ours, so the Sales Order carries real tax rows and ERPNext computes them -
	including any CGST/SGST split, which is why FieldMate does not do that arithmetic itself.
	"""

	def sales_tax_template(self, percent) -> str:
		doc = frappe.get_doc({
			"doctype": "Sales Taxes and Charges Template",
			"title": self.uid("STC"),
			"company": self.company,
			"taxes": [{
				"charge_type": "On Net Total",
				"account_head": self.tax_account,
				"description": "GST",
				"rate": percent,
			}],
		}).insert(ignore_permissions=True)
		return self.track("Sales Taxes and Charges Template", doc.name)

	def test_the_adapter_carries_a_tax_template_onto_the_sales_order(self):
		"""What FieldMate owns: handing ERPNext the template and letting it do the rest."""
		item = self.priced_item()
		template = self.sales_tax_template(18)
		name = compat.make_sales_order({
			"key": self.uid("SO"),
			"customer": self.outlet.distributor,
			"company": self.company,
			"taxes_and_charges": template,
			"items": [{"item_code": item, "qty": 10, "rate": 100}],
		})
		self.track("Sales Order", name)

		doc = frappe.get_doc("Sales Order", name)
		self.assertEqual(doc.taxes_and_charges, template)
		self.assertEqual(doc.net_total, 1000)
		self.assertEqual(doc.total_taxes_and_charges, 180)
		self.assertEqual(doc.grand_total, 1180)

	def test_fieldmate_names_no_template_and_lets_erpnext_choose(self):
		"""`_raise_sales_order` passes no `taxes_and_charges`, deliberately. Which taxes apply to
		a company's own sales is that company's ERPNext setup - its Tax Rules and its default
		template - and a template named here would quietly override all of it.

		This asserts the absence, because an absence is exactly the kind of thing somebody adds
		'helpfully' later without realising whose decision they are taking.
		"""
		import inspect
		source = inspect.getsource(order_service._raise_sales_order)
		self.assertNotIn("taxes_and_charges", source)


class TestThePhoneIsSentTheTax(TaxedCatalogueFixture):
	"""The order stored its tax and never sent it.

	`tax_total` and `grand_total` were on the document and in neither read the phone makes, so the
	orders list and the order detail could only quote `net_total` - a figure short by the whole of
	the GST on the bill the party actually receives. Both reads name their columns explicitly, so
	a field left out of the list reads as absent rather than as an error, which is the same way
	`portal.me` lost a permission earlier in this phase.

	Found on testerp2 against a real primary order: the Sales Order read 1,099.62 and the phone
	read 981.80.
	"""

	def booked(self, percent=18, qty=10):
		item = self.taxed_item(rate=100, percent=percent)
		self.make_catalogue(items=[item])
		frappe.set_user(self.rep.user)
		try:
			created = order_service.create(
				{"outlet": self.outlet.name, "lines": [{"item": item, "qty": qty}],
				 "client_uuid": self.uid("ORD")},
				self.rep.name,
			)
		finally:
			frappe.set_user("Administrator")
		return self.track("FieldMate Order", created["name"])

	def test_the_order_detail_carries_the_tax_and_the_total_it_makes(self):
		doc = frappe.get_doc("FieldMate Order", self.booked())
		payload = order_service.summarise(doc)

		self.assertEqual(payload["tax_total"], 180)
		self.assertEqual(payload["grand_total"], 1180)
		self.assertEqual(payload["net_total"], 1000, "the goods, still there and still the net")

	def test_the_orders_list_carries_them_too(self):
		name = self.booked()
		frappe.set_user(self.rep.user)
		try:
			rows = order_service.mine(self.rep.name)
		finally:
			frappe.set_user("Administrator")

		row = next(r for r in rows if r["name"] == name)
		self.assertEqual(row["tax_total"], 180)
		self.assertEqual(row["grand_total"], 1180)

	def test_an_untaxed_order_still_answers_both_keys(self):
		"""Zero, not missing. The screen falls back to the net on a site holding no tax
		templates, and it can only do that if the key is there to read."""
		doc = frappe.get_doc("FieldMate Order", self.booked(percent=0))
		payload = order_service.summarise(doc)
		self.assertEqual(payload["tax_total"], 0)
		self.assertEqual(payload["grand_total"], payload["net_total"])

	def test_both_reads_say_which_party_the_order_is_for(self):
		"""A primary order has no outlet - it has a customer. A list selecting only the outlet
		drew a card with a blank name where the party should be."""
		name = self.booked()
		doc = frappe.get_doc("FieldMate Order", name)
		payload = order_service.summarise(doc)
		self.assertEqual(payload["party_type"], "Outlet")
		self.assertEqual(payload["outlet"], self.outlet.name)

		frappe.set_user(self.rep.user)
		try:
			rows = order_service.mine(self.rep.name)
		finally:
			frappe.set_user("Administrator")
		row = next(r for r in rows if r["name"] == name)
		self.assertIn("customer", row, "the key a primary order fills instead of the outlet")
		self.assertEqual(row["party_type"], "Outlet")
