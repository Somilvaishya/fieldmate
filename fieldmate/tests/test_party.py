"""Credit days derived from ERPNext, and the patch that retires FieldMate Distributor Profile."""

import frappe

from fieldmate.patches import carry_distributor_profile_to_customer as carry
from fieldmate.services import party as party_service
from fieldmate.services import settings as settings_service
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_outlet import OutletFixture


class PartyFixture(FieldMateTestCase):
	def setUp(self):
		super().setUp()
		self._group = None
		# The fallback chain ends at the Company, and this site may well have terms set there,
		# which would make "nobody has said" answer with a number. Blanked for the duration and
		# put back in tearDown - explicitly, because `FieldMateTestCase.tearDown` commits, so a
		# change left for the rollback to undo would outlive this class instead.
		# The same chain `_template_for` walks, in the same order. It used to end at "whichever
		# company this site lists first", and where FieldMate has no default company set that is
		# a different company from the one the code goes on to read - so the test wrote terms on
		# one company and asked about another, and the company fallback answered None.
		self._company = settings_service.value("default_company") \
			or frappe.defaults.get_global_default("company") \
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
		"""No template anywhere in the chain is an absence, and says so."""
		self.assertIsNone(party_service.credit_days(self.customer()))

	def test_a_template_that_says_zero_days_answers_zero(self):
		"""Not None. A row reading "all of it, zero days after the invoice date" is how ERPNext
		spells payable on delivery, and it is what ERPNext will put in `due_date`.

		It is also what a half-filled template looks like: testerp2 had one named "15 Days" with
		nothing in its Credit Days field. Answering None there hid the mistake behind a screen
		that simply showed no terms; answering zero puts "0 day terms" in front of somebody.
		"""
		cust = self.customer(payment_terms=self.template((100, DAYS, 0)))
		self.assertEqual(party_service.credit_days(cust), 0)

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

		# `distributor_code` is no longer carried anywhere: the Customer field it used to land in
		# has been dropped, and a depot is known by its own id. The rest still carries.
		got = self.carried(cust, "fm_min_order_value")
		self.assertEqual(got.fm_min_order_value, 500)

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


class TestWhichPartiesARepCanSellTo(OutletFixture):
	"""Four ways onto a rep's list, and the reason carried with each.

	There used to be one: the `distributor` column on outlets in the rep's territory, matched
	**exactly**. So a rep saw whoever supplied their shops and nobody else - a party they owned
	the account for was invisible, and a manager standing on an area saw nothing at all, because
	their own node holds no shops. The screen then blamed the territory whatever the real reason
	was, which is how a list nobody could explain became a list nobody could fix.
	"""

	def sales_person(self) -> str:
		doc = frappe.get_doc({
			"doctype": "Sales Person", "sales_person_name": self.uid("SP"),
			"parent_sales_person": frappe.db.get_value(
				"Sales Person", {"is_group": 1, "parent_sales_person": ("in", ("", None))},
				"name"),
		}).insert(ignore_permissions=True)
		return self.track("Sales Person", doc.name)

	def setUp(self):
		super().setUp()
		self.area = self.make_territory()
		self.mine = self.make_territory(parent=self.area)
		self.theirs = self.make_territory(parent=self.area)
		self.rep = self.make_field_user(territory=self.mine)

	def reached(self):
		return party_service.reachable(self.rep.name)

	# ---------------------------------------------------------------- the four ways

	def test_a_party_whose_sales_team_names_this_rep(self):
		person = self.sales_person()
		frappe.db.set_value("FieldMate Field User", self.rep.name, "sales_person", person)
		party = self.make_distributor()
		# Deliberately in somebody else's territory: an account is owned wherever it sits.
		frappe.db.set_value("Customer", party,
		                    {"fm_tier": "Distributor", "territory": self.theirs})
		doc = frappe.get_doc("Customer", party)
		doc.append("sales_team", {"sales_person": person, "allocated_percentage": 100})
		doc.save(ignore_permissions=True)

		self.assertEqual(self.reached().get(party), party_service.BY_ACCOUNT)

	def test_a_tiered_party_in_the_reps_own_territory(self):
		party = self.make_distributor()
		frappe.db.set_value("Customer", party, {"fm_tier": "Distributor", "territory": self.mine})
		self.assertEqual(self.reached().get(party), party_service.BY_TERRITORY)

	def test_a_party_that_supplies_the_shops_this_rep_serves(self):
		"""The rule that was here before, kept. On a route-selling site it is the true one."""
		outlet = self.make_outlet(territory=self.mine)
		self.assertEqual(self.reached().get(outlet.distributor), party_service.BY_SHOPS)

	def test_the_party_named_on_the_reps_own_record(self):
		"""So a rep with no shops yet does not start on an empty screen."""
		party = self.make_distributor()
		frappe.db.set_value("FieldMate Field User", self.rep.name, "distributor", party)
		self.assertEqual(self.reached().get(party), party_service.BY_ASSIGNMENT)

	# ---------------------------------------------------------------- the edges

	def test_a_manager_sees_the_whole_subtree_below_them(self):
		"""The bug this fixes. An area node holds no shops and no parties - every one of them
		sits on a child - so an exact match left a manager with nothing."""
		manager = self.make_field_user(territory=self.area, designation="Area Manager")
		outlet = self.make_outlet(territory=self.mine)
		party = self.make_distributor()
		frappe.db.set_value("Customer", party, {"fm_tier": "Distributor", "territory": self.theirs})

		reached = party_service.reachable(manager.name)
		self.assertIn(outlet.distributor, reached)
		self.assertIn(party, reached, "a child's party is in the area the manager covers")

	def test_a_rep_does_not_see_the_next_territory_along(self):
		party = self.make_distributor()
		frappe.db.set_value("Customer", party,
		                    {"fm_tier": "Distributor", "territory": self.theirs})
		self.assertNotIn(party, self.reached())

	def test_an_untiered_customer_in_the_territory_is_not_one_of_ours(self):
		"""Most Customers on an ERPNext site have nothing to do with FieldMate, and a party
		FieldMate cannot place in the chain is a door that opens onto a refusal."""
		party = self.make_distributor()
		frappe.db.set_value("Customer", party, {"fm_tier": None, "territory": self.mine})
		self.assertNotIn(party, self.reached())

	def test_a_disabled_party_is_off_the_list_however_it_got_on(self):
		person = self.sales_person()
		frappe.db.set_value("FieldMate Field User", self.rep.name, "sales_person", person)
		party = self.make_distributor()
		frappe.db.set_value("Customer", party, {"fm_tier": "Distributor", "territory": self.mine})
		doc = frappe.get_doc("Customer", party)
		doc.append("sales_team", {"sales_person": person, "allocated_percentage": 100})
		doc.save(ignore_permissions=True)
		self.assertIn(party, self.reached(), "set up first, so the next line proves the disable")

		frappe.db.set_value("Customer", party, "disabled", 1)
		self.assertNotIn(party, self.reached())

	def test_the_most_specific_reason_wins(self):
		"""A party reached two ways is named by the one that says the most about it."""
		person = self.sales_person()
		frappe.db.set_value("FieldMate Field User", self.rep.name, "sales_person", person)
		outlet = self.make_outlet(territory=self.mine)
		doc = frappe.get_doc("Customer", outlet.distributor)
		doc.fm_tier = "Distributor"
		doc.territory = self.mine
		doc.append("sales_team", {"sales_person": person, "allocated_percentage": 100})
		doc.save(ignore_permissions=True)

		self.assertEqual(self.reached().get(outlet.distributor), party_service.BY_ACCOUNT)

	def test_a_rep_with_nothing_set_up_gets_an_empty_list_not_an_error(self):
		self.assertEqual(self.reached(), {})

	# ---------------------------------------------------------------- what the phone reads

	def test_the_reason_travels_to_the_phone_in_words(self):
		"""The screen shows this beside the name. Without it the rep is back to a list they
		cannot explain."""
		outlet = self.make_outlet(territory=self.mine)
		rows = {r["distributor"]: r for r in party_service.counter_facts(self.rep.name)}
		row = rows[outlet.distributor]
		self.assertEqual(row["why"], party_service.BY_SHOPS)
		self.assertEqual(row["why_label"], party_service.WHY[party_service.BY_SHOPS])

	def test_the_old_keys_are_all_still_there(self):
		"""Additive only. Builds already in the field read these and must go on working."""
		self.make_outlet(territory=self.mine)
		row = party_service.counter_facts(self.rep.name)[0]
		for key in ("distributor", "distributor_name", "delivery_days", "credit_days"):
			self.assertIn(key, row)
