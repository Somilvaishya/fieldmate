"""Which orders stop for a manager, and who that manager is.

There was no test here at all, and that is how three fields on `FieldMate Order Approval Rule`
came to do nothing. Fifty-two order tests never created a rule, so the picker was only ever run
with no rules on the site - where it correctly returns None, and where a trigger it does not read
and an approver it does not consult look exactly like a trigger and an approver that work.

What was wrong, each with a test below:

  * the **discount ceiling** was never fetched by the query that picks a rule, so a rule whose
    only trigger was the ceiling passed validation and then matched nothing, ever;
  * the **named approver** was validated on save and read by nothing, so a rule saying large
    southern orders go to the RM neither reached the RM nor let them decide;
  * **territory** was compared by name equality although the field's own description promises the
    whole branch beneath it, so a rule on North missed every shop in North / Delhi.

Most of these go at `pick_approval_rule` directly rather than through a booked order. The picker
is the unit that changed, a rule has to be matched against a shop and a set of totals and nothing
else, and routing a priced cart through four services to vary one threshold tests the four
services. The permission and notification tests do go the whole way, because what they assert is
what happens to a real order after it stops.
"""

import frappe

from fieldmate.services import order as order_service
from fieldmate.tests.test_order import OrderFixture


class ApprovalRuleFixture(OrderFixture):
	def make_rule(self, **kwargs):
		"""An active rule, with an approver unless the test is about the approver."""
		data = {
			"doctype": "FieldMate Order Approval Rule",
			"rule_name": self.uid("RULE"),
			"is_active": 1,
			"priority": 10,
			"approver_role": "FieldMate Area Manager",
		}
		data.update(kwargs)
		doc = frappe.get_doc(data).insert(ignore_permissions=True)
		self.track("FieldMate Order Approval Rule", doc.name)
		return doc

	def an_order_worth(self, net, gross=None, discount=0, credit_status="Within Limit",
	                   outlet=None):
		"""The fields `pick_approval_rule` reads, and nothing else.

		A `_dict` rather than a saved document on purpose: the picker's whole job is to weigh a
		shop and a set of totals against the rules on the site, and a fixture that priced a cart
		to vary one threshold would be testing the pricing.
		"""
		return frappe._dict({
			"outlet": outlet or self.outlet.name,
			"net_total": net,
			"gross_total": gross if gross is not None else net,
			"discount_total": discount,
			"credit_status": credit_status,
		})


# --------------------------------------------------------------------------------------
# The discount ceiling, which used to be decoration
# --------------------------------------------------------------------------------------


class TestTheDiscountCeiling(ApprovalRuleFixture):
	def test_a_rule_whose_only_trigger_is_the_discount_ceiling_catches_an_order_over_it(self):
		"""The bug this file was written for.

		`check_discount_percent` and `max_discount_percent` were never in the picker's field list,
		so this rule matched nothing however much was given away. Schemes stack, and two
		legitimate offers on one cart can land well past what anybody intended - which is the
		case the field exists for and the case that was sailing through unread.
		"""
		rule = self.make_rule(check_discount_percent=1, max_discount_percent=10)

		# 1500 off a gross of 10000 is 15 per cent, which is over the ceiling of 10.
		over = self.an_order_worth(net=8500, gross=10000, discount=1500)
		self.assertEqual(order_service.pick_approval_rule(over), rule.name)

	def test_an_order_under_the_ceiling_is_left_alone(self):
		self.make_rule(check_discount_percent=1, max_discount_percent=10)

		# 500 off 10000 is 5 per cent.
		under = self.an_order_worth(net=9500, gross=10000, discount=500)
		self.assertIsNone(order_service.pick_approval_rule(under))

	def test_the_ceiling_is_a_share_of_gross_not_a_rupee_figure(self):
		"""Two orders giving away the same rupees, one small and one large.

		A ceiling read as an amount would catch both or neither. As a share, 1500 off a 10000
		cart is worth a manager's attention and the same 1500 off a 100000 cart is not.
		"""
		self.make_rule(check_discount_percent=1, max_discount_percent=10)

		small = self.an_order_worth(net=8500, gross=10000, discount=1500)
		large = self.an_order_worth(net=98500, gross=100000, discount=1500)

		self.assertIsNotNone(order_service.pick_approval_rule(small))
		self.assertIsNone(order_service.pick_approval_rule(large))

	def test_a_cart_with_no_gross_divides_by_nothing(self):
		"""An empty or fully free cart has no share to compute, and must not raise."""
		self.make_rule(check_discount_percent=1, max_discount_percent=10)
		self.assertIsNone(
			order_service.pick_approval_rule(self.an_order_worth(net=0, gross=0, discount=0)))


# --------------------------------------------------------------------------------------
# Territory, which the field's own description has always described correctly
# --------------------------------------------------------------------------------------


class TestTerritoryIsATree(ApprovalRuleFixture):
	def setUp(self):
		super().setUp()
		# A shop one level below the rep's own node. The rule goes on the parent, which is how a
		# planner scopes anything: to a region, not to the single leaf a shop happens to sit on.
		self.child = self.make_territory(parent=self.rep.territory)
		self.shop_below = self.make_outlet(territory=self.child, approval_status="Approved")

	def test_a_rule_on_a_parent_territory_catches_a_shop_in_a_child(self):
		"""Name equality stood here and silently excluded every shop off the exact node.

		Worse than a plain miss, because Frappe fills an empty Link from the session default and
		for a tree master that default is the root - so a rule that looks unscoped is very often
		pinned to whatever node the person saving it happened to carry.
		"""
		rule = self.make_rule(territory=self.rep.territory,
		                      check_order_value=1, min_order_value=1000)

		order = self.an_order_worth(net=5000, outlet=self.shop_below.name)
		self.assertEqual(order_service.pick_approval_rule(order), rule.name)

	def test_a_rule_on_a_sibling_territory_catches_nothing(self):
		"""The other direction, or "matches the tree" would just mean "matches everything"."""
		elsewhere = self.make_territory()
		self.make_rule(territory=elsewhere, check_order_value=1, min_order_value=1000)

		order = self.an_order_worth(net=5000, outlet=self.shop_below.name)
		self.assertIsNone(order_service.pick_approval_rule(order))

	def test_a_rule_with_no_territory_still_means_everywhere(self):
		rule = self.make_rule(check_order_value=1, min_order_value=1000)
		order = self.an_order_worth(net=5000, outlet=self.shop_below.name)
		self.assertEqual(order_service.pick_approval_rule(order), rule.name)


# --------------------------------------------------------------------------------------
# Which rule claims the order
# --------------------------------------------------------------------------------------


class TestWhichRuleClaimsIt(ApprovalRuleFixture):
	def test_the_lowest_priority_number_wins(self):
		"""Ascending, the same way the scheme engine's priority ascends.

		Two conventions in one app is how somebody eventually reads one of them backwards.
		"""
		first = self.make_rule(priority=5, check_order_value=1, min_order_value=1000)
		self.make_rule(priority=50, check_order_value=1, min_order_value=1000)

		self.assertEqual(order_service.pick_approval_rule(self.an_order_worth(net=5000)),
		                 first.name)

	def test_an_inactive_rule_claims_nothing(self):
		self.make_rule(is_active=0, check_order_value=1, min_order_value=1000)
		self.assertIsNone(order_service.pick_approval_rule(self.an_order_worth(net=5000)))

	def test_a_credit_rule_fires_only_on_a_breach(self):
		rule = self.make_rule(on_credit_breach=1)

		within = self.an_order_worth(net=5000, credit_status="Within Limit")
		breached = self.an_order_worth(net=5000, credit_status="Breach")

		self.assertIsNone(order_service.pick_approval_rule(within))
		self.assertEqual(order_service.pick_approval_rule(breached), rule.name)


# --------------------------------------------------------------------------------------
# Who may decide, and who gets told
# --------------------------------------------------------------------------------------


class TestWhoMayDecide(ApprovalRuleFixture):
	def setUp(self):
		super().setUp()
		# The cart is 20 at 100, so 2000 net. A threshold under that stops every order this
		# fixture books, which is what these tests need.
		self.rule = self.make_rule(check_order_value=1, min_order_value=1000,
		                           approver_user=self.make_user(role=None))

	def booked_and_waiting(self):
		result = self.book()
		self.assertEqual(result["order_status"], "Pending Approval",
		                 "the rule has to stop the order before any of this means anything")
		return result["name"]

	def test_an_order_over_the_threshold_waits(self):
		name = self.booked_and_waiting()
		self.assertEqual(frappe.db.get_value("FieldMate Order", name, "approval_rule"),
		                 self.rule.name, "the order has to record which rule stopped it")

	def test_the_user_the_rule_names_may_decide(self):
		"""The field was read by nothing, so naming somebody granted them nothing.

		They hold no FieldMate role and manage nobody. Before this they were refused, and the
		rule that pointed at them read as enforced in Desk while routing to a different set of
		people entirely.
		"""
		name = self.booked_and_waiting()
		order_service.approve(name, "Approved", approver=self.rule.approver_user)

		self.assertEqual(frappe.db.get_value("FieldMate Order", name, "approval_status"),
		                 "Approved")

	def test_a_holder_of_the_role_the_rule_names_may_decide(self):
		rule = self.make_rule(priority=1, check_order_value=1, min_order_value=1000,
		                      approver_role="FieldMate Regional Manager")
		covering = self.make_user(role="FieldMate Regional Manager")

		name = self.booked_and_waiting()
		self.assertEqual(frappe.db.get_value("FieldMate Order", name, "approval_rule"), rule.name)

		order_service.approve(name, "Approved", approver=covering)
		self.assertEqual(frappe.db.get_value("FieldMate Order", name, "approval_status"),
		                 "Approved")

	def test_a_stranger_still_cannot_decide(self):
		"""Naming an approver widens the gate by one person; it does not open it.

		This is the whole of what the credit hold is for, and `assert_may_approve` was written
		because any signed-in session used to get through.
		"""
		stranger = self.make_user(role=None)
		name = self.booked_and_waiting()

		with self.assertRaises(frappe.PermissionError):
			order_service.approve(name, "Approved", approver=stranger)

	def test_the_named_approver_is_told(self):
		"""A queue nobody is pointed at is how an order sits for a week.

		A Notification Log rather than an email, the way `alerts._notify` and the cockpit already
		do it: an email nobody configured goes nowhere and reports success.
		"""
		name = self.booked_and_waiting()

		told = frappe.get_all("Notification Log",
		                      filters={"document_type": "FieldMate Order", "document_name": name},
		                      pluck="for_user")
		self.assertIn(self.rule.approver_user, told)

	def test_an_order_nobody_stopped_tells_nobody(self):
		"""The courtesy follows the hold. Without one there is nothing to be told about."""
		frappe.db.set_value("FieldMate Order Approval Rule", self.rule.name, "is_active", 0)
		frappe.clear_document_cache("FieldMate Order Approval Rule", self.rule.name)

		result = self.book()
		self.assertEqual(result["order_status"], "Sent To Distributor")
		self.assertFalse(frappe.get_all(
			"Notification Log",
			filters={"document_type": "FieldMate Order", "document_name": result["name"]}))


# --------------------------------------------------------------------------------------
# What a rule may not say
# --------------------------------------------------------------------------------------


class TestWhatARuleMayNotSay(ApprovalRuleFixture):
	def test_a_field_rep_cannot_be_named_as_the_approver(self):
		"""Naming a role grants its holders the decision, and this one books the orders.

		A rep releasing another rep's breached order is the exact thing the credit hold exists to
		stop. Field Rep is also the one role on the matrix with no Desk access, so somebody
		reaching for it in this field has almost certainly picked the wrong row of a long list.
		"""
		with self.assertRaises(frappe.ValidationError):
			self.make_rule(approver_role="FieldMate Field Rep", check_order_value=1,
			               min_order_value=1000)

	def test_a_rule_with_no_trigger_is_refused(self):
		"""It would match every order in its scope, and a queue holding everything gets cleared
		without being read - taking the one genuine breach in it along with the rest."""
		with self.assertRaises(frappe.ValidationError):
			self.make_rule()

	def test_a_switched_on_threshold_of_zero_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_rule(check_order_value=1, min_order_value=0)

	def test_a_switched_on_ceiling_of_zero_is_refused(self):
		"""Every order carrying any scheme at all would need approval."""
		with self.assertRaises(frappe.ValidationError):
			self.make_rule(check_discount_percent=1, max_discount_percent=0)

	def test_a_rule_that_stops_an_order_and_names_nobody_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_rule(approver_role=None, approver_user=None,
			               check_order_value=1, min_order_value=1000)
