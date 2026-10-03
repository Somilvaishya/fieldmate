"""The GPS trail: one row per rep per day, plus the arithmetic that makes it useful.

Storing a row per ping would add roughly 30 million rows a year at 250 reps pinging every 90
seconds, and every location report would then scan them. The whole day goes on one row as JSON
with the summary figures kept alongside, so reports read the summary and never the path.

The distance here is what expense claims are paid against, so it is computed from the path rather
than typed by the person being reimbursed.
"""

from __future__ import annotations

import itertools
import json
import math

import frappe
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime

EARTH_RADIUS_KM = 6371.0

# Above this, a segment is recorded as implausible. Not proof of anything - GPS drifts badly
# indoors and a bad fix can jump a kilometre - but a day full of them is worth a look.
MAX_PLAUSIBLE_KMPH = 140.0

# Segments shorter than this are dropped from the distance total. A phone sitting on a counter
# wanders a few metres continuously, and summing that noise inflates every expense claim.
MIN_SEGMENT_KM = 0.02

# A fix this coarse is not a GPS fix at all. It is the network's guess from a cell tower or a
# wifi scan, it lands a hundred metres or so from where the phone actually is, and it arrives
# looking exactly like a real fix. The one thing that tells them apart is the accuracy the
# device itself reported, which this file used to record and never read.
#
# Measured on a real day: 93 pings from a rep who never left the office summed to 2.069 km. All
# thirteen jumps over 100 m ran good fix -> acc 100 -> good fix and back, so each excursion was
# paid for twice. Dropping the coarse fixes took the day to 0.000 km, against a net displacement
# of 53 m. At 3.50 a kilometre that difference is the whole of what a travel claim is for.
MAX_ACCURACY_M = 75.0


def haversine_km(lat1, lon1, lat2, lon2) -> float:
	"""Great-circle distance. Straight-line, so it under-reports road travel rather than over."""
	p1, p2 = math.radians(flt(lat1)), math.radians(flt(lat2))
	dp = math.radians(flt(lat2) - flt(lat1))
	dl = math.radians(flt(lon2) - flt(lon1))
	a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
	return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def summarise(pings: list[dict]) -> dict:
	"""Distance, speed and plausibility for an ordered list of pings."""
	clean = [
		p for p in pings
		if p.get("lat") not in (None, "") and p.get("lon") not in (None, "")
	]
	clean.sort(key=lambda p: p.get("t") or "")

	# Kept in the trail, left out of the distance. The row is evidence and deleting it would
	# destroy the record of where the phone said it was; it simply cannot carry the weight of a
	# claim. A fix with no accuracy reported at all is trusted, because older devices sent none
	# and refusing those would silently zero their days.
	usable = [p for p in clean
	          if p.get("acc") in (None, "") or flt(p["acc"]) <= MAX_ACCURACY_M]

	summary = {
		"ping_count": len(clean),
		"coarse_ping_count": len(clean) - len(usable),
		"total_distance_km": 0.0,
		"max_speed_kmph": 0.0,
		"implausible_jumps": 0,
		"mock_ping_count": sum(1 for p in clean if p.get("mock")),
		"first_ping_on": clean[0].get("t") if clean else None,
		"last_ping_on": clean[-1].get("t") if clean else None,
	}

	for previous, current in itertools.pairwise(usable):
		km = haversine_km(previous["lat"], previous["lon"], current["lat"], current["lon"])

		# A move smaller than the combined uncertainty of the two fixes that describe it is not
		# evidence of a move. Two fixes 25 m apart, each good to 16 m, say nothing. The flat 20 m
		# floor still applies underneath, for devices that report no accuracy.
		floor = MIN_SEGMENT_KM
		slack = flt(previous.get("acc") or 0) + flt(current.get("acc") or 0)
		if slack:
			floor = max(floor, slack / 1000.0)
		if km < floor:
			continue

		seconds = 0.0
		if previous.get("t") and current.get("t"):
			try:
				seconds = (get_datetime(current["t"]) - get_datetime(previous["t"])).total_seconds()
			except Exception:
				seconds = 0.0

		if seconds > 0:
			kmph = km / (seconds / 3600.0)
			if kmph > MAX_PLAUSIBLE_KMPH:
				# Counted, and excluded from the distance: paying for a teleport would be worse
				# than under-reporting a real drive.
				summary["implausible_jumps"] += 1
				continue
			summary["max_speed_kmph"] = max(summary["max_speed_kmph"], kmph)

		summary["total_distance_km"] += km

	summary["total_distance_km"] = round(summary["total_distance_km"], 3)
	summary["max_speed_kmph"] = round(summary["max_speed_kmph"], 1)
	return summary


def append(field_user: str, pings: list[dict], day_start: str | None = None,
           device_id: str | None = None, trail_date=None) -> dict:
	"""Add a batch of pings to today's trail, creating it if this is the first batch.

	Safe to call repeatedly: pings carrying the same timestamp are not added twice, so a retried
	upload after a dropped connection does not inflate the distance a rep is paid for.
	"""
	trail_date = getdate(trail_date or now_datetime())

	name = frappe.db.get_value(
		"FieldMate Location Trail", {"field_user": field_user, "trail_date": trail_date}, "name"
	)
	if name:
		doc = frappe.get_doc("FieldMate Location Trail", name)
		existing = json.loads(doc.trail or "[]")
	else:
		doc = frappe.new_doc("FieldMate Location Trail")
		doc.field_user = field_user
		doc.trail_date = trail_date
		existing = []

	seen = {p.get("t") for p in existing}
	fresh = [p for p in (pings or []) if p.get("t") not in seen]
	combined = existing + fresh

	summary = summarise(combined)
	doc.trail = json.dumps(combined, separators=(",", ":"), default=str)
	for key, value in summary.items():
		doc.set(key, value)
	if day_start:
		doc.day_start = day_start
	if device_id:
		doc.device_id = device_id

	doc.save(ignore_permissions=True)
	return {"trail": doc.name, "added": len(fresh), "ignored_duplicates": len(pings or []) - len(fresh),
	        **summary}


def distance_for(field_user: str, date) -> float:
	"""Kilometres travelled, for Day End and for expense claims."""
	return flt(frappe.db.get_value(
		"FieldMate Location Trail",
		{"field_user": field_user, "trail_date": getdate(date)},
		"total_distance_km",
	))


def purge_older_than(days: int) -> int:
	"""Delete trails past the retention period. GPS trails track a named employee."""
	if cint(days) < 1:
		return 0
	cutoff = frappe.utils.add_days(frappe.utils.today(), -cint(days))
	names = frappe.get_all(
		"FieldMate Location Trail", filters={"trail_date": ["<", cutoff]}, pluck="name"
	)
	for name in names:
		frappe.delete_doc("FieldMate Location Trail", name, force=True, ignore_permissions=True)
	return len(names)
