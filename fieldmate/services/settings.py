"""Reading FieldMate Settings, and resolving a rep's sales mode.

Settings are read on every bootstrap and on every credit check, so this caches. The cache is
cleared by FieldMateSettings.on_update.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

ORDER_BOOKING = "Order Booking"
VAN_SALES = "Van Sales"

# Mirrors the DocType defaults so a site that has never opened the form still behaves sanely.
DEFAULTS = {
	"enable_order_booking": 1,
	"enable_van_sales": 0,
	"default_sales_mode": ORDER_BOOKING,
	"enforce_geo_fence": 1,
	"default_geo_fence_radius_m": 100,
	"allow_geo_fence_exception": 1,
	"min_visit_duration_minutes": 3,
	"flag_mock_location": 1,
	"require_day_start_selfie": 1,
	"auto_close_day_after_hours": 14,
	"gps_ping_interval_seconds": 90,
	"block_order_on_credit_breach": 1,
	"allow_credit_override": 1,
	"sync_batch_size": 50,
	"sync_max_retries": 6,
	"photo_max_kb": 120,
	"photo_max_dimension_px": 1280,
	"gps_trail_retention_days": 180,
	"selfie_retention_days": 30,
	"visit_photo_retention_days": 365,
	# Phase 7. A tolerance and a receipt threshold both have defensible defaults; the three
	# money rates do not, and are in `extra` below so that an unset rate reads as unset rather
	# than as a number this app chose for somebody's reps.
	"expense_receipt_required_above": 500,
	"expense_distance_tolerance_pct": 10,
}


def get() -> dict:
	"""All settings as a plain dict, with defaults filled in."""
	cached = frappe.cache().get_value("fieldmate_settings")
	if cached:
		return cached

	doc = frappe.get_single("FieldMate Settings")
	values = dict(DEFAULTS)
	# Settings with no sensible default, so they are not in DEFAULTS and have to be named here.
	# A field added to the DocType and not added to this tuple reads as unset for ever, which is
	# how Phase 9 shipped a settlement item the claim code could never see - it is worth a moment
	# when adding the next one.
	extra = ("default_company", "default_price_list", "support_contact", "day_start_alert_time",
	         "claim_settlement_item", "claim_expense_account", "claim_cost_center",
	         "travel_rate_per_km", "daily_food_allowance", "daily_stay_allowance")
	for key in (*DEFAULTS, *extra):
		value = doc.get(key)
		if value not in (None, ""):
			values[key] = value

	frappe.cache().set_value("fieldmate_settings", values)
	return values


def value(key: str, default=None):
	return get().get(key, default)


def enabled_modes() -> list[str]:
	settings = get()
	modes = []
	if cint(settings.get("enable_order_booking")):
		modes.append(ORDER_BOOKING)
	if cint(settings.get("enable_van_sales")):
		modes.append(VAN_SALES)
	return modes


def resolve_sales_mode(field_user: str | None = None) -> str:
	"""A rep's own mode wins; otherwise the company default.

	Falls back to whatever is actually enabled rather than trusting a stale rep setting — a rep
	still marked Van Sales after the company switched it off must not be left unable to sell.
	"""
	modes = enabled_modes()
	if not modes:
		return ORDER_BOOKING

	chosen = None
	if field_user and frappe.db.exists("DocType", "FieldMate Field User"):
		chosen = frappe.db.get_value("FieldMate Field User", field_user, "sales_mode")
		if chosen == "Company Default":
			chosen = None

	if not chosen:
		chosen = get().get("default_sales_mode")

	return chosen if chosen in modes else modes[0]


def is_van_sales(field_user: str | None = None) -> bool:
	return resolve_sales_mode(field_user) == VAN_SALES


def client_settings() -> dict:
	"""The subset the PWA needs. Retention and company config stay on the server."""
	s = get()
	return {
		"geo_fence_radius_m": cint(s["default_geo_fence_radius_m"]),
		"enforce_geo_fence": bool(cint(s["enforce_geo_fence"])),
		"min_visit_duration_minutes": cint(s["min_visit_duration_minutes"]),
		"require_day_start_selfie": bool(cint(s["require_day_start_selfie"])),
		"gps_ping_interval_seconds": cint(s["gps_ping_interval_seconds"]),
		"sync_batch_size": cint(s["sync_batch_size"]),
		"sync_max_retries": cint(s["sync_max_retries"]),
		"photo_max_kb": cint(s["photo_max_kb"]),
		"photo_max_dimension_px": cint(s["photo_max_dimension_px"]),
		"support_contact": s.get("support_contact"),
	}
