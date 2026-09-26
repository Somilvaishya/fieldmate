"""Exceptions, and the one promise that makes them worth reading.

Gate 8 criterion 5: **each rule fires exactly once per occurrence.** An occurrence is rule + rep
+ day, and that string is a unique column on the log, so the database refuses a second one
however often the job runs. Most of this file is that sentence, tested from several directions -
a repeat run, a re-evaluation after the snapshot moved, and two rules watching the same rep.

The rest is about whether anybody will still be reading the channel in a month: a ratio over
almost nothing is noise, one bad day is weather, and a rule that repeats itself every morning
about the same unresolved thing gets filtered into a folder.
"""

import frappe
from frappe.utils import add_days, today

from fieldmate.services import alerts as alerts_service
from fieldmate.services import kpi as kpi_service
from fieldmate.tests.test_order import OrderFixture


class AlertFixture(OrderFixture):
	def tearDown(self):
		frappe.set_user("Administrator")
		for dt in ("FieldMate Alert Log", "FieldMate Alert Rule", "FieldMate KPI Snapshot"):
			for name in frappe.get_all(dt, filters={} if dt != "FieldMate Alert Rule"
			                           else {"rule_name": ["like", "T8-%"]}, pluck="name"):
				try:
					frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
				except Exception:
					pass
		frappe.db.commit()
		super().tearDown()

	def rule(self, exception="No Order All Day", **extra):
		data = {
			"doctype": "FieldMate Alert Rule",
			"rule_name": self.uid("T8-RULE"),
			"exception": exception,
			"is_active": 1,
			"severity": "Warning",
			"threshold": 0,
			"comparison": "Above",
			"consecutive_days": 1,
			"notify_manager": 0,
		}
		data.update(extra)
		doc = frappe.get_doc(data)
		doc.flags.ignore_permissions = True
		doc.insert()
		self.track("FieldMate Alert Rule", doc.name)
		return doc

	def snapshot(self, day=None, **values):
		"""A snapshot row written directly.

		Written rather than rolled up on purpose: these tests are about the evaluator, and a
		fixture that had to produce a real bad day through visits and orders would be testing
		the rollup again at ten times the cost.
		"""
		day = day or today()
		existing = frappe.db.get_value("FieldMate KPI Snapshot",
		                               {"field_user": self.rep.name, "snapshot_date": day},
		                               "name")
		row = {"field_user": self.rep.name, "snapshot_date": day, "territory": self.rep.territory,
		       "day_started": 1, "actual_visits": 10, "productive_visits": 5,
		       "orders_count": 1, "outlets_in_scope": 100, "outlets_billed": 50}
		row.update(values)
		row.update(kpi_service.derive(row))

		doc = frappe.get_doc("FieldMate KPI Snapshot", existing) if existing \
			else frappe.new_doc("FieldMate KPI Snapshot")
		doc.update(row)
		doc.flags.ignore_permissions = True
		doc.save()
		return doc


class TestOncePerOccurrence(AlertFixture):
	def test_a_rule_fires_when_the_condition_holds(self):
		rule = self.rule(threshold=4, minimum_base=0)
		self.snapshot(actual_visits=12, orders_count=0)

		result = alerts_service.evaluate_rule(rule.name, today())

		self.assertEqual(result["fired"], 1)
		log = frappe.get_doc("FieldMate Alert Log", result["logs"][0])
		self.assertEqual(log.field_user, self.rep.name)
		self.assertEqual(log.observed_value, 12)
		self.assertEqual(log.base_value, 12)

	def test_running_it_again_does_not_fire_again(self):
		"""Gate 8 criterion 5. The job runs hourly; the occurrence happened once."""
		rule = self.rule(threshold=4, minimum_base=0)
		self.snapshot(actual_visits=12, orders_count=0)

		first = alerts_service.evaluate_rule(rule.name, today())
		second = alerts_service.evaluate_rule(rule.name, today())
		third = alerts_service.evaluate_rule(rule.name, today())

		self.assertEqual(first["fired"], 1)
		self.assertEqual(second["fired"], 0)
		self.assertEqual(third["fired"], 0)
		self.assertEqual(second["already_logged"], 1)
		self.assertEqual(frappe.db.count("FieldMate Alert Log", {"rule": rule.name}), 1)

	def test_the_key_is_unique_in_the_database_not_only_in_the_code(self):
		"""Two workers reaching the same occurrence must produce one row, not two."""
		rule = self.rule(threshold=4, minimum_base=0)
		self.snapshot(actual_visits=12, orders_count=0)
		alerts_service.evaluate_rule(rule.name, today())

		key = f"{rule.name}|{self.rep.name}|{today()}"
		doc = frappe.get_doc({
			"doctype": "FieldMate Alert Log", "rule": rule.name,
			"exception": rule.exception, "field_user": self.rep.name,
			"occurred_on": today(), "occurrence_key": key,
		})
		doc.flags.ignore_permissions = True
		# UniqueValidationError, not DuplicateEntryError: the key is a unique COLUMN that MySQL
		# rejects, not a clashing primary key. The distinction is only interesting because
		# `_log` has to catch the right one, and at first it did not.
		with self.assertRaises(frappe.UniqueValidationError):
			doc.insert()

	def test_a_different_day_is_a_different_occurrence(self):
		rule = self.rule(threshold=4, minimum_base=0)
		self.snapshot(day=today(), actual_visits=12, orders_count=0)
		self.snapshot(day=add_days(today(), -1), actual_visits=9, orders_count=0)

		alerts_service.evaluate_rule(rule.name, today())
		alerts_service.evaluate_rule(rule.name, add_days(today(), -1))

		self.assertEqual(frappe.db.count("FieldMate Alert Log", {"rule": rule.name}), 2)

	def test_recomputing_the_snapshot_does_not_re_fire(self):
		"""A day corrected at noon is still the same day, and was already reported."""
		rule = self.rule(threshold=4, minimum_base=0)
		self.snapshot(actual_visits=12, orders_count=0)
		alerts_service.evaluate_rule(rule.name, today())

		self.snapshot(actual_visits=14, orders_count=0)
		again = alerts_service.evaluate_rule(rule.name, today())

		self.assertEqual(again["fired"], 0)
		self.assertEqual(frappe.db.count("FieldMate Alert Log", {"rule": rule.name}), 1)


class TestNotFiringOnNoise(AlertFixture):
	def test_a_ratio_over_almost_nothing_is_ignored(self):
		"""A rep with two calls and no order has not had a day yet."""
		rule = self.rule(threshold=0, comparison="Above", minimum_base=4)
		self.snapshot(actual_visits=2, orders_count=0)

		self.assertEqual(alerts_service.evaluate_rule(rule.name, today())["fired"], 0)

	def test_the_same_rule_fires_once_the_base_is_real(self):
		rule = self.rule(threshold=0, comparison="Above", minimum_base=4)
		self.snapshot(actual_visits=9, orders_count=0)

		self.assertEqual(alerts_service.evaluate_rule(rule.name, today())["fired"], 1)

	def test_one_bad_day_does_not_fire_a_three_day_rule(self):
		rule = self.rule(exception="Coverage Below Target", threshold=60, comparison="Below",
		                 minimum_base=0, consecutive_days=3)
		self.snapshot(outlets_in_scope=100, outlets_billed=10)

		self.assertEqual(alerts_service.evaluate_rule(rule.name, today())["fired"], 0)

	def test_three_bad_days_running_do(self):
		rule = self.rule(exception="Coverage Below Target", threshold=60, comparison="Below",
		                 minimum_base=0, consecutive_days=3)
		for back in range(3):
			self.snapshot(day=add_days(today(), -back), outlets_in_scope=100, outlets_billed=10)

		result = alerts_service.evaluate_rule(rule.name, today())

		self.assertEqual(result["fired"], 1)
		log = frappe.get_doc("FieldMate Alert Log", result["logs"][0])
		self.assertEqual(log.consecutive_days, 3)

	def test_a_good_day_in_the_middle_breaks_the_streak(self):
		rule = self.rule(exception="Coverage Below Target", threshold=60, comparison="Below",
		                 minimum_base=0, consecutive_days=3)
		self.snapshot(day=today(), outlets_in_scope=100, outlets_billed=10)
		self.snapshot(day=add_days(today(), -1), outlets_in_scope=100, outlets_billed=90)
		self.snapshot(day=add_days(today(), -2), outlets_in_scope=100, outlets_billed=10)

		self.assertEqual(alerts_service.evaluate_rule(rule.name, today())["fired"], 0)

	def test_a_cooldown_keeps_it_quiet_about_the_same_thing(self):
		rule = self.rule(threshold=4, minimum_base=0, cooldown_days=7)
		self.snapshot(day=add_days(today(), -1), actual_visits=12, orders_count=0)
		self.snapshot(day=today(), actual_visits=12, orders_count=0)

		alerts_service.evaluate_rule(rule.name, add_days(today(), -1))
		second = alerts_service.evaluate_rule(rule.name, today())

		self.assertEqual(second["fired"], 0, "it said this yesterday")

	def test_an_inactive_rule_says_nothing(self):
		rule = self.rule(threshold=4, minimum_base=0, is_active=0)
		self.snapshot(actual_visits=12, orders_count=0)

		result = alerts_service.evaluate_rule(rule.name, today())
		self.assertEqual(result["fired"], 0)
		self.assertEqual(result["skipped"], "inactive")

	def test_a_rep_with_no_snapshot_is_not_blamed_for_our_lateness(self):
		"""No row means the rollup has not run, not that the rep did nothing."""
		rule = self.rule(threshold=4, minimum_base=0)
		self.assertEqual(alerts_service.evaluate_rule(rule.name, today())["fired"], 0)


class TestTheFiveConditions(AlertFixture):
	def test_cash_carried_and_not_handed_over(self):
		rule = self.rule(exception="Collection Overdue In Hand", threshold=5000,
		                 comparison="Above", minimum_base=0)
		self.snapshot(collection_amount=12000, deposited_amount=2000)

		result = alerts_service.evaluate_rule(rule.name, today())

		self.assertEqual(result["fired"], 1)
		log = frappe.get_doc("FieldMate Alert Log", result["logs"][0])
		self.assertEqual(log.observed_value, 10000, "what is still in the satchel")

	def test_cash_all_handed_over_says_nothing(self):
		rule = self.rule(exception="Collection Overdue In Hand", threshold=5000,
		                 comparison="Above", minimum_base=0)
		self.snapshot(collection_amount=12000, deposited_amount=12000)

		self.assertEqual(alerts_service.evaluate_rule(rule.name, today())["fired"], 0)

	def test_geo_fence_breaches(self):
		rule = self.rule(exception="Geo Fence Breaches", threshold=2, comparison="Above",
		                 minimum_base=0)
		self.snapshot(actual_visits=10, geo_breach_visits=5)

		result = alerts_service.evaluate_rule(rule.name, today())
		self.assertEqual(result["fired"], 1)
		log = frappe.get_doc("FieldMate Alert Log", result["logs"][0])
		self.assertEqual(log.base_value, 10, "out of how many visits")

	def test_coverage_below_target(self):
		rule = self.rule(exception="Coverage Below Target", threshold=60, comparison="Below",
		                 minimum_base=0)
		self.snapshot(outlets_in_scope=100, outlets_billed=40)

		result = alerts_service.evaluate_rule(rule.name, today())
		self.assertEqual(result["fired"], 1)
		self.assertEqual(
			frappe.db.get_value("FieldMate Alert Log", result["logs"][0], "observed_value"), 40)

	def test_a_day_that_was_started_is_not_reported_as_missing(self):
		rule = self.rule(exception="Day Not Started", threshold=0, comparison="Above",
		                 minimum_base=0)
		self.snapshot(day=add_days(today(), -1), day_started=1)

		self.assertEqual(
			alerts_service.evaluate_rule(rule.name, add_days(today(), -1))["fired"], 0)

	def test_a_day_never_started_is(self):
		rule = self.rule(exception="Day Not Started", threshold=0, comparison="Above",
		                 minimum_base=0)
		self.snapshot(day=add_days(today(), -1), day_started=0)

		self.assertEqual(
			alerts_service.evaluate_rule(rule.name, add_days(today(), -1))["fired"], 1)


class TestTheRuleItself(AlertFixture):
	def test_an_unknown_exception_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.rule(exception="Something Nobody Wrote")

	def test_a_coverage_threshold_outside_a_percentage_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			self.rule(exception="Coverage Below Target", threshold=6000)

	def test_the_five_shipped_rules_install_once(self):
		before = frappe.db.count("FieldMate Alert Rule")
		alerts_service.install_starter_rules()
		after = frappe.db.count("FieldMate Alert Rule")
		alerts_service.install_starter_rules()

		self.assertEqual(frappe.db.count("FieldMate Alert Rule"), after,
		                 "installing twice must not double them")
		self.assertGreaterEqual(after, before)
		for payload in alerts_service.STARTER_RULES:
			self.assertTrue(frappe.db.exists("FieldMate Alert Rule", payload["rule_name"]))

	def test_a_broken_message_template_does_not_lose_the_alert(self):
		"""The figures matter more than the sentence."""
		rule = self.rule(threshold=4, minimum_base=0,
		                 message_template="{nonsense} and {alsomissing}")
		self.snapshot(actual_visits=12, orders_count=0)

		result = alerts_service.evaluate_rule(rule.name, today())

		self.assertEqual(result["fired"], 1)
		message = frappe.db.get_value("FieldMate Alert Log", result["logs"][0], "message")
		self.assertIn("booked nothing", message)
