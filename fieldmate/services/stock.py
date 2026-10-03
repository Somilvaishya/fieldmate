"""Stock in the field: what a shop holds.

Nothing here posts. A retailer count is measurement - the goods in a shop were never ours - so
what this module owes is arithmetic and honesty about what was actually counted.

The van load and settlement used to live below this and have gone with the mode they served.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, nowdate

from fieldmate import compat
from fieldmate.services import catalogue as catalogue_service
from fieldmate.services import field_user as field_user_service

# --------------------------------------------------------------------------------------
# what a shop holds
# --------------------------------------------------------------------------------------


def sheet_for(outlet, field_user: str | None = None) -> dict:
	"""The stock-count sheet for a shop: every SKU it could hold, and what it held last time.

	The previous count rides along with the list. Fetching it separately would mean a rep in a
	shop with no signal either waits for a second round trip or counts blind, and counting blind
	is how "same as last time" becomes impossible to offer.
	"""
	field_user = field_user or field_user_service.for_user()
	catalogue = catalogue_service.for_outlet(outlet, field_user)
	previous = last_count_for(catalogue["outlet"])

	rows = []
	for item in catalogue.get("items") or []:
		was = previous["items"].get(item["item_code"], {})
		rows.append({
			"item_code": item["item_code"],
			"item_name": item["item_name"],
			"item_group": item.get("item_group"),
			"stock_uom": item.get("stock_uom"),
			"order_uom": item.get("order_uom"),
			"conversion_factor": item.get("conversion_factor") or 1,
			"is_focus": item.get("is_focus"),
			"is_must_sell": item.get("is_must_sell"),
			"last_qty": was.get("qty"),
			"last_display_qty": was.get("qty_display"),
			"last_uom": was.get("display_uom"),
			# Distinguished on purpose. "Never counted here" and "counted at zero" are opposite
			# instructions to a rep, and a Float cannot tell them apart.
			"has_history": bool(was),
			"was_out_of_stock": bool(was.get("is_out_of_stock")),
		})

	return {
		"outlet": catalogue["outlet"],
		"outlet_name": catalogue.get("outlet_name"),
		"items": rows,
		"previous": previous["name"],
		"previous_on": previous["on"],
		"days_since": previous["days_since"],
	}


def last_count_for(outlet) -> dict:
	last = frappe.db.get_value(
		"FieldMate Retailer Stock",
		{"outlet": outlet, "docstatus": 1},
		["name", "stock_date"],
		order_by="stock_date desc",
		as_dict=True,
	)
	if not last:
		return {"name": None, "on": None, "days_since": None, "items": {}}

	rows = frappe.get_all(
		"FieldMate Retailer Stock Item",
		filters={"parent": last.name, "parenttype": "FieldMate Retailer Stock"},
		fields=["item_code", "qty", "qty_display", "display_uom", "is_counted", "is_out_of_stock"],
	)
	return {
		"name": last.name,
		"on": str(last.stock_date),
		"days_since": frappe.utils.date_diff(nowdate(), last.stock_date),
		"items": {row.item_code: row for row in rows if cint(row.is_counted)},
	}


def save_count(payload: dict, field_user: str | None = None) -> dict:
	"""Record a stock count. A partial one is accepted, and says so.

	A rep pulled away halfway through has still learnt something about that shop, and an app
	that refuses the half he did count teaches him to stop starting.
	"""
	field_user = field_user or field_user_service.for_user()
	if not field_user:
		frappe.throw(frappe._("You are not set up as a field user yet. Ask your manager."))

	data = dict(payload or {})
	if not data.get("outlet"):
		frappe.throw(frappe._("A stock count needs a shop."))

	doc = frappe.new_doc("FieldMate Retailer Stock")
	doc.outlet = data["outlet"]
	doc.field_user = field_user
	doc.stock_date = data.get("stock_date") or nowdate()
	doc.visit = data.get("visit")
	doc.remarks = data.get("remarks")
	doc.client_uuid = data.get("client_uuid")
	doc.created_offline = cint(data.get("created_offline"))
	doc.device_id = data.get("device_id")

	for line in data.get("items") or []:
		row = doc.append("items", {})
		row.item_code = line.get("item_code")
		row.qty_display = flt(line.get("qty_display"))
		row.display_uom = line.get("display_uom")
		row.conversion_factor = flt(line.get("conversion_factor")) or 1
		# Sent explicitly by the phone, never inferred from the number. The whole reason this
		# column exists is that zero is a real answer.
		row.is_counted = cint(line.get("is_counted"))
		row.notes = line.get("notes")

	doc.insert()
	# A rep holds create and submit-if-owner and never write (ADR-004), so the server submits on
	# their behalf once it has confirmed the record names them.
	doc.flags.ignore_permissions = True
	doc.submit()
	mark_visit_task(doc)
	return summarise_count(doc)


def mark_visit_task(doc) -> None:
	"""Tick the visit's stock task, so the hub shows the work as done.

	Written straight to the row: the visit is submitted by the time a count is taken, and a rep
	holds no write on it at all. Silent when the visit has no such task - a count taken outside
	a visit is ordinary, and a stock check is not the reason the visit exists.
	"""
	if not doc.visit:
		return
	task = frappe.db.get_value(
		"FieldMate Visit Task",
		{"parent": doc.visit, "parenttype": "FieldMate Visit", "task_type": "Stock Audit"},
		"name",
	)
	if not task:
		return
	frappe.db.set_value("FieldMate Visit Task", task, {
		"status": "Done",
		"completed_on": frappe.utils.now_datetime(),
		"reference_doctype": "FieldMate Retailer Stock",
		"reference_name": doc.name,
	}, update_modified=False)


def summarise_count(doc) -> dict:
	return {
		"name": doc.name,
		"outlet": doc.outlet,
		"stock_date": str(doc.stock_date),
		"counted_lines": cint(doc.counted_lines),
		"total_lines": cint(doc.total_lines),
		"coverage_pct": flt(doc.coverage_pct),
		"is_partial": cint(doc.is_partial),
		"previous_stock": doc.previous_stock,
		"days_since_previous": cint(doc.days_since_previous),
		"offtake": doc.offtake(),
	}
