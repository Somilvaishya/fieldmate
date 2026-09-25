"""Stock in the field: what a shop holds, and what a van carried.

Three things live here, and none of them post. A retailer count and a van day are measurement —
the goods in a shop were never ours, and the goods in a van are the distributor's (ADR-024).
What this module owes is arithmetic and honesty about what was actually counted.
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


# --------------------------------------------------------------------------------------
# the van
# --------------------------------------------------------------------------------------


def load_sheet_for(field_user: str | None = None, on=None) -> dict:
	"""Today's van load, as the godown prepared it, or an empty sheet to build one on.

	The rep is checking a load somebody else made. Where no sheet exists he loads his own van,
	which is ordinary on a small route, so an empty sheet is a starting point rather than an error.
	"""
	field_user = field_user or field_user_service.for_user()
	on = on or nowdate()

	existing = frappe.db.get_value(
		"FieldMate Van Load",
		{"field_user": field_user, "load_date": on, "docstatus": ["<", 2]},
		"name",
	)
	if existing:
		doc = frappe.get_doc("FieldMate Van Load", existing)
		return summarise_load(doc)

	distributor = distributor_for(field_user)
	return {
		"name": None,
		"load_date": str(on),
		"distributor": distributor,
		"distributor_name": frappe.db.get_value("FieldMate Distributor Profile", distributor,
		                                        "customer") if distributor else None,
		"load_status": "Draft",
		"items": [],
		"total_skus": 0,
		"total_qty": 0,
		"stock_value": 0,
		"has_variance": 0,
	}


def distributor_for(field_user: str) -> str | None:
	"""Whose godown this rep loads from.

	Their own distributor where one is set, otherwise the one behind the shops on their route -
	which is the same answer on every route we have seen, and a better guess than none.
	"""
	customer = frappe.db.get_value("FieldMate Field User", field_user, "distributor")
	if customer:
		return frappe.db.get_value("FieldMate Distributor Profile", {"customer": customer}, "name")

	territory = frappe.db.get_value("FieldMate Field User", field_user, "territory")
	if not territory:
		return None
	return frappe.db.get_value("FieldMate Distributor Profile", {"territory": territory}, "name")


def save_load(payload: dict, field_user: str | None = None) -> dict:
	field_user = field_user or field_user_service.for_user()
	data = dict(payload or {})

	doc = frappe.new_doc("FieldMate Van Load")
	doc.load_date = data.get("load_date") or nowdate()
	doc.field_user = field_user
	doc.distributor = data.get("distributor") or distributor_for(field_user)
	doc.vehicle_no = data.get("vehicle_no")
	doc.day_start = data.get("day_start")
	doc.variance_note = data.get("variance_note")
	doc.remarks = data.get("remarks")
	doc.client_uuid = data.get("client_uuid")
	doc.created_offline = cint(data.get("created_offline"))
	doc.device_id = data.get("device_id")

	rates = price_map([line.get("item_code") for line in data.get("items") or []], field_user)
	for line in data.get("items") or []:
		row = doc.append("items", {})
		row.item_code = line.get("item_code")
		row.godown_qty = flt(line.get("godown_qty"))
		row.counted_qty = flt(line.get("counted_qty"))
		row.display_uom = line.get("display_uom")
		row.conversion_factor = flt(line.get("conversion_factor")) or 1
		row.rate = rates.get(line.get("item_code"), 0)

	doc.insert()
	doc.flags.ignore_permissions = True
	doc.submit()
	return summarise_load(frappe.get_doc("FieldMate Van Load", doc.name))


def price_map(item_codes: list, field_user: str | None = None) -> dict:
	"""Per-base-unit rates, in one call. A load sheet of forty SKUs must not be forty queries."""
	codes = [code for code in item_codes if code]
	if not codes:
		return {}
	price_list = catalogue_service.resolve_price_list(frappe._dict(price_list=None), field_user)
	company = catalogue_service.resolve_company(field_user)
	details = compat.get_item_details(codes, price_list, company)
	return {row["item_code"]: flt(row.get("price_list_rate")) for row in details}


def summarise_load(doc) -> dict:
	return {
		"name": doc.name,
		"load_date": str(doc.load_date),
		"distributor": doc.distributor,
		"vehicle_no": doc.vehicle_no,
		"load_status": doc.load_status,
		"total_skus": cint(doc.total_skus),
		"total_qty": flt(doc.total_qty),
		"stock_value": flt(doc.stock_value),
		"has_variance": cint(doc.has_variance),
		"variance_skus": cint(doc.variance_skus),
		"variance_note": doc.variance_note,
		"items": [
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"godown_qty": flt(row.godown_qty),
				"counted_qty": flt(row.counted_qty),
				"variance": flt(row.variance),
				"is_adjusted": cint(row.is_adjusted),
				"display_uom": row.display_uom,
				"conversion_factor": flt(row.conversion_factor) or 1,
				"amount": flt(row.amount),
			}
			for row in doc.items or []
		],
	}


def settlement_for(field_user: str | None = None, on=None) -> dict:
	"""Tonight's settlement, computed but not saved.

	The rep opens this to see where he stands before entering anything, so everything except the
	returned quantities is worked out and handed to him. The one number he supplies is what came
	back in the van.
	"""
	field_user = field_user or field_user_service.for_user()
	on = on or nowdate()

	load = frappe.db.get_value(
		"FieldMate Van Load",
		{"field_user": field_user, "load_date": on, "docstatus": 1},
		"name",
	)
	if not load:
		return {"van_load": None, "message": "Nothing was loaded on this vehicle today."}

	existing = frappe.db.get_value(
		"FieldMate Van Settlement",
		{"van_load": load, "docstatus": ["<", 2]},
		"name",
	)
	doc = frappe.get_doc("FieldMate Van Settlement", existing) if existing else frappe.new_doc(
		"FieldMate Van Settlement"
	)
	if not existing:
		doc.van_load = load
		doc.field_user = field_user
		doc.settlement_date = on
		doc.run_method("validate")

	return summarise_settlement(doc)


def save_settlement(payload: dict, field_user: str | None = None) -> dict:
	field_user = field_user or field_user_service.for_user()
	data = dict(payload or {})
	if not data.get("van_load"):
		frappe.throw(frappe._("A settlement needs the load it is settling."))

	doc = frappe.new_doc("FieldMate Van Settlement")
	doc.van_load = data["van_load"]
	doc.field_user = field_user
	doc.settlement_date = data.get("settlement_date") or nowdate()
	doc.day_start = data.get("day_start")
	doc.cash_deposited = flt(data.get("cash_deposited"))
	doc.shortfall_note = data.get("shortfall_note")
	doc.remarks = data.get("remarks")
	doc.client_uuid = data.get("client_uuid")
	doc.created_offline = cint(data.get("created_offline"))
	doc.device_id = data.get("device_id")

	returned = {line.get("item_code"): line for line in data.get("items") or []}
	doc.run_method("pull_from_load")
	for row in doc.items or []:
		line = returned.get(row.item_code) or {}
		row.returned_good = flt(line.get("returned_good"))
		row.returned_damaged = flt(line.get("returned_damaged"))
		row.returned_qty = flt(line.get("returned_qty")) or (
			row.returned_good + row.returned_damaged
		)

	doc.insert()
	doc.flags.ignore_permissions = True
	doc.submit()
	return summarise_settlement(frappe.get_doc("FieldMate Van Settlement", doc.name))


def summarise_settlement(doc) -> dict:
	return {
		"name": doc.name if doc.get("name") and not doc.is_new() else None,
		"van_load": doc.van_load,
		"settlement_date": str(doc.settlement_date) if doc.settlement_date else None,
		"distributor": doc.distributor,
		"vehicle_no": doc.vehicle_no,
		"loaded_qty": flt(doc.loaded_qty),
		"sold_qty": flt(doc.sold_qty),
		"returned_qty": flt(doc.returned_qty),
		"short_qty": flt(doc.short_qty),
		"short_value": flt(doc.short_value),
		"cash_collected": flt(doc.cash_collected),
		"cash_deposited": flt(doc.cash_deposited),
		"cash_to_hand_over": flt(doc.cash_to_hand_over),
		"settlement_status": doc.settlement_status,
		"shortfall_note": doc.shortfall_note,
		"items": [
			{
				"item_code": row.item_code,
				"item_name": row.item_name,
				"loaded_qty": flt(row.loaded_qty),
				"sold_qty": flt(row.sold_qty),
				"returned_qty": flt(row.returned_qty),
				"returned_good": flt(row.returned_good),
				"returned_damaged": flt(row.returned_damaged),
				"short_qty": flt(row.short_qty),
				"display_uom": row.display_uom,
				"conversion_factor": flt(row.conversion_factor) or 1,
			}
			for row in doc.items or []
		],
	}
