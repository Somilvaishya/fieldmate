"""Scheduled work. Thin wrappers so hooks.py names something stable."""

import frappe

from fieldmate.services import day as day_service
from fieldmate.services import settings as settings_service
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
