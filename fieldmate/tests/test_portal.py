"""The distributor's end: the order queue, and the claims raised off it.

Two things are being proved here, and they are not the same thing.

The first is scoping. A depot logs in with an ordinary Frappe login, and every query it makes
has to be narrowed to its own profile - at the service layer, and again at the framework layer,
because the second is what catches the route nobody thought of. Gate 9 criterion 1 asks for a
document belonging to another depot to be *refused*, not merely absent from a list, so that is
what is asserted.

The second is that a claim is arithmetic nobody at the depot did. Every line is copied from a
Scheme Ledger row the server wrote when the order was routed, and the reconciliation figure on
the claim is computed against the ledger rather than against the lines attached. Criterion 2 is
that comparison.
"""

import frappe
from frappe.utils import add_days, flt, today

from fieldmate.api import portal as portal_api
from fieldmate.services import claim as claim_service
from fieldmate.services import portal as portal_service
from fieldmate.tests.test_order import OrderFixture


class PortalFixture(OrderFixture):
	"""An order in the depot's queue, and a portal login that may work it."""

	def setUp(self):
		super().setUp()
		self.depot = self.make_portal_user(self.distributor.name)

	def tearDown(self):
		frappe.set_user("Administrator")
		self.wipe_since_setup("FieldMate Order Ingest Log", "FieldMate Claim")
		super().tearDown()

	def make_portal_user(self, distributor, **extra):
		email = f"{self.uid('depot')}@fieldmate.test"
		user = frappe.get_doc({
			"doctype": "User", "email": email, "first_name": "Depot Desk",
			"send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		self.track("User", user.name)
		data = {"doctype": "FieldMate Portal User", "user": email, "distributor": distributor}
		data.update(extra)
		row = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Portal User", row.name)
		return row

	def second_depot(self):
		"""A whole other distributor, with an order of its own. The thing criterion 1 probes."""
		other_customer = frappe.get_doc({
			"doctype": "Customer", "customer_name": self.uid("OTHER-DIST"),
			"customer_type": "Company",
			# Named rather than left blank. Frappe fills an empty Link from the session default,
			# which here is the root group, and ERPNext then refuses the Customer for a reason
			# that says nothing about what the test was doing (ADR-020).
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": self.rep.territory,
		}).insert(ignore_permissions=True)
		self.track("Customer", other_customer.name)
		# No FieldMate Distributor Profile beside it since step 2d: a distributor IS the Customer,
		# and `FieldMate Order.distributor` links straight to one.
		frappe.db.set_value("Customer", other_customer.name,
		                    {"fm_tier": "Distributor", "fm_buys_from": "Company"},
		                    update_modified=False)
		frappe.clear_document_cache("Customer", other_customer.name)
		return other_customer

	def as_depot(self, fn, *args, **kwargs):
		frappe.set_user(self.depot.user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def routed(self, qty=20):
		"""An order sitting in the depot's queue, which is where Phase 9 starts."""
		result = self.book(qty=qty)
		self.assertEqual(result["order_status"], "Sent To Distributor",
		                 "Phase 9 has nothing to work on unless routing still works")
		return result["name"]


# --------------------------------------------------------------------------------------
# criterion 1 — a depot sees its own documents and is refused everyone else's
# --------------------------------------------------------------------------------------


class TestWhatADepotIsToldAboutItself(PortalFixture):
	"""`whoami` draws the portal header. Since step 2d it reads the Customer, not a profile."""

	def test_the_depot_is_named_by_its_customer(self):
		answer = self.as_depot(portal_api.whoami)["data"]
		self.assertEqual(answer["distributor"], self.distributor.name)
		self.assertEqual(answer["distributor_name"], self.distributor.customer_name)
		self.assertEqual(answer["customer"], self.distributor.name,
		                 "the distributor and the billing account are one record now")

	def test_the_counter_facts_come_off_the_customer(self):
		frappe.db.set_value("Customer", self.distributor.name,
		                    {"fm_distributor_code": "MLX-01", "fm_delivery_days": 3},
		                    update_modified=False)
		frappe.clear_document_cache("Customer", self.distributor.name)

		answer = self.as_depot(portal_api.whoami)["data"]
		self.assertEqual(answer["distributor_code"], "MLX-01")
		self.assertEqual(answer["delivery_days"], 3)

	def test_credit_days_are_derived_from_the_payment_terms(self):
		"""There is no credit-days field on a Customer. The template is what bills this party,
		so the template is what the header reads - see `services.party`."""
		template = frappe.get_doc({
			"doctype": "Payment Terms Template",
			"template_name": self.uid("PRT-PTT"),
			"terms": [{"invoice_portion": 100,
			           "due_date_based_on": "Day(s) after invoice date",
			           "credit_days": 21}],
		}).insert(ignore_permissions=True)
		self.track("Payment Terms Template", template.name)
		frappe.db.set_value("Customer", self.distributor.name, "payment_terms", template.name,
		                    update_modified=False)
		frappe.clear_document_cache("Customer", self.distributor.name)

		self.assertEqual(self.as_depot(portal_api.whoami)["data"]["credit_days"], 21)
		# What happens when nobody has set any terms is `services.party`'s question, and
		# `test_party` asks it there - against a Company whose own default has been blanked for
		# the duration. Asking it here would pass or fail on how this site is configured.


class TestADepotSeesOnlyItsOwn(PortalFixture):
	def test_the_queue_holds_this_depots_orders(self):
		name = self.routed()
		rows = self.as_depot(portal_service.orders)
		self.assertIn(name, [r.name for r in rows])

	def test_another_depots_order_is_refused_not_hidden(self):
		"""The criterion in as many words: attempt another depot's document.

		Absence from a list is not the assertion. A caller who knows the name has to be refused,
		because knowing the name is exactly what an api.resource call needs.
		"""
		name = self.routed()
		other = self.second_depot()
		frappe.db.set_value("FieldMate Order", name, "distributor", other.name,
		                    update_modified=False)

		with self.assertRaises(frappe.PermissionError):
			self.as_depot(portal_service.order_detail, name)

	def test_another_depots_order_cannot_be_moved(self):
		name = self.routed()
		other = self.second_depot()
		frappe.db.set_value("FieldMate Order", name, "distributor", other.name,
		                    update_modified=False)

		with self.assertRaises(frappe.PermissionError):
			self.as_depot(portal_service.act, name, "Accepted")
		self.assertEqual(
			frappe.db.get_value("FieldMate Order", name, "order_status"),
			"Sent To Distributor",
			"a refused move must leave the order where it was",
		)

	def test_the_framework_narrows_a_plain_query_too(self):
		"""Belt and braces. The service layer covers the portal's own screens; this covers the
		report, the Desk list and whatever gets added later that forgets to ask."""
		mine = self.routed()
		other = self.second_depot()
		stray = self.routed()
		frappe.db.set_value("FieldMate Order", stray, "distributor", other.name,
		                    update_modified=False)

		frappe.set_user(self.depot.user)
		try:
			names = [r.name for r in frappe.get_list(
				"FieldMate Order", fields=["name"], limit_page_length=0,
				user=self.depot.user, ignore_permissions=False)]
		finally:
			frappe.set_user("Administrator")

		self.assertIn(mine, names)
		self.assertNotIn(stray, names, "permission_query_conditions did not narrow the list")

	def test_a_login_with_no_depot_gets_nothing(self):
		user = frappe.get_doc({
			"doctype": "User", "email": f"{self.uid('nobody')}@fieldmate.test",
			"first_name": "Nobody", "send_welcome_email": 0,
		}).insert(ignore_permissions=True)
		self.track("User", user.name)

		frappe.set_user(user.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				portal_service.me()
		finally:
			frappe.set_user("Administrator")

	def test_a_deactivated_login_is_refused(self):
		frappe.db.set_value("FieldMate Portal User", self.depot.name, "is_active", 0)
		with self.assertRaises(frappe.PermissionError):
			self.as_depot(portal_service.me)

	def test_a_desk_administrator_cannot_be_given_a_depot(self):
		"""A scoped login that carries permissions from elsewhere is not scoped."""
		admin = frappe.get_doc({
			"doctype": "User", "email": f"{self.uid('boss')}@fieldmate.test",
			"first_name": "Boss", "send_welcome_email": 0,
			"roles": [{"role": "System Manager"}],
		}).insert(ignore_permissions=True)
		self.track("User", admin.name)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({
				"doctype": "FieldMate Portal User",
				"user": admin.name, "distributor": self.distributor.name,
			}).insert(ignore_permissions=True)


# --------------------------------------------------------------------------------------
# criterion 4 — what the depot sets reaches the rep
# --------------------------------------------------------------------------------------


class TestWorkingTheQueue(PortalFixture):
	def test_accepting_moves_the_order_and_writes_it_down(self):
		name = self.routed()
		self.as_depot(portal_service.act, name, "Accepted")

		self.assertEqual(frappe.db.get_value("FieldMate Order", name, "order_status"), "Accepted")
		log = frappe.get_all("FieldMate Order Ingest Log", filters={"order": name},
		                     fields=["action", "from_status", "to_status", "acted_by", "source"])
		self.assertEqual(len(log), 1)
		self.assertEqual(log[0].from_status, "Sent To Distributor")
		self.assertEqual(log[0].to_status, "Accepted")
		self.assertEqual(log[0].acted_by, self.depot.user)
		self.assertEqual(log[0].source, "Portal")

	def test_the_same_tap_twice_is_the_same_answer(self):
		"""A depot on a bad connection taps Accept twice. The second tap must not be a second
		event a week later saying the order was accepted again."""
		name = self.routed()
		self.as_depot(portal_service.act, name, "Accepted")
		again = self.as_depot(portal_service.act, name, "Accepted")

		self.assertTrue(again["repeated"])
		self.assertEqual(
			frappe.db.count("FieldMate Order Ingest Log", {"order": name}), 1,
			"a repeated tap must not append a second log row",
		)

	def test_a_move_the_order_cannot_make_is_refused(self):
		name = self.routed()
		with self.assertRaises(frappe.ValidationError):
			self.as_depot(portal_service.act, name, "Delivered")

	def test_rejecting_without_a_reason_is_refused(self):
		name = self.routed()
		with self.assertRaises(frappe.ValidationError):
			self.as_depot(portal_service.act, name, "Rejected")

	def test_invoicing_without_a_number_is_refused(self):
		name = self.routed()
		self.as_depot(portal_service.act, name, "Accepted")
		with self.assertRaises(frappe.ValidationError):
			self.as_depot(portal_service.act, name, "Invoiced")

	def test_invoicing_keeps_the_depots_own_number(self):
		name = self.routed()
		self.as_depot(portal_service.act, name, "Accepted")
		self.as_depot(portal_service.act, name, "Invoiced", reference="DEP/2026/4471")

		self.assertEqual(
			frappe.db.get_value("FieldMate Order", name, "distributor_reference"),
			"DEP/2026/4471",
			"the only thread from our order to their bill",
		)

	def test_a_read_only_login_cannot_work_the_queue(self):
		name = self.routed()
		frappe.db.set_value("FieldMate Portal User", self.depot.name, "can_accept_orders", 0)
		with self.assertRaises(frappe.PermissionError):
			self.as_depot(portal_service.act, name, "Accepted")

	def test_the_move_reaches_the_reps_next_sync(self):
		"""Gate 9 criterion 4.

		The rep is the person the shopkeeper asks the next morning. Before Phase 9 the order was
		push-only, so the phone would still be showing "Sent To Distributor" on an order the
		depot delivered on Tuesday.
		"""
		from fieldmate.services import sync as sync_service

		name = self.routed()
		before = sync_service.pull(self.rep.user, doctypes=["FieldMate Order"])
		sent = {r["name"]: r for r in before["changes"]["FieldMate Order"]}
		self.assertEqual(sent[name]["order_status"], "Sent To Distributor")

		self.as_depot(portal_service.act, name, "Accepted")
		self.as_depot(portal_service.act, name, "Invoiced", reference="DEP/9/1")

		after = sync_service.pull(self.rep.user, since=before["watermark"],
		                          doctypes=["FieldMate Order"])
		rows = {r["name"]: r for r in after["changes"]["FieldMate Order"]}
		self.assertIn(name, rows, "the depot moved it, so it has to come down on the next pull")
		self.assertEqual(rows[name]["order_status"], "Invoiced")
		self.assertEqual(rows[name]["distributor_reference"], "DEP/9/1")

	def test_a_rep_still_cannot_set_their_own_status(self):
		"""Pull was turned on in Phase 9. Push must not have been widened with it."""
		from fieldmate.services import registry

		entry = registry.get("FieldMate Order")
		for field in ("order_status", "distributor_reference", "sent_to_distributor_on"):
			self.assertIn(field, entry.server_owned,
			              f"{field} must stay server-owned or the queue is decorative")


# --------------------------------------------------------------------------------------
# criterion 2 — a claim reconciles to the benefits actually granted
# --------------------------------------------------------------------------------------


class ClaimFixture(PortalFixture):
	def setUp(self):
		super().setUp()
		self.scheme = self.make_scheme()

	def accrued(self, qty=20):
		"""An order that granted a benefit, and the ledger rows behind it."""
		name = self.routed(qty=qty)
		rows = frappe.get_all(
			"FieldMate Scheme Ledger",
			filters={"order": name, "docstatus": 1},
			fields=["name", "benefit_amount", "benefit_kind", "status", "distributor"],
		)
		self.assertTrue(rows, "the fixture's scheme granted nothing, so there is nothing to claim")
		return name, rows

	# A window wide enough to hold anything the fixture books today.
	def window(self):
		return add_days(today(), -30), today()


class TestAClaimIsArithmeticNobodyDid(ClaimFixture):
	def test_a_claim_reconciles_to_the_ledger(self):
		"""Gate 9 criterion 2.

		The claim's own lines and the window's accruals are counted separately and compared. If
		they agree the flag is set; the test asserts both the flag and the two figures, because a
		flag that is always true would pass on its own.
		"""
		_, rows = self.accrued()
		expected = sum(flt(r.benefit_amount) for r in rows)

		from_date, to_date = self.window()
		name = claim_service.build(self.distributor.name, from_date, to_date)
		self.track("FieldMate Claim", name)
		doc = frappe.get_doc("FieldMate Claim", name)

		self.assertEqual(doc.line_count, len(rows))
		self.assertAlmostEqual(flt(doc.claimed_amount), expected, places=2)
		self.assertAlmostEqual(flt(doc.ledger_amount), expected, places=2)
		self.assertAlmostEqual(flt(doc.variance_amount), 0.0, places=2)
		self.assertTrue(doc.reconciles)

	def test_a_partial_claim_is_flagged_rather_than_refused(self):
		"""A depot may deliberately claim part of a month. The gap is measured, not blocked -
		but it is never silent, because an unflagged partial claim and an unflagged missing
		accrual look identical at approval."""
		_, rows = self.accrued()
		self.accrued(qty=40)

		from_date, to_date = self.window()
		doc = frappe.new_doc("FieldMate Claim")
		doc.claim_date = today()
		doc.distributor = self.distributor.name
		doc.company = frappe.db.get_value("FieldMate Scheme Ledger", rows[0].name, "company")
		doc.from_date, doc.to_date = from_date, to_date
		for row in rows:
			doc.append("items", {"scheme_ledger": row.name})
		doc.flags.ignore_permissions = True
		doc.insert()
		self.track("FieldMate Claim", doc.name)

		self.assertFalse(doc.reconciles)
		self.assertGreater(flt(doc.variance_amount), 0,
		                   "what was left out has to show as unclaimed, not as nothing")

	def test_an_incentive_row_is_not_claimable(self):
		"""What the rep earned never came off a shop bill, so the depot was never out of
		pocket for it. Adding it to a claim would have us paying the same money twice."""
		_, rows = self.accrued()
		frappe.db.set_value("FieldMate Scheme Ledger", rows[0].name,
		                    "benefit_kind", "Incentive", update_modified=False)

		from_date, to_date = self.window()
		preview = claim_service.claimable(self.distributor.name, from_date, to_date)
		self.assertEqual(preview["line_count"], len(rows) - 1,
		                 "an incentive row must not be offered for claiming")

		# And it is refused if somebody attaches it by hand on the Desk form, rather than merely
		# left out of the preview the portal reads.
		doc = frappe.new_doc("FieldMate Claim")
		doc.claim_date = today()
		doc.distributor = self.distributor.name
		doc.company = frappe.db.get_value("FieldMate Scheme Ledger", rows[0].name, "company")
		doc.from_date, doc.to_date = from_date, to_date
		doc.append("items", {"scheme_ledger": rows[0].name})
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_the_same_benefit_cannot_be_claimed_twice(self):
		"""The failure this document exists to prevent."""
		self.accrued()
		from_date, to_date = self.window()

		first = claim_service.build(self.distributor.name, from_date, to_date)
		self.track("FieldMate Claim", first)
		claim_service.submit_claim(first)

		with self.assertRaises(frappe.ValidationError):
			claim_service.build(self.distributor.name, from_date, to_date)

	def test_cancelling_a_claim_puts_the_benefits_back(self):
		"""A depot that fixes whatever was wrong and claims again must find the window full."""
		_, rows = self.accrued()
		from_date, to_date = self.window()

		name = claim_service.build(self.distributor.name, from_date, to_date)
		self.track("FieldMate Claim", name)
		claim_service.submit_claim(name)
		self.assertEqual(
			frappe.db.get_value("FieldMate Scheme Ledger", rows[0].name, "status"), "Claimed")

		doc = frappe.get_doc("FieldMate Claim", name)
		doc.flags.ignore_permissions = True
		doc.cancel()

		self.assertEqual(
			frappe.db.get_value("FieldMate Scheme Ledger", rows[0].name, "status"), "Accrued")
		self.assertIsNone(
			frappe.db.get_value("FieldMate Scheme Ledger", rows[0].name, "claim"))

	def test_a_rejected_claim_puts_the_benefits_back_too(self):
		_, rows = self.accrued()
		from_date, to_date = self.window()
		name = claim_service.build(self.distributor.name, from_date, to_date)
		self.track("FieldMate Claim", name)
		claim_service.submit_claim(name)

		claim_service.approve(name, "Rejected", remarks="Photo proof missing at three shops.")

		self.assertEqual(
			frappe.db.get_value("FieldMate Claim", name, "claim_status"), "Rejected")
		self.assertEqual(
			frappe.db.get_value("FieldMate Scheme Ledger", rows[0].name, "status"), "Accrued",
			"a rejected claim that keeps its rows deletes the depot's entitlement",
		)

	def test_a_rejection_needs_a_reason(self):
		_, _rows = self.accrued()
		from_date, to_date = self.window()
		name = claim_service.build(self.distributor.name, from_date, to_date)
		self.track("FieldMate Claim", name)
		claim_service.submit_claim(name)

		with self.assertRaises(frappe.ValidationError):
			claim_service.approve(name, "Rejected")

	def test_more_cannot_be_approved_than_was_claimed(self):
		_, _rows = self.accrued()
		from_date, to_date = self.window()
		name = claim_service.build(self.distributor.name, from_date, to_date)
		self.track("FieldMate Claim", name)
		claim_service.submit_claim(name)
		claimed = flt(frappe.db.get_value("FieldMate Claim", name, "claimed_amount"))

		with self.assertRaises(frappe.ValidationError):
			claim_service.approve(name, "Approved", approved_amount=claimed + 100, settle=False)

	def test_a_depot_cannot_claim_another_depots_accruals(self):
		_, rows = self.accrued()
		other = self.second_depot()
		from_date, to_date = self.window()

		doc = frappe.new_doc("FieldMate Claim")
		doc.claim_date = today()
		doc.distributor = other.name
		doc.company = frappe.db.get_value("FieldMate Scheme Ledger", rows[0].name, "company")
		doc.from_date, doc.to_date = from_date, to_date
		doc.append("items", {"scheme_ledger": rows[0].name})
		doc.flags.ignore_permissions = True

		with self.assertRaises(frappe.ValidationError):
			doc.insert()


# --------------------------------------------------------------------------------------
# criterion 3 — approval raises a credit note, on the right account and cost centre
# --------------------------------------------------------------------------------------


class TestSettlement(ClaimFixture):
	def setUp(self):
		super().setUp()
		self.company = frappe.db.get_value("Company", {}, "name")
		self.expense = self.an_account()
		self.cost_center = frappe.db.get_value("Company", self.company, "cost_center")
		self.settlement_item = self.make_item(item_name="Scheme Claim Settlement")
		self.apply_settings(
			claim_settlement_item=self.settlement_item,
			claim_expense_account=self.expense,
			claim_cost_center=self.cost_center,
		)

	def tearDown(self):
		"""Let go of the settlement item before the item itself is deleted.

		FieldMate Settings is a Single, so it outlives this class's rollback while the Item does
		not. Leaving a dead Link there does not break a test here - it breaks every later test on
		the bench that saves the Single at all, with `Could not find Settlement Item` and nothing
		pointing back at this file.
		"""
		try:
			self.apply_settings(claim_settlement_item=None, claim_expense_account=None,
			                    claim_cost_center=None)
			frappe.db.commit()
		except Exception:
			pass
		super().tearDown()

	def an_account(self):
		"""Any real income account on this bench. The test is about which one was used, not
		about the chart of accounts on the site it happens to run on."""
		return frappe.db.get_value(
			"Account", {"company": self.company, "root_type": "Income", "is_group": 0}, "name")

	def submitted_claim(self):
		self.accrued()
		from_date, to_date = self.window()
		name = claim_service.build(self.distributor.name, from_date, to_date)
		self.track("FieldMate Claim", name)
		claim_service.submit_claim(name)
		return name

	def test_the_settlement_settings_are_actually_readable(self):
		"""`settings.get()` copies a named list of keys, not every field on the DocType.

		Phase 9 shipped with the three claim settings missing from that list, so the form showed
		them, the database held them, and `settings.value()` returned None for all three - and
		the only symptom was a claim refusing to settle with a message about a field that was
		plainly set. Asserting the round trip is cheaper than reading that message again.
		"""
		from fieldmate.services import settings as settings_service

		self.assertEqual(settings_service.value("claim_settlement_item"), self.settlement_item)
		self.assertEqual(settings_service.value("claim_expense_account"), self.expense)
		self.assertEqual(settings_service.value("claim_cost_center"), self.cost_center)

	def test_approval_raises_one_credit_note(self):
		name = self.submitted_claim()
		result = claim_service.approve(name, "Approved")

		self.assertEqual(result["claim_status"], "Settled")
		self.assertTrue(result["credit_note"])
		invoice = frappe.get_doc("Sales Invoice", result["credit_note"])
		self.track("Sales Invoice", invoice.name)

		self.assertEqual(invoice.is_return, 1)
		self.assertEqual(invoice.customer, self.distributor.name)
		self.assertEqual(invoice.docstatus, 1)

	def test_the_credit_note_carries_the_configured_account_and_cost_centre(self):
		"""Gate 9 criterion 3. A claim booked as negative sales on the default income account is
		usable and is also the number a brand manager reads as a shortfall."""
		name = self.submitted_claim()
		result = claim_service.approve(name, "Approved")
		invoice = frappe.get_doc("Sales Invoice", result["credit_note"])
		self.track("Sales Invoice", invoice.name)

		self.assertEqual(len(invoice.items), 1, "a claim is one settlement, not a return of SKUs")
		self.assertEqual(invoice.items[0].item_code, self.settlement_item)
		self.assertEqual(invoice.items[0].income_account, self.expense)
		self.assertEqual(invoice.items[0].cost_center, self.cost_center)

	def test_the_credit_note_is_for_the_approved_figure_not_the_claimed_one(self):
		name = self.submitted_claim()
		claimed = flt(frappe.db.get_value("FieldMate Claim", name, "claimed_amount"))
		agreed = round(claimed / 2, 2)

		result = claim_service.approve(name, "Approved", approved_amount=agreed)
		invoice = frappe.get_doc("Sales Invoice", result["credit_note"])
		self.track("Sales Invoice", invoice.name)

		# Negative, because a return invoice is negative. Asserted as the signed figure rather
		# than through abs(), so that a note which somehow came out positive - money billed to
		# the distributor instead of credited to him - fails here rather than reading as correct.
		self.assertAlmostEqual(flt(invoice.grand_total), -agreed, places=2)

	def test_the_credit_note_moves_no_stock(self):
		"""Same rule as every other secondary document in the app: the stock was the
		distributor's from primary billing onward (ADR-023, ADR-024)."""
		name = self.submitted_claim()
		before = frappe.db.count("Stock Ledger Entry")
		result = claim_service.approve(name, "Approved")
		self.track("Sales Invoice", result["credit_note"])

		self.assertEqual(frappe.db.count("Stock Ledger Entry"), before)

	def test_approving_twice_credits_once(self):
		"""The idempotency key, and the reason the adapter refuses to post without one."""
		name = self.submitted_claim()
		first = claim_service.approve(name, "Approved")
		self.track("Sales Invoice", first["credit_note"])
		second = claim_service.settle_claim(name)

		self.assertEqual(first["credit_note"], second["credit_note"])
		self.assertEqual(
			frappe.db.count("Sales Invoice",
			                {"fm_source_key": f"CLAIM:{name}", "docstatus": ["<", 2]}),
			1,
		)

	def test_settling_closes_the_accruals(self):
		name = self.submitted_claim()
		result = claim_service.approve(name, "Approved")
		self.track("Sales Invoice", result["credit_note"])

		for row in frappe.get_doc("FieldMate Claim", name).items:
			ledger = frappe.db.get_value(
				"FieldMate Scheme Ledger", row.scheme_ledger, ["status", "settled_on"],
				as_dict=True)
			self.assertEqual(ledger.status, "Settled")
			self.assertTrue(ledger.settled_on, "a claim marked settled with no date is disputed")

	def test_reversing_releases_the_link_before_cancelling(self):
		"""Frappe checks back-links before on_cancel, so the note has to be let go of first.
		This is the third time the same trap has bitten this app; it is a test now."""
		name = self.submitted_claim()
		result = claim_service.approve(name, "Approved")
		note = result["credit_note"]
		self.track("Sales Invoice", note)

		reversed_claim = claim_service.reverse(name)

		self.assertIsNone(reversed_claim["credit_note"])
		self.assertEqual(reversed_claim["claim_status"], "Approved")
		self.assertEqual(frappe.db.get_value("Sales Invoice", note, "docstatus"), 2)

	def test_a_settled_claim_cannot_be_cancelled_underneath_its_note(self):
		name = self.submitted_claim()
		result = claim_service.approve(name, "Approved")
		self.track("Sales Invoice", result["credit_note"])

		doc = frappe.get_doc("FieldMate Claim", name)
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()


class TestADepotSendsItsOwnSalesFile(PortalFixture):
	"""Phase 1, step 7c. The reader, the column mapping and the bad-row tolerance have existed
	since Phase 5 and were reachable only from Desk - so a depot emailed a file and somebody at
	this end imported it, which is a step that gets skipped in a busy week."""

	def csv(self, *rows, header="Date,Item Code,Qty,Amount,Shop Name"):
		return "\n".join([header, *rows])

	def upload(self, content, **extra):
		payload = {"from_date": "2026-09-01", "to_date": "2026-09-30",
		           "content": content, "file_name": "sales.csv"}
		payload.update(extra)
		answer = self.as_depot(lambda: portal_api.upload_secondary_sales(**payload))
		# The envelope, not just its data. `@endpoint` turns a refusal into `{ok: False, ...}`
		# rather than raising, so indexing straight into `data` reports a KeyError and hides the
		# message that says what actually went wrong.
		self.assertTrue(answer.get("ok"), answer.get("message") or answer)
		return answer["data"]

	def test_a_depot_can_send_its_own_file(self):
		result = self.upload(self.csv(f"2026-09-05,{self.item},12,1464,Sharma Kirana"))
		self.track("FieldMate Secondary Sales", result["name"])
		self.assertEqual(result["imported"], 1)

	def test_the_sales_land_against_the_depot_that_sent_them(self):
		"""The distributor is taken from the session and never from the payload. A depot sending
		a file for somebody else's sales is the one thing this endpoint must not allow, and the
		only way to be sure is not to accept the name at all."""
		result = self.upload(self.csv(f"2026-09-05,{self.item},12,1464,Sharma Kirana"))
		self.track("FieldMate Secondary Sales", result["name"])
		self.assertEqual(
			frappe.db.get_value("FieldMate Secondary Sales", result["name"], "distributor"),
			self.distributor.name)

	def test_the_endpoint_will_not_even_accept_another_depots_name(self):
		"""A depot sending a file for somebody else's sales is the one thing this must not allow,
		and the only way to be sure is not to take the name at all. Asserted on the signature
		rather than on behaviour, because a parameter that exists is a parameter somebody will
		eventually pass through from a form."""
		import inspect
		params = inspect.signature(portal_api.upload_secondary_sales).parameters
		self.assertNotIn("distributor", params)
		self.assertNotIn("customer", params)

	def test_a_bad_row_does_not_cost_the_good_ones(self):
		"""Gate 5 criterion 1, now reachable from the portal. A distributor who has to fix and
		resend a whole file stops sending files."""
		result = self.upload(self.csv(
			f"2026-09-05,{self.item},12,1464,Sharma Kirana",
			"2026-09-06,NOPE,3,99,Some Shop",
			f"2026-09-07,{self.item},4,488,Raja Stores",
		))
		self.track("FieldMate Secondary Sales", result["name"])
		self.assertEqual(result["imported"], 2)
		self.assertEqual(len(result["rejected"]), 1)
		self.assertIn("NOPE", result["rejected"][0]["reason"])

	def test_a_login_without_the_right_is_refused(self):
		"""Refused as an envelope, not as a raise: `@endpoint` turns every refusal into one so a
		depot's browser gets a message rather than a stack trace."""
		row = frappe.get_doc("FieldMate Portal User", self.depot.name)
		row.can_upload_sales = 0
		row.save(ignore_permissions=True)

		answer = self.as_depot(lambda: portal_api.upload_secondary_sales(
			from_date="2026-09-01", to_date="2026-09-30",
			content=self.csv(f"2026-09-05,{self.item},1,10,Sharma Kirana")))

		self.assertFalse(answer["ok"])
		self.assertIn("cannot send sales files", answer["message"])
		self.assertIn("your depot", answer["message"],
		              "the message names who can turn it on")

	def test_the_template_says_which_headers_are_understood(self):
		"""So a depot can see its own export is probably already accepted, rather than being
		handed a format to convert to."""
		answer = self.as_depot(portal_api.secondary_sales_template)["data"]
		self.assertIn("invoice_no", answer["columns"])
		self.assertIn("bill no", answer["accepted_headers"]["invoice_no"])
		self.assertEqual(sorted(answer["required"]), ["date", "item_code", "qty"])

	def test_nothing_is_posted_for_it(self):
		"""ADR-023. These are the distributor's sales; FieldMate records them, never bills them."""
		before = frappe.db.count("GL Entry"), frappe.db.count("Sales Invoice")
		result = self.upload(self.csv(f"2026-09-05,{self.item},12,1464,Sharma Kirana"))
		self.track("FieldMate Secondary Sales", result["name"])
		self.assertEqual((frappe.db.count("GL Entry"), frappe.db.count("Sales Invoice")), before)

	def test_the_page_builds_its_own_context(self):
		"""A smoke test, because a broken context or a bad template reference shows up only in a
		browser - and the browser belongs to a distributor, not to us."""
		from fieldmate.www.distributor import sales as sales_page

		context = self.as_depot(lambda: sales_page.get_context(frappe._dict()))
		self.assertEqual(context.distributor, self.distributor.name)
		self.assertTrue(context.can_upload)
		self.assertIn("invoice_no", context.template["accepted_headers"])
		self.assertIsInstance(context.recent, list)

	def test_the_page_lists_only_this_depots_files(self):
		other = self.second_depot()
		mine = self.upload(self.csv(f"2026-09-05,{self.item},3,360,Sharma Kirana"))
		self.track("FieldMate Secondary Sales", mine["name"])

		theirs = frappe.get_doc({
			"doctype": "FieldMate Secondary Sales", "distributor": other.name,
			"from_date": "2026-09-01", "to_date": "2026-09-30",
			"items": [{"sale_date": "2026-09-05", "item_code": self.item, "qty": 1}],
		})
		theirs.flags.ignore_permissions = True
		theirs.insert()
		theirs.submit()
		self.track("FieldMate Secondary Sales", theirs.name)

		from fieldmate.www.distributor import sales as sales_page
		names = {r.name for r in self.as_depot(
			lambda: sales_page.get_context(frappe._dict())).recent}
		self.assertIn(mine["name"], names)
		self.assertNotIn(theirs.name, names, "one depot must not see another's book")
