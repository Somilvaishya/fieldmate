"""Reading a distributor's secondary sales file.

No two distributors export the same headers, and none of them will change their export for us.
So the column names are configuration, not code: a standard set of names is understood out of
the box, a per-distributor mapping overrides it, and anything still unrecognised is reported by
name rather than guessed at.

The rule that shapes everything here: **a bad row must not cost the good ones.** A file of 347
lines with 3 broken ones imports 344 and reports the 3 with their row numbers and reasons
(Gate 5 criterion 1). A distributor who has to fix and resend the whole file simply stops
sending files.

Nothing in this module posts. These are the distributor's sales, not ours.
"""

from __future__ import annotations

import csv
import io

import frappe
from frappe.utils import flt, getdate

# What we understand without being told. Everything is matched case-insensitively with spaces,
# underscores and hyphens treated alike, because "Item Code", "item_code" and "ITEM-CODE" are the
# same column and arguing about it helps nobody.
STANDARD = {
	"date": ("date", "sale date", "invoice date", "bill date", "txn date"),
	"item_code": ("item code", "item", "sku", "sku code", "product code", "material"),
	"qty": ("qty", "quantity", "sold qty", "sale qty", "billed qty"),
	"uom": ("uom", "unit", "unit of measure"),
	"amount": ("amount", "value", "net amount", "sale value", "taxable value"),
	"retailer_name": ("retailer name", "shop name", "customer name", "party name", "retailer"),
	"retailer_code": ("retailer code", "shop code", "customer code", "party code"),
	"invoice_no": ("invoice no", "invoice", "bill no", "bill number", "document no"),
}

REQUIRED = ("date", "item_code", "qty")


def template() -> dict:
	"""What a sales file may be headed with, and one filled row showing it.

	Every spelling this reader already understands, not one canonical set: no two distributors
	export the same headers and none of them will change their export for us, so the point is to
	show a depot that theirs is probably already accepted rather than to hand them a format to
	convert to. A depot that has to rewrite its export stops sending files.
	"""
	return {
		"columns": list(STANDARD),
		"required": list(REQUIRED),
		"accepted_headers": {field: list(names) for field, names in STANDARD.items()},
		"example": {
			"date": "2026-10-01",
			"item_code": "<an item code we hold>",
			"qty": "12",
			"uom": "Nos",
			"amount": "1440.00",
			"retailer_name": "Sharma Kirana Store",
			"retailer_code": "R-1042",
			"invoice_no": "INV-2026-00871",
		},
	}


def normalise(header: str) -> str:
	return " ".join(str(header or "").strip().lower().replace("_", " ").replace("-", " ").split())


def build_mapping(headers: list[str], overrides: dict | None = None) -> tuple[dict, list[str]]:
	"""Column index per field, plus the headers we could make nothing of.

	Unrecognised columns are returned rather than ignored. A distributor whose quantity column is
	called "Nos." deserves to be told that is why nothing imported, instead of being handed an
	empty document.
	"""
	overrides = {normalise(k): v for k, v in (overrides or {}).items()}
	mapping: dict[str, int] = {}
	unknown: list[str] = []

	for index, raw in enumerate(headers):
		key = normalise(raw)
		if not key:
			continue
		field = overrides.get(key)
		if not field:
			field = next((name for name, aliases in STANDARD.items() if key in aliases), None)
		if field:
			mapping.setdefault(field, index)
		else:
			unknown.append(str(raw).strip())

	return mapping, unknown


def read_rows(content: bytes | str) -> tuple[list[str], list[list[str]]]:
	"""Header row and body, from CSV text.

	A spreadsheet is saved as CSV before it reaches here. Excel parsing is a dependency and a
	class of bug we do not need in the path a month's sales figures travel through.
	"""
	if isinstance(content, bytes):
		# Excel writes a BOM on "CSV UTF-8", which otherwise turns the first header into
		# "﻿Date" and makes the date column vanish for no visible reason.
		text = content.decode("utf-8-sig", errors="replace")
	else:
		text = content

	rows = [row for row in csv.reader(io.StringIO(text)) if any((cell or "").strip() for cell in row)]
	if not rows:
		return [], []
	return rows[0], rows[1:]


def parse(content, distributor: str, overrides: dict | None = None) -> dict:
	"""Turn a file into lines we can save, and a list of what we could not.

	Pure: reads nothing but Items and Outlets, writes nothing. The caller decides whether to keep
	the result.
	"""
	headers, body = read_rows(content)
	if not headers:
		return {"lines": [], "rejected": [{"row": 0, "reason": "The file is empty."}],
		        "mapping": {}, "unknown_columns": []}

	mapping, unknown = build_mapping(headers, overrides)

	missing = [field for field in REQUIRED if field not in mapping]
	if missing:
		names = ", ".join(missing)
		hint = f" Columns we did not recognise: {', '.join(unknown)}." if unknown else ""
		return {
			"lines": [],
			"rejected": [{"row": 1, "reason": f"The file has no {names} column.{hint}"}],
			"mapping": mapping,
			"unknown_columns": unknown,
		}

	codes = known_item_codes()
	shops = outlets_for(distributor)

	lines, rejected = [], []
	for offset, raw in enumerate(body):
		# +2: row 1 is the header, and a person counting rows in a spreadsheet starts at 1.
		row_no = offset + 2
		line, reason = parse_row(raw, mapping, codes, shops, row_no)
		if reason:
			rejected.append({"row": row_no, "reason": reason})
		else:
			lines.append(line)

	return {"lines": lines, "rejected": rejected, "mapping": mapping, "unknown_columns": unknown}


def parse_row(raw: list, mapping: dict, codes: dict, shops: dict, row_no: int):
	def cell(field):
		index = mapping.get(field)
		if index is None or index >= len(raw):
			return ""
		return (raw[index] or "").strip()

	code_raw = cell("item_code")
	if not code_raw:
		return None, "No item code."
	item_code = codes.get(code_raw.strip().lower())
	if not item_code:
		return None, f"We do not have an item called {code_raw}."

	qty_raw = cell("qty")
	try:
		# Indian exports routinely carry thousands separators, and a stray one would otherwise
		# turn 1,200 into 1.
		qty = float(qty_raw.replace(",", ""))
	except (TypeError, ValueError):
		return None, f"Quantity {qty_raw!r} is not a number."
	if qty <= 0:
		return None, f"Quantity is {qty_raw}. A sale of nothing is not a sale."

	try:
		sale_date = getdate(cell("date"))
	except Exception:
		return None, f"Date {cell('date')!r} is not a date we can read."

	retailer_code = cell("retailer_code")
	retailer_name = cell("retailer_name")
	return {
		"sale_date": sale_date,
		"item_code": item_code,
		"qty": qty,
		"uom": cell("uom") or None,
		"amount": flt((cell("amount") or "0").replace(",", "")),
		"retailer_name": retailer_name or None,
		"retailer_code": retailer_code or None,
		# Matched where we can, blank where we cannot, and blank is normal. Most distributors
		# have no shop id in common with us at all.
		"outlet": shops.get(retailer_code.lower()) or shops.get(retailer_name.lower()),
		"invoice_no": cell("invoice_no") or None,
		"source_row": row_no,
	}, None


def known_item_codes() -> dict:
	"""Item codes keyed lowercase, so a file that shouts SE-1000 still matches."""
	return {row.name.lower(): row.name for row in frappe.get_all("Item", fields=["name"])}


def outlets_for(distributor: str) -> dict:
	"""This distributor's shops, keyed by anything a file might name them with.

	Only their own shops: matching across distributors would attach one distributor's sales to
	another's outlet, and the mistake would be invisible in every report afterwards.
	"""
	if not frappe.db.exists("Customer", distributor):
		return {}

	shops = {}
	for row in frappe.get_all(
		"FieldMate Outlet",
		filters={"distributor": distributor},
		fields=["name", "outlet_name", "outlet_code"] if
		frappe.get_meta("FieldMate Outlet").has_field("outlet_code")
		else ["name", "outlet_name"],
	):
		shops[row.name.lower()] = row.name
		if row.outlet_name:
			shops[row.outlet_name.strip().lower()] = row.name
		if row.get("outlet_code"):
			shops[row.outlet_code.strip().lower()] = row.name
	return shops


def import_file(distributor: str, content, from_date, to_date, file_name=None,
                overrides: dict | None = None, company: str | None = None) -> dict:
	"""Parse a file and save what we could read.

	A document is created even when some rows failed, carrying both counts and every rejection
	with its row number. Refusing the whole file over three bad lines is how a distributor stops
	sending them.
	"""
	result = parse(content, distributor, overrides)
	if not result["lines"]:
		reasons = "; ".join(f"row {r['row']}: {r['reason']}" for r in result["rejected"][:5])
		frappe.throw(frappe._("Nothing in that file could be read. {0}").format(reasons))

	doc = frappe.get_doc({
		"doctype": "FieldMate Secondary Sales",
		"distributor": distributor,
		"from_date": from_date,
		"to_date": to_date,
		"company": company,
		"source": "File Upload",
		"file_name": file_name,
		"items": result["lines"],
		"rows_read": len(result["lines"]) + len(result["rejected"]),
		"rows_rejected": len(result["rejected"]),
		"rejections": "\n".join(
			f"Row {r['row']}: {r['reason']}" for r in result["rejected"]
		) or None,
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	doc.submit()

	return {
		"name": doc.name,
		"imported": len(result["lines"]),
		"rejected": result["rejected"],
		"unknown_columns": result["unknown_columns"],
		"matched_outlets": doc.matched_outlets,
	}
