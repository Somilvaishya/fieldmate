"""Targets, achievement and incentive — the arithmetic, and the one thing that must not move.

The invariant this phase turns on: **the leaves add up to the root, exactly.** Not nearly, not
to two decimal places on a good day. A cascade in floating point gives three children who sum to
9,99,999.99 against a root of 10,00,000, and nobody sees that until the end of the month when a
regional manager's report is a rupee short and nobody can say which rep is carrying it.

Five of the six target types are quantities and are split. The sixth is a rate, and a rate does
not divide - a root asking 4.5 lines a call means every rep is asked for 4.5. Both behaviours
are asserted, separately, because one boolean cannot carry them.
"""

import frappe
from frappe.utils import add_days, flt, today

from fieldmate.services import incentive as incentive_service
from fieldmate.services import target as target_service
from fieldmate.tests.base import FieldMateTestCase
from fieldmate.tests.test_order import OrderFixture


class TargetFixture(OrderFixture):
	"""A Sales Person tree with reps hanging off it, and a plan at the top."""

	def setUp(self):
		super().setUp()
		self.root_person = self.make_sales_person("ROOT")
		self.company = frappe.db.get_value("Company", {}, "name")

	def tearDown(self):
		frappe.set_user("Administrator")
		for dt in ("FieldMate Incentive Payout", "FieldMate Achievement",
		           "FieldMate Target Plan", "FieldMate Incentive Scheme"):
			for name in frappe.get_all(dt, pluck="name"):
				try:
					doc = frappe.get_doc(dt, name)
					if doc.meta.is_submittable and doc.docstatus == 1:
						doc.flags.ignore_permissions = True
						doc.cancel()
					frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
				except Exception:
					pass
		frappe.db.commit()
		super().tearDown()

	def make_sales_person(self, label, parent=None, is_group=1):
		doc = frappe.get_doc({
			"doctype": "Sales Person",
			"sales_person_name": self.uid(f"T7-{label}"),
			"parent_sales_person": parent,
			"is_group": is_group,
			"enabled": 1,
		}).insert(ignore_permissions=True)
		self.track("Sales Person", doc.name)
		return doc.name

	def make_rep_under(self, parent, outlets=0):
		"""A rep on the tree, with a territory of their own and some shops in it.

		Outlet count is the default cascade weight, so a fixture that wants an uneven split has
		to give the reps uneven shops - which is also what a real site looks like.
		"""
		person = self.make_sales_person("REP", parent=parent, is_group=0)
		territory = self.make_territory()
		rep = self.make_field_user(territory=territory)
		frappe.db.set_value("FieldMate Field User", rep.name, "sales_person", person)
		for _ in range(outlets):
			self.make_outlet(territory=territory, approval_status="Approved")
		return frappe._dict(person=person, rep=rep, territory=territory)

	def plan_for(self, person, lines=None, basis="Equal", **extra):
		data = {
			"doctype": "FieldMate Target Plan",
			"plan_name": self.uid("T7-PLAN"),
			"company": self.company,
			"from_date": today(),
			"to_date": add_days(today(), 29),
			"sales_person": person,
			"cascade_basis": basis,
			"lines": lines or [{"target_type": "Value", "target_value": 1000000}],
		}
		data.update(extra)
		doc = frappe.get_doc(data)
		doc.flags.ignore_permissions = True
		doc.insert()
		self.track("FieldMate Target Plan", doc.name)
		doc.submit()
		return doc


# --------------------------------------------------------------------------------------
# the split, on its own
# --------------------------------------------------------------------------------------


class TestTheSplit(FieldMateTestCase):
	"""`split` is a pure function over integers. Testing it without a database is the point."""

	def test_an_even_split_is_even(self):
		self.assertEqual(target_service.split(300, [1, 1, 1]), [100, 100, 100])

	def test_the_parts_always_sum_to_the_whole(self):
		"""The invariant. Everything else in this phase rests on it."""
		for total in (1, 7, 100, 999, 1_000_000, 10_00_000_00):
			for weights in ([1, 1, 1], [1, 2, 3], [5, 3, 1, 1], [7], [1] * 20, [0, 0, 1]):
				parts = target_service.split(total, weights)
				self.assertEqual(sum(parts), total,
				                 f"{total} split by {weights} came to {sum(parts)}")
				self.assertEqual(len(parts), len(weights))

	def test_nothing_ever_goes_negative(self):
		for parts in (target_service.split(5, [1, 1, 1, 1, 1, 1]),
		              target_service.split(0, [3, 1])):
			self.assertTrue(all(p >= 0 for p in parts), parts)

	def test_the_spare_goes_to_the_biggest_remainder(self):
		"""100 three ways is 34/33/33, not 33/33/33 with a rupee lost."""
		self.assertEqual(target_service.split(100, [1, 1, 1]), [34, 33, 33])

	def test_a_tie_breaks_on_position_so_a_rerun_matches(self):
		"""A cascade that gave a different rep the spare rupee on a re-run is uncheckable."""
		first = target_service.split(10, [1, 1, 1])
		for _ in range(5):
			self.assertEqual(target_service.split(10, [1, 1, 1]), first)

	def test_no_weight_at_all_falls_back_to_equal(self):
		"""A tree whose nodes have no outlets yet is week one of a rollout, not an error."""
		self.assertEqual(target_service.split(90, [0, 0, 0]), [30, 30, 30])

	def test_weights_are_honoured(self):
		self.assertEqual(target_service.split(600, [1, 2, 3]), [100, 200, 300])

	def test_money_is_split_in_paise_not_rupees(self):
		"""A third of a rupee is 33 paise and 34 paise, not 0.33 three times."""
		units = target_service.to_units(1, "Value")
		self.assertEqual(units, 100)
		self.assertEqual(sum(target_service.split(units, [1, 1, 1])), 100)

	def test_counts_are_split_in_whole_things(self):
		"""Half a shop is not covered."""
		self.assertEqual(target_service.units_for("New Outlets"), 1)
		parts = target_service.split(target_service.to_units(10, "New Outlets"), [1, 1, 1])
		self.assertEqual(sum(parts), 10)
		self.assertTrue(all(float(p).is_integer() for p in parts))


# --------------------------------------------------------------------------------------
# cascade
# --------------------------------------------------------------------------------------


class TestCascade(TargetFixture):
	def test_a_plan_splits_to_its_children(self):
		kids = [self.make_rep_under(self.root_person) for _ in range(3)]
		plan = self.plan_for(self.root_person, basis="Equal")

		result = target_service.cascade(plan.name)

		self.assertEqual(len(result["children"]), 3)
		for child in result["children"]:
			doc = frappe.get_doc("FieldMate Target Plan", child)
			self.assertEqual(doc.docstatus, 1)
			self.assertEqual(doc.parent_plan, plan.name)
			# Ten lakh three ways is 3,33,333.34 once and 3,33,333.33 twice - never 3,33,333.33
			# three times, which would lose a paisa off the root.
			self.assertIn(round(flt(doc.lines[0].target_value), 2), (333333.33, 333333.34))
		self.assertEqual({k.person for k in kids},
		                 {frappe.db.get_value("FieldMate Target Plan", c, "sales_person")
		                  for c in result["children"]})

	def test_the_leaves_sum_to_the_root_exactly(self):
		"""Gate 7 criterion 1. A third of ten lakh does not divide, which is the whole point."""
		for _ in range(3):
			self.make_rep_under(self.root_person)
		plan = self.plan_for(self.root_person, basis="Equal")

		target_service.cascade(plan.name)
		report = target_service.reconcile(plan.name)

		self.assertTrue(report["matches"], report)
		self.assertEqual(report["leaf_count"], 3)
		self.assertTrue(report["types"]["Value"]["matches"])
		self.assertEqual(report["types"]["Value"]["difference"], 0)

	def test_the_leaves_sum_through_two_levels(self):
		"""A national plan reaching reps through regions still adds back up."""
		regions = [self.make_sales_person("REG", parent=self.root_person) for _ in range(2)]
		for region in regions:
			for _ in range(3):
				self.make_rep_under(region)

		plan = self.plan_for(self.root_person, basis="Equal")
		target_service.cascade(plan.name)
		report = target_service.reconcile(plan.name)

		self.assertEqual(report["leaf_count"], 6)
		self.assertTrue(report["matches"], report)

	def test_an_uneven_weight_still_sums(self):
		"""Outlet count is the default, and real depots never divide evenly."""
		self.make_rep_under(self.root_person, outlets=3)
		self.make_rep_under(self.root_person, outlets=1)
		self.make_rep_under(self.root_person, outlets=1)

		plan = self.plan_for(self.root_person, basis="Outlet Count")
		target_service.cascade(plan.name)
		report = target_service.reconcile(plan.name)

		self.assertTrue(report["matches"], report)
		values = sorted(
			flt(frappe.db.get_value("FieldMate Target Line",
			                        {"parent": leaf, "target_type": "Value"}, "target_value"))
			for leaf in target_service.leaves_of(plan.name))
		self.assertGreater(values[-1], values[0],
		                   "a rep with three times the shops must carry more")

	def test_a_ratio_target_is_copied_not_divided(self):
		"""Splitting 4.5 lines a call between twenty reps asks each of them for 0.225."""
		for _ in range(4):
			self.make_rep_under(self.root_person)
		plan = self.plan_for(self.root_person, basis="Equal", lines=[
			{"target_type": "Value", "target_value": 400000},
			{"target_type": "Lines Per Call", "target_value": 4.5},
		])

		target_service.cascade(plan.name)

		for leaf in target_service.leaves_of(plan.name):
			rate = flt(frappe.db.get_value(
				"FieldMate Target Line",
				{"parent": leaf, "target_type": "Lines Per Call"}, "target_value"))
			self.assertAlmostEqual(rate, 4.5, places=4,
			                       msg="every rep is asked for the root's own rate")

		report = target_service.reconcile(plan.name)
		self.assertTrue(report["matches"], report)
		self.assertFalse(report["types"]["Lines Per Call"]["additive"])
		self.assertEqual(report["types"]["Lines Per Call"]["leaves"], [4.5])

	def test_every_additive_type_reconciles(self):
		"""The criterion says 'for every target type', so every type is exercised."""
		for _ in range(3):
			self.make_rep_under(self.root_person, outlets=2)
		plan = self.plan_for(self.root_person, basis="Equal", lines=[
			{"target_type": "Value", "target_value": 1000000},
			{"target_type": "Volume", "target_value": 5000},
			{"target_type": "Outlet Coverage", "target_value": 280},
			{"target_type": "Productive Calls", "target_value": 210},
			{"target_type": "New Outlets", "target_value": 10},
			{"target_type": "Lines Per Call", "target_value": 4.5},
		])

		target_service.cascade(plan.name)
		report = target_service.reconcile(plan.name)

		self.assertEqual(len(report["types"]), 6)
		for target_type, entry in report["types"].items():
			self.assertTrue(entry["matches"], f"{target_type}: {entry}")

	def test_cascading_twice_does_not_double_the_children(self):
		"""The first thing anybody does is change one number at the top and run it again."""
		for _ in range(2):
			self.make_rep_under(self.root_person)
		plan = self.plan_for(self.root_person, basis="Equal")

		target_service.cascade(plan.name)
		with self.assertRaises(frappe.ValidationError):
			# The children are submitted, so a silent rewrite would change numbers a rep has
			# already been shown. It says so instead.
			target_service.cascade(plan.name)

	def test_a_leaf_cascades_to_nothing_and_says_so(self):
		plan = self.plan_for(self.make_sales_person("SOLO", parent=self.root_person, is_group=0))
		result = target_service.cascade(plan.name)
		self.assertTrue(result["leaf"])
		self.assertEqual(result["children"], [])

	def test_an_uncascaded_plan_reconciles_to_itself(self):
		"""Not a special case to patch around: a plan with no children is its own leaf."""
		plan = self.plan_for(self.make_sales_person("SOLO", parent=self.root_person, is_group=0))
		report = target_service.reconcile(plan.name)
		self.assertEqual(report["leaf_count"], 1)
		self.assertTrue(report["matches"], report)

	def test_a_cascaded_plan_cannot_be_cancelled_underneath_its_children(self):
		self.make_rep_under(self.root_person)
		plan = self.plan_for(self.root_person, basis="Equal")
		target_service.cascade(plan.name)

		doc = frappe.get_doc("FieldMate Target Plan", plan.name)
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()

	def test_two_targets_of_one_type_are_refused(self):
		"""Two Value lines is not a bigger target, it is somebody typing twice."""
		with self.assertRaises(frappe.ValidationError):
			self.plan_for(self.root_person, lines=[
				{"target_type": "Value", "target_value": 100},
				{"target_type": "Value", "target_value": 200},
			])

	def test_a_category_target_sits_beside_the_overall_one(self):
		group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		plan = self.plan_for(self.root_person, lines=[
			{"target_type": "Value", "target_value": 1000},
			{"target_type": "Value", "item_group": group, "target_value": 400},
		])
		self.assertEqual(len(plan.lines), 2)


# --------------------------------------------------------------------------------------
# achievement
# --------------------------------------------------------------------------------------


class TestAchievement(TargetFixture):
	def setUp(self):
		super().setUp()
		self.person = self.make_sales_person("SOLO", parent=self.root_person, is_group=0)
		frappe.db.set_value("FieldMate Field User", self.rep.name, "sales_person", self.person)

	def test_value_counts_orders_the_rep_actually_booked(self):
		booked = self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 10000}])

		target_service.compute(plan.name)
		doc = frappe.get_doc("FieldMate Achievement", {"target_plan": plan.name})

		self.assertAlmostEqual(flt(doc.lines[0].actual_value),
		                       flt(booked["net_total"]), places=2)
		self.assertEqual(doc.field_user, self.rep.name)

	def test_a_cancelled_order_stops_counting(self):
		"""Otherwise a rep books, takes the credit, and cancels on the first of next month."""
		from fieldmate.services import order as order_service

		booked = self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 10000}])
		target_service.compute(plan.name)
		before = flt(frappe.get_doc("FieldMate Achievement",
		                            {"target_plan": plan.name}).lines[0].actual_value)

		# As the rep, because cancelling checks ownership - the same guard a real cancel goes
		# through, and cancelling as Administrator would be testing a path nobody takes.
		self.as_rep(order_service.cancel, booked["name"], "testing")
		target_service.compute(plan.name)
		after = flt(frappe.get_doc("FieldMate Achievement",
		                           {"target_plan": plan.name}).lines[0].actual_value)

		self.assertGreater(before, 0)
		self.assertEqual(after, 0)

	def test_all_six_types_are_measured(self):
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 10000},
			{"target_type": "Volume", "target_value": 100},
			{"target_type": "Outlet Coverage", "target_value": 5},
			{"target_type": "Productive Calls", "target_value": 5},
			{"target_type": "New Outlets", "target_value": 2},
			{"target_type": "Lines Per Call", "target_value": 4.5},
		])

		target_service.compute(plan.name)
		doc = frappe.get_doc("FieldMate Achievement", {"target_plan": plan.name})

		self.assertEqual(len(doc.lines), 6)
		measured = {r.target_type: flt(r.actual_value) for r in doc.lines}
		self.assertGreater(measured["Value"], 0)
		self.assertGreater(measured["Volume"], 0)
		self.assertEqual(measured["Outlet Coverage"], 1, "one shop was sold to")
		for target_type in ("Productive Calls", "New Outlets", "Lines Per Call"):
			self.assertIn(target_type, measured)

	def test_a_ratio_carries_no_shortfall(self):
		"""A rep at 4.2 against 4.5 is not 0.3 lines behind - they are selling narrower carts."""
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 10000},
			{"target_type": "Lines Per Call", "target_value": 4.5},
		])
		target_service.compute(plan.name)
		doc = frappe.get_doc("FieldMate Achievement", {"target_plan": plan.name})

		rate = next(r for r in doc.lines if r.target_type == "Lines Per Call")
		self.assertEqual(flt(rate.shortfall), 0)

	def test_recomputing_rewrites_rather_than_duplicating(self):
		self.book(qty=20)
		plan = self.plan_for(self.person)
		first = target_service.compute(plan.name)
		second = target_service.compute(plan.name)

		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("FieldMate Achievement", {"target_plan": plan.name}), 1)

	def test_the_rep_sees_their_own_standing(self):
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 10000}])
		target_service.compute(plan.name)

		standing = target_service.mine(self.rep.name)

		self.assertTrue(standing["has_target"])
		self.assertEqual(standing["plan"], plan.name)
		self.assertGreater(standing["headline_pct"], 0)
		self.assertTrue(standing["computed_on"])

	def test_a_rep_with_no_plan_is_told_so_rather_than_shown_zero(self):
		standing = target_service.mine(self.rep.name)
		self.assertFalse(standing["has_target"])


# --------------------------------------------------------------------------------------
# incentive
# --------------------------------------------------------------------------------------


class TestIncentiveArithmetic(TargetFixture):
	"""The slab table, against figures anybody can check on paper."""

	def scheme(self, **extra):
		data = {
			"doctype": "FieldMate Incentive Scheme",
			"scheme_name": self.uid("T7-INC"),
			"company": self.company,
			"is_active": 1,
			"valid_from": add_days(today(), -30),
			"measured_on": "Value",
			"qualifying_pct": 80,
			"slabs": [
				{"slab_idx": 1, "from_pct": 80, "to_pct": 100,
				 "payout_kind": "Fixed Amount", "payout_amount": 4200, "label": "Tier 1"},
				{"slab_idx": 2, "from_pct": 100, "to_pct": 120,
				 "payout_kind": "Fixed Amount", "payout_amount": 6000, "label": "Tier 2"},
				{"slab_idx": 3, "from_pct": 120, "is_open_ended": 1,
				 "payout_kind": "Fixed Amount", "payout_amount": 9000, "label": "Tier 3"},
			],
		}
		data.update(extra)
		doc = frappe.get_doc(data)
		doc.flags.ignore_permissions = True
		doc.insert()
		self.track("FieldMate Incentive Scheme", doc.name)
		doc.submit()
		return doc

	def test_below_the_qualifying_line_nothing_is_earned(self):
		scheme = self.scheme()
		result = incentive_service.award(scheme, 79.9, 790000)
		self.assertFalse(result["qualified"])
		self.assertEqual(result["payout_paise"], 0)

	def test_exactly_at_a_boundary_lands_in_the_slab_above(self):
		"""The one boundary every incentive argument is about."""
		scheme = self.scheme()
		self.assertEqual(incentive_service.award(scheme, 80, 800000)["slab_label"], "Tier 1")
		self.assertEqual(incentive_service.award(scheme, 100, 1000000)["slab_label"], "Tier 2")
		self.assertEqual(incentive_service.award(scheme, 120, 1200000)["slab_label"], "Tier 3")

	def test_the_top_slab_has_no_ceiling(self):
		"""A rep at 140% against a table stopping at 120 must not earn nothing."""
		scheme = self.scheme()
		result = incentive_service.award(scheme, 140, 1400000)
		self.assertEqual(result["slab_label"], "Tier 3")
		self.assertEqual(incentive_service.in_rupees(result["payout_paise"]), 9000)

	def test_a_percentage_pays_on_actual_not_on_target(self):
		"""Of the target, a rep at 81% and one at 119% would be paid the same."""
		scheme = self.scheme(slabs=[
			{"slab_idx": 1, "from_pct": 80, "is_open_ended": 1,
			 "payout_kind": "Percent Of Value", "payout_pct": 0.5, "label": "Half a percent"},
		])
		low = incentive_service.award(scheme, 81, 810000)
		high = incentive_service.award(scheme, 119, 1190000)

		self.assertEqual(incentive_service.in_rupees(low["payout_paise"]), 4050.00)
		self.assertEqual(incentive_service.in_rupees(high["payout_paise"]), 5950.00)

	def test_the_percentage_is_computed_in_paise(self):
		"""0.5% of 8,33,333.33 is 4166.67 - and 4166.665 rounds up, not to even."""
		scheme = self.scheme(slabs=[
			{"slab_idx": 1, "from_pct": 0, "is_open_ended": 1,
			 "payout_kind": "Percent Of Value", "payout_pct": 0.5},
		], qualifying_pct=0)
		result = incentive_service.award(scheme, 100, 833333.33)
		self.assertEqual(incentive_service.in_rupees(result["payout_paise"]), 4166.67)

	def test_the_cap_is_applied_last_and_is_visible(self):
		"""Capping the rate instead of the result looks identical on a good month."""
		scheme = self.scheme(cap_amount=5000, slabs=[
			{"slab_idx": 1, "from_pct": 80, "is_open_ended": 1,
			 "payout_kind": "Percent Of Value", "payout_pct": 1},
		])
		result = incentive_service.award(scheme, 100, 1000000)

		self.assertEqual(incentive_service.in_rupees(result["gross_paise"]), 10000)
		self.assertEqual(incentive_service.in_rupees(result["capped_paise"]), 5000)
		self.assertEqual(incentive_service.in_rupees(result["payout_paise"]), 5000)
		self.assertIn("capped", result["working"])

	def test_the_working_says_what_it_did(self):
		scheme = self.scheme()
		result = incentive_service.award(scheme, 95, 950000)
		self.assertIn("Tier 1", result["working"])
		self.assertIn("95", result["working"])

	def test_three_reps_against_a_hand_built_table(self):
		"""Gate 7 criterion 3, as a unit test. Worked out on paper first:

		    rep A   64% of 10,00,000   -> below 80%, qualifies for nothing        0
		    rep B   95% of 10,00,000   -> Tier 1, flat                        4,200
		    rep C  131% of 10,00,000   -> Tier 3, flat                        9,000
		"""
		scheme = self.scheme()
		table = [(64, 640000, 0), (95, 950000, 4200), (131, 1310000, 9000)]
		for pct, actual, expected in table:
			result = incentive_service.award(scheme, pct, actual)
			self.assertEqual(incentive_service.in_rupees(result["payout_paise"]), expected,
			                 f"{pct}% of the target should pay {expected}")


class TestIncentiveSchemeShape(TargetFixture):
	def base(self, slabs, **extra):
		data = {
			"doctype": "FieldMate Incentive Scheme",
			"scheme_name": self.uid("T7-BAD"),
			"company": self.company,
			"valid_from": today(),
			"measured_on": "Value",
			"slabs": slabs,
		}
		data.update(extra)
		doc = frappe.get_doc(data)
		doc.flags.ignore_permissions = True
		return doc

	def test_overlapping_slabs_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.base([
				{"from_pct": 80, "to_pct": 110, "payout_kind": "Fixed Amount", "payout_amount": 1},
				{"from_pct": 100, "is_open_ended": 1, "payout_kind": "Fixed Amount",
				 "payout_amount": 2},
			]).insert()

	def test_a_gap_between_slabs_is_refused(self):
		"""A rep landing at 105% between an 80-100 and a 110+ slab would earn nothing."""
		with self.assertRaises(frappe.ValidationError):
			self.base([
				{"from_pct": 80, "to_pct": 100, "payout_kind": "Fixed Amount", "payout_amount": 1},
				{"from_pct": 110, "is_open_ended": 1, "payout_kind": "Fixed Amount",
				 "payout_amount": 2},
			]).insert()

	def test_a_closed_top_slab_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.base([
				{"from_pct": 80, "to_pct": 120, "payout_kind": "Fixed Amount",
				 "payout_amount": 1},
			]).insert()

	def test_an_open_slab_in_the_middle_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.base([
				{"from_pct": 80, "is_open_ended": 1, "payout_kind": "Fixed Amount",
				 "payout_amount": 1},
				{"from_pct": 120, "is_open_ended": 1, "payout_kind": "Fixed Amount",
				 "payout_amount": 2},
			]).insert()


class TestPayouts(TargetFixture):
	def setUp(self):
		super().setUp()
		self.person = self.make_sales_person("SOLO", parent=self.root_person, is_group=0)
		frappe.db.set_value("FieldMate Field User", self.rep.name, "sales_person", self.person)

	def scheme(self):
		doc = frappe.get_doc({
			"doctype": "FieldMate Incentive Scheme",
			"scheme_name": self.uid("T7-PAY"),
			"company": self.company,
			"valid_from": add_days(today(), -30),
			"measured_on": "Value",
			"qualifying_pct": 0,
			"slabs": [{"slab_idx": 1, "from_pct": 0, "is_open_ended": 1,
			           "payout_kind": "Fixed Amount", "payout_amount": 1500, "label": "Flat"}],
		})
		doc.flags.ignore_permissions = True
		doc.insert()
		self.track("FieldMate Incentive Scheme", doc.name)
		doc.submit()
		return doc

	def test_a_payout_is_created_and_names_its_evidence(self):
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 1000}])
		target_service.compute(plan.name)
		scheme = self.scheme()

		results = incentive_service.compute_for(self.rep.name, plan.name)
		earned = [r for r in results if not r.get("skipped")]

		self.assertEqual(len(earned), 1)
		payout = frappe.get_doc("FieldMate Incentive Payout", earned[0]["payout"])
		self.assertEqual(payout.scheme, scheme.name)
		self.assertEqual(payout.target_plan, plan.name)
		self.assertTrue(payout.achievement, "a payout that cannot name its figures is indefensible")
		self.assertEqual(flt(payout.payout_amount), 1500)
		self.assertTrue(payout.working)

	def test_recomputing_does_not_duplicate(self):
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 1000}])
		target_service.compute(plan.name)
		self.scheme()

		incentive_service.compute_for(self.rep.name, plan.name)
		incentive_service.compute_for(self.rep.name, plan.name)

		self.assertEqual(frappe.db.count("FieldMate Incentive Payout",
		                                 {"field_user": self.rep.name}), 1)

	def test_a_submitted_payout_is_never_silently_restated(self):
		"""Somebody has been told what they earned. Recomputing must not change it."""
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 1000}])
		target_service.compute(plan.name)
		self.scheme()

		name = incentive_service.compute_for(self.rep.name, plan.name)[0]["payout"]
		doc = frappe.get_doc("FieldMate Incentive Payout", name)
		doc.flags.ignore_permissions = True
		doc.submit()

		incentive_service.compute_for(self.rep.name, plan.name)
		self.assertEqual(frappe.db.get_value("FieldMate Incentive Payout", name, "docstatus"), 1)

	def test_a_scheme_measuring_something_untargeted_is_skipped_out_loud(self):
		"""Skipped and paid-at-zero look identical on a report, and only one is a mistake."""
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 1000}])
		target_service.compute(plan.name)

		doc = frappe.get_doc({
			"doctype": "FieldMate Incentive Scheme",
			"scheme_name": self.uid("T7-NEW"),
			"company": self.company,
			"valid_from": add_days(today(), -30),
			"measured_on": "New Outlets",
			"slabs": [{"slab_idx": 1, "from_pct": 0, "is_open_ended": 1,
			           "payout_kind": "Fixed Amount", "payout_amount": 500}],
		})
		doc.flags.ignore_permissions = True
		doc.insert()
		self.track("FieldMate Incentive Scheme", doc.name)
		doc.submit()

		results = incentive_service.compute_for(self.rep.name, plan.name)
		skipped = [r for r in results if r.get("skipped")]
		self.assertEqual(len(skipped), 1)
		self.assertIn("New Outlets", skipped[0]["reason"])

	def test_a_rejection_needs_a_reason(self):
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 1000}])
		target_service.compute(plan.name)
		self.scheme()
		name = incentive_service.compute_for(self.rep.name, plan.name)[0]["payout"]
		doc = frappe.get_doc("FieldMate Incentive Payout", name)
		doc.flags.ignore_permissions = True
		doc.submit()

		with self.assertRaises(frappe.ValidationError):
			incentive_service.approve(name, "Rejected")

	def test_paying_needs_a_reference(self):
		"""FieldMate does not pay anybody. It says what is owed and records where it went."""
		self.book(qty=20)
		plan = self.plan_for(self.person, lines=[
			{"target_type": "Value", "target_value": 1000}])
		target_service.compute(plan.name)
		self.scheme()
		name = incentive_service.compute_for(self.rep.name, plan.name)[0]["payout"]
		doc = frappe.get_doc("FieldMate Incentive Payout", name)
		doc.flags.ignore_permissions = True
		doc.submit()
		incentive_service.approve(name, "Approved")

		with self.assertRaises(frappe.ValidationError):
			incentive_service.mark_paid(name, "")
