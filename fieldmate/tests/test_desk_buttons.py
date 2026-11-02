"""The Sales Head's buttons on Target Plan, Incentive Payout and Claim - and who may press them.

Every one of these used to be a call typed into the browser console. The buttons call small
whitelisted functions on each controller, held to the DocType's own right: the Sales Head (and
Admin) may, an Area Manager - who has read and nothing else on these three - may not.

The same rule now holds on `api/target.py`, which checked a list of manager roles instead and so
let any Area Manager approve any rep's payout, company-wide, from outside Desk.
"""

import frappe
from frappe.utils import add_days, today

from fieldmate.api import target as target_api
from fieldmate.fieldmate.doctype.fieldmate_claim import fieldmate_claim as claim_buttons
from fieldmate.fieldmate.doctype.fieldmate_incentive_payout import (
	fieldmate_incentive_payout as payout_buttons,
)
from fieldmate.fieldmate.doctype.fieldmate_target_plan import fieldmate_target_plan as plan_buttons
from fieldmate.services import claim as claim_service
from fieldmate.services import incentive as incentive_service
from fieldmate.services import target as target_service
from fieldmate.tests.test_portal import ClaimFixture
from fieldmate.tests.test_target import TargetFixture, TestPayouts


def as_user(user, fn, *args, **kwargs):
	frappe.set_user(user)
	try:
		return fn(*args, **kwargs)
	finally:
		frappe.set_user("Administrator")


class PayoutFixture(TargetFixture):
	def setUp(self):
		super().setUp()
		self.person = self.make_sales_person("SOLO", parent=self.root_person, is_group=0)
		frappe.db.set_value("FieldMate Field User", self.rep.name, "sales_person", self.person)
		self.head = self.make_user(role="FieldMate Sales Head")
		self.area = self.make_user(role="FieldMate Area Manager")

	def submitted_payout(self):
		self.book(qty=20)
		self.plan = self.plan_for(self.person, lines=[{"target_type": "Value", "target_value": 1000}])
		target_service.compute(self.plan.name)
		TestPayouts.scheme(self)
		name = incentive_service.compute_for(self.rep.name, self.plan.name)[0]["payout"]
		doc = frappe.get_doc("FieldMate Incentive Payout", name)
		doc.flags.ignore_permissions = True
		doc.submit()
		return name


class TestThePayoutButtons(PayoutFixture):
	def test_the_sales_head_approves_and_records_the_payment(self):
		name = self.submitted_payout()
		self.assertEqual(as_user(self.head, payout_buttons.decide, name, "Approved")["payout_status"],
		                 "Approved")
		paid = as_user(self.head, payout_buttons.mark_paid, name, "PAYROLL-NOV-26")
		self.assertEqual(paid["payout_status"], "Paid")

	def test_an_area_manager_cannot_approve_from_the_form(self):
		name = self.submitted_payout()
		with self.assertRaises(frappe.PermissionError):
			as_user(self.area, payout_buttons.decide, name, "Approved")

	def test_nor_through_the_api_which_used_to_let_them(self):
		name = self.submitted_payout()
		answer = as_user(self.area, target_api.decide_payout, name, "Approved")
		self.assertFalse(answer["ok"])
		self.assertEqual(frappe.db.get_value("FieldMate Incentive Payout", name, "payout_status"),
		                 "Pending Approval")

	def test_nor_record_it_paid_through_the_api(self):
		name = self.submitted_payout()
		as_user(self.head, payout_buttons.decide, name, "Approved")
		answer = as_user(self.area, target_api.mark_payout_paid, name, "MY-OWN-REF")
		self.assertFalse(answer["ok"])
		self.assertEqual(frappe.db.get_value("FieldMate Incentive Payout", name, "payout_status"),
		                 "Approved")


class TestThePlanButtons(PayoutFixture):
	def test_the_sales_head_cascades_and_an_area_manager_cannot(self):
		plan = self.plan_for(self.person, lines=[{"target_type": "Value", "target_value": 1000}])
		self.assertTrue(as_user(self.head, plan_buttons.cascade_plan, plan.name)["leaf"])
		with self.assertRaises(frappe.PermissionError):
			as_user(self.area, plan_buttons.cascade_plan, plan.name)
		self.assertFalse(as_user(self.area, target_api.cascade, plan.name)["ok"])

	def test_anybody_who_can_read_the_plan_may_check_its_totals(self):
		plan = self.plan_for(self.person, lines=[{"target_type": "Value", "target_value": 1000}])
		self.assertTrue(as_user(self.area, plan_buttons.check_totals, plan.name)["matches"])

	def test_measure_now_writes_the_achievement(self):
		plan = self.plan_for(self.person, lines=[{"target_type": "Value", "target_value": 1000}])
		self.assertEqual(as_user(self.head, plan_buttons.measure_now, plan.name)["measured"], 1)
		self.assertTrue(frappe.db.exists("FieldMate Achievement", {"target_plan": plan.name}))

	def test_payouts_are_previewed_before_anything_is_written(self):
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[{"target_type": "Value", "target_value": 1000}])
		target_service.compute(plan.name)
		TestPayouts.scheme(self)
		# Counted before and after rather than asserted absent: a payout another class committed
		# can outlive its plan, and a new plan reuses the name.
		def drafts():
			return frappe.db.count("FieldMate Incentive Payout",
			                       {"target_plan": plan.name, "field_user": self.rep.name,
			                        "docstatus": 0})

		before = drafts()
		preview = as_user(self.head, plan_buttons.compute_payouts, plan.name, 1)
		self.assertGreaterEqual(preview["payouts"], 1)
		self.assertEqual(drafts(), before)

		as_user(self.head, plan_buttons.compute_payouts, plan.name, 0)
		self.assertGreaterEqual(drafts(), 1)

	def test_an_area_manager_cannot_work_out_payouts(self):
		plan = self.plan_for(self.person, lines=[{"target_type": "Value", "target_value": 1000}])
		with self.assertRaises(frappe.PermissionError):
			as_user(self.area, plan_buttons.compute_payouts, plan.name, 1)
		answer = as_user(self.area, target_api.compute_payouts,
		                 str(add_days(today(), -30)), today(), 1)
		self.assertFalse(answer["ok"])


class TestTheClaimButtons(ClaimFixture):
	def setUp(self):
		super().setUp()
		self.head = self.make_user(role="FieldMate Sales Head")
		self.area = self.make_user(role="FieldMate Area Manager")

	def submitted_claim(self):
		self.accrued()
		from_date, to_date = self.window()
		name = claim_service.build(self.distributor.name, from_date, to_date)
		self.track("FieldMate Claim", name)
		claim_service.submit_claim(name)
		return name

	def test_the_sales_head_rejects_with_a_reason(self):
		name = self.submitted_claim()
		result = as_user(self.head, claim_buttons.decide, name, "Rejected",
		                 remarks="Two of these shops are not ours")
		self.assertEqual(result["claim_status"], "Rejected")

	def test_an_area_manager_cannot_decide_a_claim(self):
		name = self.submitted_claim()
		with self.assertRaises(frappe.PermissionError):
			as_user(self.area, claim_buttons.decide, name, "Approved", settle=0)
		self.assertEqual(frappe.db.get_value("FieldMate Claim", name, "claim_status"),
		                 "Pending Approval")
