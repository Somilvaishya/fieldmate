"""Bulk import of outlets and beats.

Gate 1 asks that 5,000 outlets and 200 beats import with zero manual correction. That is really
a demand about *reporting*: the importer must say exactly which row failed and why, in terms the
person holding the spreadsheet can act on, rather than failing the file.

So every run validates the whole file first and reports per row. A bad row never takes the good
rows with it, and a dry run tells you what would happen before anything is written.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt

OUTLET_COLUMNS = [
	"outlet_name", "mobile_no", "distributor", "territory",
	"channel", "outlet_class", "outlet_type", "owner_name",
	"address_line1", "city", "district", "state", "pincode",
	"latitude", "longitude", "monthly_potential", "gstin", "client_uuid",
]

BEAT_COLUMNS = ["beat_name", "territory", "assigned_to", "frequency", "visit_day", "outlets"]

REQUIRED_OUTLET = ("outlet_name", "mobile_no", "distributor", "territory")


def outlet_template() -> dict:
	"""Column list plus one filled example row, so the header is never guessed."""
	return {
		"columns": OUTLET_COLUMNS,
		"required": list(REQUIRED_OUTLET),
		"example": {
			"outlet_name": "Sharma Kirana Store",
			"mobile_no": "9812345678",
			"distributor": "<existing Customer name>",
			"territory": "<existing Territory name>",
			"channel": "Kirana",
			"outlet_class": "A",
			"outlet_type": "Kirana",
			"owner_name": "Ramesh Sharma",
			"address_line1": "12 Model Town",
			"city": "Delhi",
			"district": "North Delhi",
			"state": "Delhi",
			"pincode": "110009",
			"latitude": "28.7041",
			"longitude": "77.1025",
			"monthly_potential": "45000",
			"gstin": "",
			"client_uuid": "",
		},
	}


def validate_outlets(rows: list[dict]) -> list[dict]:
	"""Per-row problems, each naming the row number, the column and what to do.

	Row numbers are 1-based and count the header, matching what the spreadsheet shows.
	"""
	problems: list[dict] = []
	seen_names: dict[str, int] = {}

	territories = set(frappe.get_all("Territory", pluck="name"))
	customers = set(frappe.get_all("Customer", pluck="name"))
	channels = set(frappe.get_all("FieldMate Outlet Channel", pluck="name"))
	classes = set(frappe.get_all("FieldMate Outlet Class", pluck="name"))

	for index, row in enumerate(rows, start=2):
		def fail(column, message):
			problems.append({"row": index, "column": column, "message": message})

		for column in REQUIRED_OUTLET:
			if not str(row.get(column) or "").strip():
				fail(column, f"{column} is required")

		name = str(row.get("outlet_name") or "").strip().lower()
		mobile = str(row.get("mobile_no") or "").strip()

		if name and mobile:
			key = f"{name}|{mobile}"
			if key in seen_names:
				fail("outlet_name", f"same shop and mobile as row {seen_names[key]}")
			else:
				seen_names[key] = index

		if mobile and not (mobile.isdigit() and 7 <= len(mobile) <= 15):
			fail("mobile_no", "must be 7 to 15 digits, no spaces or symbols")

		territory = str(row.get("territory") or "").strip()
		if territory and territory not in territories:
			fail("territory", f"'{territory}' does not exist. Create it first.")

		distributor = str(row.get("distributor") or "").strip()
		if distributor and distributor not in customers:
			fail("distributor", f"'{distributor}' is not an existing Customer.")

		channel = str(row.get("channel") or "").strip()
		if channel and channel not in channels:
			fail("channel", f"'{channel}' is not a known channel.")

		outlet_class = str(row.get("outlet_class") or "").strip()
		if outlet_class and outlet_class not in classes:
			fail("outlet_class", f"'{outlet_class}' is not a known class.")

		# Geo is the field that most often arrives wrong, and a bad pin sends a rep to the
		# wrong street, so it is checked hard rather than coerced.
		lat, lon = row.get("latitude"), row.get("longitude")
		if (lat in (None, "")) != (lon in (None, "")):
			fail("latitude", "latitude and longitude must be given together")
		elif lat not in (None, ""):
			try:
				lat_f, lon_f = flt(lat), flt(lon)
			except Exception:
				fail("latitude", "not a number")
			else:
				if not (-90 <= lat_f <= 90):
					fail("latitude", f"{lat_f} is outside -90 to 90")
				if not (-180 <= lon_f <= 180):
					fail("longitude", f"{lon_f} is outside -180 to 180")
				if lat_f == 0 and lon_f == 0:
					fail("latitude", "0,0 is in the Atlantic. Leave both blank instead.")

		pincode = str(row.get("pincode") or "").strip()
		if pincode and not (pincode.isdigit() and len(pincode) == 6):
			fail("pincode", "must be 6 digits")

	return problems


def import_outlets(rows: list[dict], dry_run: bool = False) -> dict:
	"""Validate everything, then write the rows that passed.

	A bad row is reported and skipped; it never takes the good rows with it.
	"""
	problems = validate_outlets(rows)
	bad_rows = {p["row"] for p in problems}

	result = {
		"total": len(rows),
		"valid": len(rows) - len(bad_rows),
		"failed": len(bad_rows),
		"errors": problems,
		"created": [],
		"skipped_existing": [],
		"dry_run": dry_run,
	}

	if dry_run:
		return result

	for index, row in enumerate(rows, start=2):
		if index in bad_rows:
			continue

		client_uuid = str(row.get("client_uuid") or "").strip() or None
		if client_uuid:
			existing = frappe.db.get_value("FieldMate Outlet", {"client_uuid": client_uuid}, "name")
			if existing:
				result["skipped_existing"].append({"row": index, "name": existing})
				continue

		data = {"doctype": "FieldMate Outlet", "approval_status": "Approved"}
		for column in OUTLET_COLUMNS:
			value = row.get(column)
			if value not in (None, ""):
				data[column] = value
		data["client_uuid"] = client_uuid

		try:
			doc = frappe.get_doc(data)
			doc.insert(ignore_permissions=True)
			result["created"].append({"row": index, "name": doc.name})
		except Exception as e:
			# Anything validation did not foresee still reports as a row, not a stack trace.
			result["errors"].append({"row": index, "column": "", "message": str(e)[:200]})
			result["valid"] -= 1
			result["failed"] += 1

	return result


def import_beats(rows: list[dict], dry_run: bool = False) -> dict:
	"""Beats, with their outlet list given as a comma-separated column."""
	result = {"total": len(rows), "created": [], "errors": [], "dry_run": dry_run}

	for index, row in enumerate(rows, start=2):
		def fail(message, column=""):
			result["errors"].append({"row": index, "column": column, "message": message})

		if not str(row.get("beat_name") or "").strip():
			fail("beat_name is required", "beat_name")
			continue
		if not frappe.db.exists("Territory", row.get("territory")):
			fail(f"territory '{row.get('territory')}' does not exist", "territory")
			continue
		if not frappe.db.exists("FieldMate Field User", row.get("assigned_to")):
			fail(f"assigned_to '{row.get('assigned_to')}' is not a field user", "assigned_to")
			continue

		names = [n.strip() for n in str(row.get("outlets") or "").split(",") if n.strip()]
		missing = [n for n in names if not frappe.db.exists("FieldMate Outlet", n)]
		if missing:
			fail(f"unknown outlets: {', '.join(missing[:5])}", "outlets")
			continue

		if dry_run:
			continue

		try:
			doc = frappe.get_doc({
				"doctype": "FieldMate Beat",
				"beat_name": row["beat_name"],
				"territory": row["territory"],
				"assigned_to": row["assigned_to"],
				"frequency": row.get("frequency") or "Weekly",
				"visit_day": row.get("visit_day") or "Monday",
				"outlets": [{"outlet": n} for n in names],
			})
			doc.insert(ignore_permissions=True)
			result["created"].append({"row": index, "name": doc.name})
		except Exception as e:
			fail(str(e)[:200])

	result["failed"] = len({e["row"] for e in result["errors"]})
	result["valid"] = result["total"] - cint(result["failed"])
	return result
