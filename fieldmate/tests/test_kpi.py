"""The KPI snapshot, the nine metrics, and the exceptions read off them.

Two things are being proved.

The first is that **the numbers are right** - not plausible, right. Gate 8 criterion 1 asks that
every metric be reproducible by hand for a rep-week, so the tests here build a week whose answers
were worked out on paper first and then assert those exact figures. A test that asserts
`self.assertGreater(value, 0)` proves the query ran, which is not the same thing.

The second is that **a month is the days added up, except for the ratios**. Averaging thirty
daily strike rates answers a different question from the one anybody asked. Both behaviours are
asserted separately, because one of them is a sum and the other is not.
"""

import frappe
from frappe.utils import add_days, flt, today

from fieldmate.services import kpi as kpi_service
from fieldmate.tests.test_order import OrderFixture


class KpiFixture(OrderFixture):
	def tearDown(self):
		frappe.set_user("Administrator")
		self.wipe_since_setup("FieldMate Alert Log", "FieldMate KPI Snapshot")
		super().tearDown()

	def another_shop(self):
		"""A second shop on the same beat, behind the same distributor.

		The distributor is not optional and must not be left to a session default (ADR-020): an
		order routes to it, so an outlet without one is a shape the real app never produces and
		the order refuses on a mandatory field that says nothing about the test.
		"""
		return self.make_outlet(territory=self.rep.territory,
		                        distributor=self.outlet.distributor,
		                        approval_status="Approved")

	def book_on(self, day, outlet=None, qty=20):
		"""An order on a given day, at a given shop."""
		from fieldmate.services import order as order_service

		payload = {"outlet": outlet or self.outlet.name, "order_date": day,
		           "lines": self.cart(qty), "client_uuid": self.uid("ORD")}
		created = self.as_rep(order_service.create, payload, self.rep.name)
		self.track("FieldMate Order", created["name"])
		return self.as_rep(order_service.submit_order, created["name"])


class TestCountingOneDay(KpiFixture):
	def test_an_empty_day_counts_zero_and_says_so(self):
		"""Zero everywhere, and the bases beside the ratios so a reader can tell an empty day
		from a bad one."""
		row = kpi_service.measure(self.rep.name, today())

		self.assertEqual(row["actual_visits"], 0)
		self.assertEqual(row["orders_count"], 0)
		self.assertEqual(row["order_value"], 0)
		self.assertEqual(row["productive_pct"], 0)
		self.assertEqual(row["lines_per_call"], 0)
		self.assertFalse(row["day_started"])

	def test_orders_are_counted_from_the_documents(self):
		booked = self.book_on(today())
		row = kpi_service.measure(self.rep.name, today())

		self.assertEqual(row["orders_count"], 1)
		self.assertAlmostEqual(row["order_value"], flt(booked["net_total"]), places=2)
		self.assertEqual(row["outlets_billed"], 1)

	def test_a_cancelled_order_stops_counting(self):
		"""Otherwise a rep books, is counted, and cancels on the first of next month."""
		from fieldmate.services import order as order_service

		booked = self.book_on(today())
		before = kpi_service.measure(self.rep.name, today())["order_value"]

		self.as_rep(order_service.cancel, booked["name"], "testing")
		after = kpi_service.measure(self.rep.name, today())["order_value"]

		self.assertGreater(before, 0)
		self.assertEqual(after, 0)

	def test_two_shops_is_two_shops_billed(self):
		other = self.another_shop()
		self.book_on(today())
		self.book_on(today(), outlet=other.name)

		row = kpi_service.measure(self.rep.name, today())
		self.assertEqual(row["orders_count"], 2)
		self.assertEqual(row["outlets_billed"], 2)

	def test_the_same_shop_twice_is_one_shop_billed(self):
		self.book_on(today())
		self.book_on(today())

		row = kpi_service.measure(self.rep.name, today())
		self.assertEqual(row["orders_count"], 2)
		self.assertEqual(row["outlets_billed"], 1, "coverage counts shops, not orders")

	def test_distinct_skus_is_not_the_line_count(self):
		"""A rep who sells the same SKU at ten shops has ten lines and one SKU."""
		other = self.another_shop()
		self.book_on(today())
		self.book_on(today(), outlet=other.name)

		row = kpi_service.measure(self.rep.name, today())
		self.assertEqual(row["distinct_skus"], 1)
		self.assertEqual(row["order_lines"], 2)


class TestTheNine(KpiFixture):
	"""Each of the nine, against a figure worked out on paper first."""

	def test_coverage_is_shops_billed_over_shops_in_territory(self):
		# Four shops in the rep's territory (one from the fixture, three more), one billed.
		for _ in range(3):
			self.another_shop()
		self.book_on(today())

		row = kpi_service.measure(self.rep.name, today())

		self.assertEqual(row["outlets_in_scope"], 4)
		self.assertEqual(row["outlets_billed"], 1)
		self.assertEqual(row["coverage_pct"], 25.0)

	def test_strike_rate_is_productive_over_calls(self):
		self.assertEqual(kpi_service.pct(3, 4), 75.0)
		self.assertEqual(kpi_service.pct(1, 3), 33.33)

	def test_a_ratio_over_nothing_is_zero_not_an_error(self):
		self.assertEqual(kpi_service.pct(5, 0), 0.0)
		self.assertEqual(kpi_service.ratio(5, 0), 0.0)

	def test_lines_per_call_divides_by_productive_calls_not_by_all_calls(self):
		"""A rep who saw twelve shops and sold at three has a cart width of three shops, not
		twelve. Dividing by every call would report a rep who walks past shops as selling
		narrower carts than one who does not."""
		row = kpi_service.derive({"order_lines": 12, "productive_visits": 3,
		                          "actual_visits": 12})
		self.assertEqual(row["lines_per_call"], 4.0)

	def test_average_order_value_divides_by_orders(self):
		row = kpi_service.derive({"order_value": 3000, "orders_count": 4})
		self.assertEqual(row["avg_order_value"], 750.0)

	def test_collection_efficiency_is_against_what_could_have_been_collected(self):
		row = kpi_service.derive({"collection_amount": 2500, "billable_base": 10000})
		self.assertEqual(row["collection_efficiency_pct"], 25.0)

	def test_plan_compliance_is_calls_made_over_calls_planned(self):
		row = kpi_service.derive({"actual_visits": 14, "planned_visits": 20})
		self.assertEqual(row["visit_compliance_pct"], 70.0)

	def test_the_nine_are_nine_and_carry_their_bases(self):
		row = kpi_service.measure(self.rep.name, today())
		nine = kpi_service.core_metrics(row)

		self.assertEqual(len(nine), 9)
		for entry in nine:
			self.assertIn("label", entry)
			self.assertIn("value", entry)
		# Every ratio ships the denominator it was measured over.
		for entry in nine:
			if entry["is_pct"]:
				self.assertIn("of", entry,
				              f"{entry['key']} is a percentage with no base beside it")


class TestRollingUp(KpiFixture):
	def test_a_roll_up_writes_one_row_per_rep_day(self):
		self.book_on(today())
		name = kpi_service.roll_up(self.rep.name, today())

		self.assertTrue(name)
		self.assertEqual(frappe.db.count("FieldMate KPI Snapshot",
		                                 {"field_user": self.rep.name,
		                                  "snapshot_date": today()}), 1)

	def test_rolling_up_twice_rewrites_rather_than_duplicating(self):
		self.book_on(today())
		first = kpi_service.roll_up(self.rep.name, today())
		second = kpi_service.roll_up(self.rep.name, today(), force=True)

		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("FieldMate KPI Snapshot",
		                                 {"field_user": self.rep.name}), 1)

	def test_an_unchanged_day_is_skipped(self):
		"""The fingerprint is what lets an hourly job look at a month cheaply."""
		self.book_on(today())
		kpi_service.roll_up(self.rep.name, today())
		again = kpi_service.roll_up(self.rep.name, today())

		self.assertIsNone(again, "a day nothing touched must not be recounted")

	def test_a_second_row_for_one_rep_day_is_refused(self):
		"""Two snapshots for one rep-day is two answers, and every sum downstream doubles."""
		kpi_service.roll_up(self.rep.name, today())
		doc = frappe.get_doc({
			"doctype": "FieldMate KPI Snapshot",
			"field_user": self.rep.name, "snapshot_date": today(),
		})
		doc.flags.ignore_permissions = True
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_a_backdated_order_restates_the_day_it_belongs_to(self):
		"""Gate 8 criterion 4.

		A correction lands on the day it happened, not the day it arrived, and the next rollup
		notices because the fingerprint of that day has moved.
		"""
		yesterday = add_days(today(), -1)
		kpi_service.roll_up(self.rep.name, yesterday)
		before = flt(frappe.db.get_value(
			"FieldMate KPI Snapshot",
			{"field_user": self.rep.name, "snapshot_date": yesterday}, "order_value"))

		self.book_on(yesterday)
		rewritten = kpi_service.roll_up(self.rep.name, yesterday)
		after = flt(frappe.db.get_value(
			"FieldMate KPI Snapshot",
			{"field_user": self.rep.name, "snapshot_date": yesterday}, "order_value"))

		self.assertEqual(before, 0)
		self.assertTrue(rewritten, "the day changed, so it had to be recounted")
		self.assertGreater(after, 0)

	def test_the_fingerprint_moves_when_the_day_does(self):
		yesterday = add_days(today(), -1)
		before = kpi_service.fingerprint(self.rep.name, yesterday)
		self.book_on(yesterday)
		self.assertNotEqual(kpi_service.fingerprint(self.rep.name, yesterday), before)


class TestAMonthIsTheDaysAddedUp(KpiFixture):
	def test_counts_add_up_across_days(self):
		for back in range(3):
			day = add_days(today(), -back)
			self.book_on(day)
			kpi_service.roll_up(self.rep.name, day)

		result = kpi_service.period(self.rep.name, add_days(today(), -2), today())

		self.assertEqual(result["totals"]["orders_count"], 3)
		self.assertEqual(result["totals"]["days"], 3)

	def test_a_ratio_is_recomputed_from_the_totals_not_averaged(self):
		"""The whole reason both halves of every ratio are stored.

		One call converted, then twelve with three converted, is 4 in 13 - not the average of
		100% and 25%, which would say 62.5%.
		"""
		summary = kpi_service.aggregate([
			{"productive_visits": 1, "actual_visits": 1},
			{"productive_visits": 3, "actual_visits": 12},
		])
		self.assertEqual(summary["productive_pct"], kpi_service.pct(4, 13))
		self.assertNotEqual(summary["productive_pct"], 62.5)

	def test_monthly_coverage_counts_a_shop_once_however_often_it_was_billed(self):
		"""The daily sum cannot answer this: a shop billed on Monday and Friday is two there."""
		for _ in range(3):
			self.another_shop()

		for back in range(2):
			day = add_days(today(), -back)
			self.book_on(day)
			kpi_service.roll_up(self.rep.name, day)

		result = kpi_service.period(self.rep.name, add_days(today(), -1), today())

		self.assertEqual(result["totals"]["outlets_billed"], 2, "the daily sum double-counts")
		self.assertEqual(result["totals"]["outlets_covered"], 1, "one shop was covered")
		self.assertEqual(result["totals"]["coverage_pct"], 25.0)

	def test_coverage_base_is_not_added_across_days(self):
		"""Four shops in a territory is four, whether the window is a day or a month."""
		for _ in range(3):
			self.another_shop()
		for back in range(3):
			kpi_service.roll_up(self.rep.name, add_days(today(), -back))

		result = kpi_service.period(self.rep.name, add_days(today(), -2), today())
		self.assertEqual(result["totals"]["outlets_in_scope"], 4)


class TestNothingElseCountsForItself(KpiFixture):
	"""Gate 8 criterion 3, as far as a unit test can carry it.

	The gate greps the shipped charts and cards; this asserts the reading side of the app - the
	manager's summary and the rep's month - answers from the snapshot rather than from raw
	documents.
	"""

	def test_the_month_reads_snapshots_and_not_orders(self):
		self.book_on(today())
		# Deliberately not rolled up. If `period` were counting orders, it would see this.
		result = kpi_service.period(self.rep.name, today(), today())
		self.assertEqual(result["totals"]["orders_count"], 0,
		                 "the month must read the table, not the documents")

		kpi_service.roll_up(self.rep.name, today())
		after = kpi_service.period(self.rep.name, today(), today())
		self.assertEqual(after["totals"]["orders_count"], 1)

	def test_today_is_the_one_view_that_measures_live(self):
		"""The rep is looking at the last hour. Last night's row is the one number they would
		immediately know to be wrong."""
		self.book_on(today())
		live = kpi_service.today_for(self.rep.name, today())
		self.assertEqual(live["orders_count"], 1, "today is counted fresh, on purpose")


class TestWhatAShopAlreadyOwed(KpiFixture):
	"""The other half of the collection base, which was always zero.

	`_billable_base` is "what the shops already owed, plus what was billed today", and the first
	half is read out of `FieldMate Outstanding Snapshot`. Nothing ever wrote that table:
	`collection.snapshot_outstanding` existed, was tested, and was wired to no scheduler. So
	collection efficiency has been measured against the day's own billing alone since it was
	built - and no test noticed, because none of them looked at the figure.
	"""

	def tearDown(self):
		self.wipe_since_setup("FieldMate Outstanding Snapshot")
		super().tearDown()

	def owed_before(self, outlet, amount, on):
		"""A position frozen on an earlier day, the way the nightly job leaves one."""
		doc = frappe.get_doc({
			"doctype": "FieldMate Outstanding Snapshot",
			"as_of": on, "party_type": "Outlet", "party": outlet, "outlet": outlet,
			"distributor": frappe.db.get_value("FieldMate Outlet", outlet, "distributor"),
			"outstanding_amount": amount, "source": "Soft Ledger",
		})
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc.name

	def test_the_scheduler_runs_it_before_the_rollup(self):
		"""Order is the whole point: the rollup reads what this writes."""
		from fieldmate import hooks

		daily = hooks.scheduler_events["daily"]
		self.assertIn("fieldmate.tasks.snapshot_outstanding", daily)
		self.assertLess(daily.index("fieldmate.tasks.snapshot_outstanding"),
		                daily.index("fieldmate.tasks.roll_up_kpis"),
		                "the rollup would read yesterday's position as today's")

	def test_the_task_exists_and_calls_the_service(self):
		from fieldmate import tasks

		self.assertTrue(callable(tasks.snapshot_outstanding))

	def test_what_was_owed_before_is_part_of_the_base(self):
		"""The bug, stated as a number. 600 owed yesterday, 2000 billed today, base 2600."""
		day = today()
		self.owed_before(self.outlet.name, 600, add_days(day, -1))
		self.book_on(day, qty=20)  # 20 x 100

		orders = frappe.get_all(
			"FieldMate Order",
			filters={"field_user": self.rep.name, "order_date": day, "docstatus": 1},
			fields=["outlet", "net_total"])
		base = kpi_service._billable_base(self.rep.name, day, orders)

		billed = sum(flt(o.net_total) for o in orders)
		self.assertEqual(billed, 2000)
		self.assertEqual(base, 2600)

	def test_the_newest_position_at_or_before_the_day_is_the_one_used(self):
		"""Two snapshots for one shop. The later one is the position; they do not add up."""
		day = today()
		self.owed_before(self.outlet.name, 900, add_days(day, -5))
		self.owed_before(self.outlet.name, 400, add_days(day, -1))
		self.book_on(day, qty=20)

		orders = frappe.get_all(
			"FieldMate Order",
			filters={"field_user": self.rep.name, "order_date": day, "docstatus": 1},
			fields=["outlet", "net_total"])

		self.assertEqual(kpi_service._billable_base(self.rep.name, day, orders), 2400)

	def test_a_position_recorded_after_the_day_is_not_used(self):
		"""Measuring last Tuesday must not read a figure frozen this morning."""
		day = add_days(today(), -3)
		self.owed_before(self.outlet.name, 700, add_days(today(), -1))
		self.book_on(day, qty=20)

		orders = frappe.get_all(
			"FieldMate Order",
			filters={"field_user": self.rep.name, "order_date": day, "docstatus": 1},
			fields=["outlet", "net_total"])

		self.assertEqual(kpi_service._billable_base(self.rep.name, day, orders), 2000)

	def test_two_shops_each_bring_their_own_position(self):
		"""And the batched read must not lose one of them."""
		day = today()
		other = self.another_shop()
		self.owed_before(self.outlet.name, 300, add_days(day, -1))
		self.owed_before(other.name, 500, add_days(day, -1))
		self.book_on(day, qty=10)
		self.book_on(day, outlet=other.name, qty=10)

		orders = frappe.get_all(
			"FieldMate Order",
			filters={"field_user": self.rep.name, "order_date": day, "docstatus": 1},
			fields=["outlet", "net_total"])

		# 1000 + 1000 billed, 300 + 500 already owed.
		self.assertEqual(kpi_service._billable_base(self.rep.name, day, orders), 2800)

	def test_the_job_actually_writes_a_position(self):
		"""End to end: an unpaid order, the nightly job, a row to read tomorrow."""
		from fieldmate.services import collection as collection_service

		self.book_on(today(), qty=20)
		result = collection_service.snapshot_outstanding()

		self.assertGreaterEqual(result["written"], 1)
		self.assertTrue(frappe.db.exists("FieldMate Outstanding Snapshot", {
			"outlet": self.outlet.name, "as_of": today()}))
