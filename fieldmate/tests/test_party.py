"""Credit days derived from ERPNext, and the patch that retires FieldMate Distributor Profile."""

import frappe

from fieldmate.patches import carry_distributor_profile_to_customer as carry
from fieldmate.services import party as party_service
from fieldmate.services import settings as settings_service
from fieldmate.tests.base import FieldMateTestCase


class PartyFixture(FieldMateTestCase):
	def setUp(self):
		super().setUp()
		self._group = None
		# The fallback chain ends at the Company, and this site may well have terms set there,
		# which would make "nobody has said" answer with a number. Blanked for the duration and
		# put back in tearDown - explicitly, because `FieldMateTestCase.tearDown` commits, so a
		# change left for the rollback to undo would outlive this class instead.
		self._company = settings_service.value("default_company") \
			or frappe.db.get_value("Company", {}, "name")
		self._company_terms = frappe.db.get_value("Company", self._company, "payment_terms") \
			if self._company else None
		if self._company_terms:
			frappe.db.set_value("Company", self._company, "payment_terms", None)

	def tearDown(self):
		# Always, not only when there was something to restore: a test that puts its own template
		# on the Company would otherwise leave the link behind once the template is deleted.
		if self._company:
			frappe.db.set_value("Company", self._company, "payment_terms", self._company_terms)
		super().tearDown()

	def leaf_customer_group(self) -> str:
		"""A group of our own, so nobody else's payment terms answer for this test."""
		if not self._group:
			root = frappe.db.get_value(
				"Customer Group", {"is_group": 1, "parent_customer_group": ("in", ("", None))},
				"name")
			doc = frappe.get_doc({
				"doctype": "Customer Group",
				"customer_group_name": self.uid("PY-CG"),
				"parent_customer_group": root,
				"is_group": 0,
			}).insert(ignore_permissions=True)
			self._group = self.track("Customer Group", doc.name)
		return self._group

	def customer(self, **values):
		doc = frappe.get_doc({
			"doctype": "Customer",
			"customer_name": self.uid("PY-CUST"),
			"customer_type": "Company",
			"customer_group": self.leaf_customer_group(),
			**values,
		})
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		return self.track("Customer", doc.name)

	def template(self, *rows):
		"""A Payment Terms Template. Each row is (invoice_portion, basis, days_or_months)."""
		doc = frappe.get_doc({
			"doctype": "Payment Terms Template",
			"template_name": self.uid("PY-PTT"),
			"terms": [
				{
					"invoice_portion": portion,
					"due_date_based_on": basis,
					"credit_months" if basis.startswith("Month") else "credit_days": number,
				}
				for portion, basis, number in rows
			],
		}).insert(ignore_permissions=True)
		return self.track("Payment Terms Template", doc.name)

	def territory(self, prefix="PY-TERR"):
		root = frappe.db.get_value("Territory", {"is_group": 1, "parent_territory": ("in", ("", None))}, "name")
		doc = frappe.get_doc({
			"doctype": "Territory",
			"territory_name": self.uid(prefix),
			"parent_territory": root,
			"is_group": 0,
		}).insert(ignore_permissions=True)
		return self.track("Territory", doc.name)

	def root_territory(self) -> str:
		return frappe.db.get_value(
			"Territory", {"is_group": 1, "parent_territory": ("in", ("", None))}, "name")

	def profile(self, customer: str, **values):
		doc = frappe.get_doc({
			"doctype": "FieldMate Distributor Profile",
			"customer": customer,
			"status": "Active",
			"territory": values.pop("territory", None) or self.territory(),
			**values,
		}).insert(ignore_permissions=True)
		return self.track("FieldMate Distributor Profile", doc.name)


DAYS = "Day(s) after invoice date"
MONTHS = "Month(s) after the end of the invoice month"


class TestCreditDaysComeFromPaymentTerms(PartyFixture):
	"""No `fm_credit_days` field exists, on purpose. This is what answers instead."""

	def test_nobody_has_said_answers_none_rather_than_zero(self):
		"""Zero would read as "due today", which is a thing somebody might act on."""
		self.assertIsNone(party_service.credit_days(self.customer()))

	def test_one_row_is_its_credit_days(self):
		cust = self.customer(payment_terms=self.template((100, DAYS, 15)))
		self.assertEqual(party_service.credit_days(cust), 15)

	def test_two_rows_answer_the_later_one(self):
		"""Half in fifteen days and half in thirty means you have thirty days to pay in full."""
		cust = self.customer(payment_terms=self.template((50, DAYS, 15), (50, DAYS, 30)))
		self.assertEqual(party_service.credit_days(cust), 30)

	def test_months_are_counted_as_days(self):
		cust = self.customer(payment_terms=self.template((100, MONTHS, 2)))
		self.assertEqual(party_service.credit_days(cust),
		                 2 * party_service.DAYS_IN_MONTH)

	def test_the_customer_group_answers_when_the_party_does_not(self):
		"""ERPNext's own fallback order, so FieldMate reads the same terms the invoice will."""
		group_template = self.template((100, DAYS, 21))
		frappe.db.set_value("Customer Group", self.leaf_customer_group(),
		                    "payment_terms", group_template)
		self.assertEqual(party_service.credit_days(self.customer()), 21)

	def test_the_partys_own_terms_beat_its_groups(self):
		frappe.db.set_value("Customer Group", self.leaf_customer_group(),
		                    "payment_terms", self.template((100, DAYS, 21)))
		cust = self.customer(payment_terms=self.template((100, DAYS, 7)))
		self.assertEqual(party_service.credit_days(cust), 7)

	def test_the_company_answers_when_nobody_nearer_does(self):
		frappe.db.set_value("Company", self._company, "payment_terms",
		                    self.template((100, DAYS, 45)))
		self.assertEqual(party_service.credit_days(self.customer()), 45)

	def test_a_row_with_no_days_of_its_own_reads_the_payment_term_it_names(self):
		"""A row written by an import never had ERPNext copy the master's values into it."""
		term = frappe.get_doc({
			"doctype": "Payment Term",
			"payment_term_name": self.uid("PY-TERM"),
			"due_date_based_on": DAYS,
			"credit_days": 10,
		}).insert(ignore_permissions=True)
		self.track("Payment Term", term.name)

		template = frappe.get_doc({
			"doctype": "Payment Terms Template",
			"template_name": self.uid("PY-PTT"),
			"terms": [{"invoice_portion": 100, "due_date_based_on": DAYS,
			           "payment_term": term.name, "credit_days": 0}],
		}).insert(ignore_permissions=True)
		self.track("Payment Terms Template", template.name)

		self.assertEqual(party_service.credit_days(self.customer(payment_terms=template.name)), 10)

	def test_an_unknown_party_is_not_an_error(self):
		self.assertIsNone(party_service.credit_days(None))
		self.assertIsNone(party_service.credit_days("PY-NO-SUCH-CUSTOMER"))


class TestRetiringTheDistributorProfile(PartyFixture):
	"""The patch carries the profile's data onto its Customer. 2d-i: data only, no rewiring.

	Skipped once the DocType is gone, which it is on any site installed after step 2d-iii. The
	class stays rather than being deleted: the patch it exercises still ships, because a site
	upgrading across this change has profiles to carry, and this is the only record of what that
	patch is supposed to do. `remove_orphan_doctypes` runs after both patch passes, so on such a
	site the patch does its work first and these tests can still run against it.
	"""

	def setUp(self):
		if not frappe.db.exists("DocType", "FieldMate Distributor Profile"):
			self.skipTest("FieldMate Distributor Profile has been dropped; the patch it tests "
			              "only runs on a site upgrading across step 2d")
		super().setUp()

	def carried(self, customer: str, *fields):
		carry.execute()
		return frappe.db.get_value("Customer", customer, list(fields), as_dict=True)

	def test_the_commercial_fields_land_on_the_customer(self):
		cust = self.customer()
		self.profile(cust, min_order_value=500, distributor_code="MLX-01")

		got = self.carried(cust, "fm_min_order_value", "fm_distributor_code")
		self.assertEqual(got.fm_min_order_value, 500)
		self.assertEqual(got.fm_distributor_code, "MLX-01")

	def test_delivery_days_becomes_a_lead_time(self):
		"""The field was Data and the live value was the string "2"; the phone always read it
		with Number(). The data and the reader agreed; only the label said otherwise."""
		cust = self.customer()
		self.profile(cust, delivery_days="2")
		self.assertEqual(self.carried(cust, "fm_delivery_days").fm_delivery_days, 2)

	def test_a_delivery_day_list_is_reported_rather_than_read_as_zero(self):
		"""Zero lead days reads as same-day dispatch, which is a promise to a shopkeeper."""
		cust = self.customer()
		self.profile(cust, delivery_days="Mon, Wed, Fri")
		self.assertFalse(self.carried(cust, "fm_delivery_days").fm_delivery_days)

	def test_every_profile_becomes_a_distributor_buying_from_the_company(self):
		cust = self.customer()
		self.profile(cust)
		got = self.carried(cust, "fm_tier", "fm_buys_from")
		self.assertEqual(got.fm_tier, "Distributor")
		self.assertEqual(got.fm_buys_from, "Company")

	def test_what_the_customer_already_knows_is_left_alone(self):
		"""The profile is the thinner record. Where both have an answer, the Customer's stands."""
		cust = self.customer(fm_min_order_value=900, fm_tier="Super Stockist")
		self.profile(cust, min_order_value=500)

		got = self.carried(cust, "fm_min_order_value", "fm_tier")
		self.assertEqual(got.fm_min_order_value, 900)
		self.assertEqual(got.fm_tier, "Super Stockist")

	def test_the_price_list_is_what_shops_pay_not_what_the_party_pays(self):
		"""`default_price_list` is what ERPNext bills this party from. Writing the profile's list
		there would change what a live distributor is charged."""
		price_list = frappe.get_doc({
			"doctype": "Price List",
			"price_list_name": self.uid("PY-PL"),
			"selling": 1,
			"currency": frappe.db.get_value("Company", self._company, "default_currency") or "INR",
		}).insert(ignore_permissions=True)
		self.track("Price List", price_list.name)

		cust = self.customer()
		self.profile(cust, price_list=price_list.name)

		got = self.carried(cust, "fm_ptr_price_list", "default_price_list")
		self.assertEqual(got.fm_ptr_price_list, price_list.name)
		self.assertFalse(got.default_price_list, "the party's own billing list is untouched")

	def test_a_real_territory_on_the_customer_survives(self):
		mine, theirs = self.territory("PY-A"), self.territory("PY-B")
		cust = self.customer(territory=theirs)
		self.profile(cust, territory=mine)
		self.assertEqual(self.carried(cust, "territory").territory, theirs)

	def test_the_root_territory_is_replaced_because_it_says_nothing(self):
		"""Frappe fills an untouched Link from the session, and a Customer created in Desk by
		somebody who never opened the field reads "All Territories"."""
		mine = self.territory("PY-A")
		cust = self.customer(territory=self.root_territory())
		self.profile(cust, territory=mine)
		self.assertEqual(self.carried(cust, "territory").territory, mine)

	def test_running_it_twice_changes_nothing_the_second_time(self):
		cust = self.customer()
		self.profile(cust, min_order_value=500, delivery_days="3")

		first = self.carried(cust, "fm_min_order_value", "fm_delivery_days", "fm_tier")
		second = self.carried(cust, "fm_min_order_value", "fm_delivery_days", "fm_tier")
		self.assertEqual(first, second)

	def test_credit_days_with_no_payment_terms_is_reported_not_stored(self):
		"""There is deliberately no field to put it in; `party.credit_days` answers instead."""
		cust = self.customer()
		self.profile(cust, credit_days=15)
		carry.execute()
		self.assertFalse(frappe.get_meta("Customer").has_field("fm_credit_days"))
		self.assertIsNone(party_service.credit_days(cust))
