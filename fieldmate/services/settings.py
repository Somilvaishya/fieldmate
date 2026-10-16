"""Reading FieldMate Settings, and resolving a rep's sales mode.

Settings are read on every bootstrap and on every credit check, so this caches. The cache is
cleared by FieldMateSettings.on_update.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint

# The two kinds of sale, and the whole of what distinguishes them: who we bill.
#
# SECONDARY - the rep books at a kirana, the distributor delivers and bills it, and our books
#             never see that sale. This is what the app has always done.
# PRIMARY   - the rep books on a super stockist, distributor or wholesaler and WE bill them. The
#             order becomes a real Sales Order, so credit, GST and the ledger all apply.
#
# Which one an order is follows from the party it is booked on, never from a setting. The
# settings below say which kinds this site is allowed to make at all.
SECONDARY = "Secondary"
PRIMARY = "Primary"
# BOOKING   - a primary order dated inside an open season (Phase 2). It is a primary sale in
#             every way that matters - we bill it, it posts a Sales Order, the same switch
#             governs it - and it is a separate word only because the season changes the price
#             list, the delivery dates and when the rates stop moving.
#
#             Defined here with the other two on purpose. It lived in `services/season` for one
#             afternoon, and in that time `we_are_the_seller` compared `kind == PRIMARY` and
#             quietly stopped posting a Sales Order for every booking: a string equality where
#             the question was "is this ours to bill". Ask `is_primary`, never `== PRIMARY`.
BOOKING = "Booking"


def is_primary(kind: str | None) -> bool:
	"""Is this a sale WE bill - as opposed to the distributor's own sale to a shop?

	True for a plain primary order and for a season booking. Everything that follows from being
	the seller follows for both: the credit limit measured is the party's, a Sales Order is
	posted, and our books see the sale.
	"""
	return kind in (PRIMARY, BOOKING)

# Kept for the one caller that still reads it. `resolve_sales_mode` goes when `channel.resolve`
# lands and every caller asks about a party instead of about the company.
ORDER_BOOKING = SECONDARY

# Mirrors the DocType defaults so a site that has never opened the form still behaves sanely.
DEFAULTS = {
	"enable_secondary_sales": 1,
	"enable_primary_sales": 0,
	"enforce_geo_fence": 1,
	"default_geo_fence_radius_m": 100,
	"allow_geo_fence_exception": 1,
	"min_visit_duration_minutes": 3,
	"flag_mock_location": 1,
	"require_day_start_selfie": 1,
	"require_visit_selfie": 0,
	"auto_close_day_after_hours": 14,
	"track_gps_trail": 1,
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
	extra = ("default_company", "default_price_list", "default_warehouse",
	         "default_location",
	         "support_contact", "day_start_alert_time",
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
	"""The kinds of sale this site is allowed to make."""
	settings = get()
	modes = []
	if cint(settings.get("enable_secondary_sales")):
		modes.append(SECONDARY)
	if cint(settings.get("enable_primary_sales")):
		modes.append(PRIMARY)
	return modes


def allows(kind: str) -> bool:
	"""Is this kind of sale switched on here?

	Asked before an order is priced, not after it is built. A rep who cannot book a primary order
	should be told at the party, not at the till.
	"""
	# A booking is a primary sale, so `enable_primary_sales` is the switch that governs it.
	# There is no third switch and there should not be one: a company either sells to its
	# distributors or it does not, and a season does not change that.
	return (PRIMARY if kind == BOOKING else kind) in enabled_modes()


def resolve_sales_mode(field_user: str | None = None) -> str:
	"""How this rep sells.

	A placeholder with one answer. The kind of a sale follows from the party it is booked on, and
	`channel.resolve` is what will answer that; this stays only until its callers have been moved
	across, so that the switch is one change rather than five.
	"""
	return SECONDARY


def client_settings() -> dict:
	"""The subset the PWA needs. Retention and company config stay on the server."""
	s = get()
	return {
		"geo_fence_radius_m": cint(s["default_geo_fence_radius_m"]),
		"enforce_geo_fence": bool(cint(s["enforce_geo_fence"])),
		"min_visit_duration_minutes": cint(s["min_visit_duration_minutes"]),
		"require_day_start_selfie": bool(cint(s["require_day_start_selfie"])),
		"require_visit_selfie": bool(cint(s["require_visit_selfie"])),
		"track_gps_trail": bool(cint(s["track_gps_trail"])),
		"gps_ping_interval_seconds": cint(s["gps_ping_interval_seconds"]),
		"sync_batch_size": cint(s["sync_batch_size"]),
		"sync_max_retries": cint(s["sync_max_retries"]),
		"photo_max_kb": cint(s["photo_max_kb"]),
		"photo_max_dimension_px": cint(s["photo_max_dimension_px"]),
		"support_contact": s.get("support_contact"),
	}
