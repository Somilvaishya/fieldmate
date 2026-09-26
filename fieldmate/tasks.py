"""Scheduled work. Thin wrappers so hooks.py names something stable."""

import frappe

from fieldmate.services import day as day_service
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
