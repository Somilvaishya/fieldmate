from unittest.mock import patch

import frappe

from fieldmate import compat
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_masters import MasterFixture


class TestCompat(FieldMateTestCase):
	def test_app_version_returns_tuple(self):
		self.assertTrue(compat.app_version("frappe"))
		self.assertIsInstance(compat.app_version("frappe")[0], int)

	def test_absent_app_returns_empty(self):
		self.assertEqual(compat.app_version("definitely_not_an_app"), ())
		self.assertEqual(compat.major("definitely_not_an_app"), 0)

	def test_capabilities_never_raises_without_hrms(self):
		"""A probe must never take the app down.

		frappe.db.has_column throws when the table is absent, which is normal whenever an
		optional app is on the bench but not installed on this site.
		"""
		caps = compat.capabilities()
		self.assertIn("has_hrms", caps)
		self.assertIsInstance(caps["checkin_has_geo"], bool)
		if not caps["has_hrms"]:
			self.assertFalse(caps["checkin_has_geo"])
			self.assertEqual(caps["hrms_major"], 0)

	def test_version_report_distinguishes_installed_from_on_bench(self):
		report = compat.version_report()
		self.assertIn("frappe", report)
		if not compat.is_installed("hrms") and compat.app_version("hrms"):
			self.assertIn("not installed on this site", report["hrms"])

	def test_required_apps_excludes_hrms(self):
		"""hrms is optional by design - create_employee_checkin degrades to None."""
		self.assertIn("erpnext", compat.REQUIRED_APPS)
		self.assertNotIn("hrms", compat.REQUIRED_APPS)
		self.assertIn("hrms", compat.OPTIONAL_APPS)

	def test_employee_checkin_skipped_without_hrms(self):
		if compat.is_installed("hrms"):
			self.skipTest("hrms installed; the absent-path is what this test covers")
		self.assertIsNone(
			compat.create_employee_checkin("nobody@example.com", "IN", frappe.utils.now())
		)

	def test_outstanding_is_zero_for_unknown_party(self):
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("no company on this site")
		self.assertEqual(compat.get_outstanding(self.uid("NOCUST"), company), 0)

	def test_open_orders_are_counted_only_when_asked_for(self):
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("no company on this site")
		self.assertEqual(
			compat.get_outstanding(self.uid("NOCUST"), company, include_open_orders=True), 0
		)


class TestPricingAdapters(MasterFixture):
	"""The pricing path is where a wrong answer costs money rather than raising."""

	def setUp(self):
		super().setUp()
		self.price_list = self.make_price_list()

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

	def test_an_unpriced_item_reads_as_none_and_not_as_zero(self):
		"""0.0 would send the line out free. None stops it and makes somebody answer."""
		self.assertIsNone(compat.get_item_price(self.make_item(), self.price_list))

	def test_a_rate_of_zero_is_a_real_rate(self):
		item = self.make_item()
		self.make_item_price(item, 0)
		self.assertEqual(compat.get_item_price(item, self.price_list), 0.0)

	def test_a_price_comes_back_as_a_number(self):
		item = self.make_item()
		self.make_item_price(item, 122.5)
		self.assertEqual(compat.get_item_price(item, self.price_list, qty=24), 122.5)

	def test_details_come_back_once_per_item(self):
		priced, unpriced = self.make_item(), self.make_item()
		self.make_item_price(priced, 120)

		rows = {row["item_code"]: row for row in
		        compat.get_item_details([priced, unpriced], self.price_list)}
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[priced]["price_list_rate"], 120)
		self.assertIsNone(rows[unpriced]["price_list_rate"])
		self.assertEqual(rows[priced]["conversion_factor"], 1.0)
		self.assertEqual(rows[priced]["sales_uom"], rows[priced]["stock_uom"])
		self.assertFalse(rows[priced]["disabled"])

	def test_an_empty_catalogue_request_asks_nothing(self):
		self.assertEqual(compat.get_item_details([]), [])


class TestSalesOrderAdapters(FieldMateTestCase):
	def test_an_order_with_no_key_is_refused(self):
		"""Without a key a retried sync would post a second commitment for the same order."""
		with self.assertRaises(frappe.ValidationError):
			compat.make_sales_order({"customer": "nobody"})

	def test_cancelling_what_is_not_there_is_not_an_error(self):
		"""A retried cancel is the ordinary state after a dropped connection."""
		self.assertIsNone(compat.cancel_sales_order("SAL-ORD-does-not-exist"))


class TestTheErpnextTaxDependency(FieldMateTestCase):
	"""`compat.item_tax_rates` calls two functions inside ERPNext, one of them private.

	That is a deliberate trade, argued in its docstring: the alternative is a second copy of
	ERPNext's three template-selection rules - a tax category, a validity window and a net-rate
	band - which would drift from the first and misprice tax silently. The price of the trade is
	this test, which turns a signature change in ERPNext into a failure here rather than a wrong
	number on a bill.
	"""

	def test_the_matcher_is_still_where_we_call_it(self):
		from erpnext.stock.get_item_details import _get_item_tax_template, get_item_tax_map
		self.assertTrue(callable(_get_item_tax_template))
		self.assertTrue(callable(get_item_tax_map))

	def test_the_matcher_still_takes_args_and_a_list_of_rows(self):
		"""Called with no matching rows it answers None rather than raising - which is also the
		shape `item_tax_rates` relies on for every item no template covers."""
		from erpnext.stock.get_item_details import _get_item_tax_template
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("no company on this site")
		answer = _get_item_tax_template(
			{"company": company, "tax_category": "", "base_net_rate": 0}, [])
		self.assertIsNone(answer)

	def test_the_rate_map_takes_a_company_and_a_template(self):
		from erpnext.stock.get_item_details import get_item_tax_map
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("no company on this site")
		# No template at all is the ordinary case on most sites, and must answer empty.
		self.assertFalse(get_item_tax_map(company, None, as_json=False))

	def test_a_site_with_no_templates_is_answered_without_touching_the_item_list(self):
		"""The fast path that most ERPNext sites take. `company=None` cannot resolve anything,
		so it must return empty rather than query for items that were never going to be taxed."""
		self.assertEqual(compat.item_tax_rates(["NO-SUCH-ITEM"], company=None), {})


class TestAccountingDimensionDefaults(FieldMateTestCase):
	"""ERPNext applies a dimension's per-company default in the **form** and nowhere else.

	`dimension_tree_filter.js` calls `frm.set_value(fieldname, default_dimension)` when a document
	is opened in Desk; no server-side path does the same. Every document this app creates is
	therefore missing defaults that the identical document typed into Desk would carry.

	That is invisible until something depends on it. A bench carrying `location_based_series`
	makes `location` mandatory on every Sales Order, Sales Invoice and Delivery Note — and every
	primary order FieldMate posted on such a site was refused with "Select Location before
	Saving", a message naming a field the rep has never heard of and cannot supply.

	The dimensions themselves are ERPNext's to define, so what is tested here is ours: which
	fields get filled, which are left exactly as the caller set them, and that a site with
	nothing configured is left completely alone.
	"""

	COMPANY = "Dimension Test Co"

	def doc(self, **values):
		"""A document stand-in with the two fields a Sales Order would have."""
		doc = frappe.get_doc({"doctype": "Sales Order"})
		doc.company = values.pop("company", self.COMPANY)
		for field, value in values.items():
			doc.set(field, value)
		return doc

	def patched(self, dimensions, defaults):
		return patch(
			"erpnext.accounts.doctype.accounting_dimension.accounting_dimension.get_dimensions",
			return_value=(dimensions, defaults),
		)

	def test_an_empty_dimension_is_filled_from_the_company_default(self):
		dimensions = [{"fieldname": "cost_center", "document_type": "Cost Center"}]
		with self.patched(dimensions, {self.COMPANY: {"cost_center": "Main - DT"}}):
			doc = self.doc()
			compat.apply_dimension_defaults(doc)
		self.assertEqual(doc.cost_center, "Main - DT")

	def test_a_value_the_caller_already_chose_is_left_alone(self):
		"""Only what a person's browser would have filled, and the browser fills blanks."""
		dimensions = [{"fieldname": "cost_center", "document_type": "Cost Center"}]
		with self.patched(dimensions, {self.COMPANY: {"cost_center": "Main - DT"}}):
			doc = self.doc(cost_center="Chosen - DT")
			compat.apply_dimension_defaults(doc)
		self.assertEqual(doc.cost_center, "Chosen - DT")

	def test_a_field_this_doctype_does_not_have_is_skipped(self):
		"""A dimension is a custom field, and a site can enable one on some doctypes and not
		others. Writing it blind would throw on a document that never had the column."""
		dimensions = [{"fieldname": "fm_not_a_real_dimension", "document_type": "Location"}]
		with self.patched(dimensions, {self.COMPANY: {"fm_not_a_real_dimension": "X"}}):
			doc = self.doc()
			compat.apply_dimension_defaults(doc)  # must not raise
		self.assertFalse(doc.get("fm_not_a_real_dimension"))

	def test_another_companys_default_is_not_used(self):
		dimensions = [{"fieldname": "cost_center", "document_type": "Cost Center"}]
		with self.patched(dimensions, {"Somebody Else": {"cost_center": "Theirs - SE"}}):
			doc = self.doc()
			compat.apply_dimension_defaults(doc)
		self.assertFalse(doc.cost_center)

	def test_a_site_with_no_dimensions_is_left_alone(self):
		"""Which is most sites. Doing nothing has to be the quiet, ordinary outcome."""
		with self.patched([], {}):
			doc = self.doc(cost_center="Chosen - DT")
			compat.apply_dimension_defaults(doc)
		self.assertEqual(doc.cost_center, "Chosen - DT")

	def test_a_document_with_no_company_is_left_alone(self):
		"""Defaults are per company, so without one there is nothing to look up."""
		dimensions = [{"fieldname": "cost_center", "document_type": "Cost Center"}]
		with self.patched(dimensions, {self.COMPANY: {"cost_center": "Main - DT"}}):
			doc = self.doc(company=None)
			compat.apply_dimension_defaults(doc)
		self.assertFalse(doc.cost_center)

	def test_erpnext_failing_to_answer_does_not_fail_the_sale(self):
		"""A site mid-migration can have the DocType without its table. A missing default is not
		worth refusing an order over - the document is posted without it, as it was before."""
		with patch(
			"erpnext.accounts.doctype.accounting_dimension.accounting_dimension.get_dimensions",
			side_effect=Exception("table is gone"),
		):
			doc = self.doc()
			compat.apply_dimension_defaults(doc)  # must not raise
		self.assertFalse(doc.cost_center)
