"""Scheduled work. Thin wrappers so hooks.py names something stable."""

import frappe

from fieldmate.services import alerts as alerts_service
from fieldmate.services import collection as collection_service
from fieldmate.services import day as day_service
from fieldmate.services import kpi as kpi_service
from fieldmate.services import settings as settings_service
from fieldmate.services import target as target_service
from fieldmate.services import trail as trail_service


def close_stale_days():
	closed = day_service.auto_close_stale_days()
	if closed:
		frappe.logger("fieldmate").info(f"auto-closed {closed} stale days")


def purge_old_trails():
	days = settings_service.value("gps_trail_retention_days")
	removed = trail_service.purge_older_than(days)
	if removed:
		frappe.logger("fieldmate").info(f"purged {removed} location trails older than {days} days")


def measure_targets():
	"""Re-measure every target plan whose period covers today.

	It logs how long it took as well as what it did, because Gate 7 asks that 250 reps finish
	inside ten minutes and the only honest way to know is to have been measuring all along on a
	real site rather than once, on a good day, under a stopwatch.
	"""
	started = frappe.utils.now_datetime()
	result = target_service.compute_all()
	seconds = (frappe.utils.now_datetime() - started).total_seconds()

	frappe.logger("fieldmate").info(
		f"measured {result['computed']} of {result['plans']} target plans in {seconds:.1f}s"
		+ (f", {len(result['failed'])} failed" if result["failed"] else ""))
	if result["failed"]:
		frappe.log_error(
			title="fieldmate measure_targets",
			message="These plans could not be measured:\n" + "\n".join(result["failed"]))


def snapshot_outstanding():
	"""Freeze what every shop owes, before the rollup reads it.

	This has to run **before** `roll_up_kpis` in the daily list. The rollup answers "what is owed"
	as the last recorded position plus what was billed today, and it reads that first half out of
	this table.

	It is listed here because it was not listed anywhere: the service function existed, the
	DocType existed, `kpi` read it, and nothing wrote it - so the owed figure on every rep's day
	has been the day's own billing and nothing else since the KPI was built.
	"""
	result = collection_service.snapshot_outstanding()
	if result["written"]:
		frappe.logger("fieldmate").info(
			f"froze {result['written']} outlet position(s) as of {result['as_of']}")


def roll_up_kpis():
	"""Rebuild the KPI snapshot for the last few days, every night.

	A window rather than only yesterday: a day is corrected after it ends - an order pushed from
	a phone that had no signal, a visit a manager amended - and a job that only looked at
	yesterday would leave those corrections invisible for ever. The fingerprint on each row
	makes the days nobody touched nearly free (Gate 8 criterion 4).
	"""
	started = frappe.utils.now_datetime()
	result = kpi_service.roll_up_all(days_back=7)
	seconds = (frappe.utils.now_datetime() - started).total_seconds()

	frappe.logger("fieldmate").info(
		f"rolled up {result['written']} rep-days for {result['reps']} reps in {seconds:.1f}s "
		f"({result['unchanged']} unchanged)"
		+ (f", {len(result['failed'])} failed" if result["failed"] else ""))
	if result["failed"]:
		frappe.log_error(
			title="fieldmate roll_up_kpis",
			message="These reps could not be rolled up:\n" + "\n".join(result["failed"]))


def refresh_today_kpis():
	"""Today only, hourly, so a manager's screen is never more than an hour stale."""
	result = kpi_service.roll_up_all(days_back=1)
	if result["written"]:
		frappe.logger("fieldmate").info(f"refreshed {result['written']} rep-days for today")


def run_alerts():
	"""Evaluate every active rule over the last few days.

	The same window as the rollup, and for the same reason: a snapshot recomputed at noon can
	turn an ordinary day into an exception. Re-running is free - an occurrence already logged is
	refused by a unique key rather than duplicated (Gate 8 criterion 5).
	"""
	result = alerts_service.evaluate_all(days_back=3)
	if result["fired"]:
		frappe.logger("fieldmate").info(
			f"{result['fired']} alerts fired across {result['rules']} rules "
			f"({result['already_logged']} were already logged)")


def remind_booking_payments():
	"""Daily. Tell the rep and their manager about a season booking whose money is late.

	Read off the Sales Order's own payment schedule, which ERPNext built from the season's
	Payment Terms Template - the schedule finance maintains is the one that decides when money
	is late, and a second copy of it here would be a second thing to keep in step.
	"""
	from fieldmate.services import cockpit as cockpit_service

	answer = cockpit_service.remind_overdue()
	if answer["overdue"]:
		print(f"  FieldMate: {answer['overdue']} booking(s) overdue, {answer['told']} told")
