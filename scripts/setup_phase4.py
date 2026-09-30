"""Seed everything the Phase 4 manual test needs, in one command.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase4.py
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase4.py --undo
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase4.py --show

Without this, the order screens open on nothing. An outlet with no catalogue has no
SKUs, an SKU with no Item Price is refused rather than booked free, and a site with no
scheme cannot demonstrate the one thing this phase exists to prove.

What it builds is deliberately the five SKUs and the four scheme shapes from the
supplied designs, so the numbers on screen can be checked against a calculator:

  SE-1000  Surf Excel Easy Wash 1kg    12/case   Rs 122.00
  LB-100   Lifebuoy Total Soap 100g    48/case   Rs   8.20
  RIN-250  Rin Detergent Bar 250g      36/case   Rs  16.50
  TM-500   Taj Mahal Tea 500g          24/case   Rs 275.00
  WH-500   Wheel 2-in-1 Powder 500g    30/case   Rs  34.00   (deliberately unpriced)

and the schemes:

  1. Buy 10 get 1 free on Surf Excel        qty slab, per Multiple, free goods
  2. 5% off on 2+ cases of Lifebuoy         qty slab typed in CASES, percent
  3. Rs 400 off a bill above Rs 10,000      value slab measured over the whole order
  4. Tea festival: Rs 4,000 of tea          value slab over an item set, free jar

Scope is left blank on every one of them, which means everywhere - so it works whichever
rep signs in. Nothing here is scoped to a territory on purpose: a blank Link filled from
the session default is ADR-020's trap, and scoping this to whoever ran the script is how
the tester ends up seeing an empty catalogue and no explanation.

WH-500 is left unpriced on purpose. It is the one SKU that proves the app names a missing
price instead of quietly booking the stock free.

Safe to run twice: everything is looked up by name first.
"""

import sys

import frappe
from frappe.utils import add_days, today

from _guard import require_test_site

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
	if not arg.startswith("--"):
		SITE = arg

UNDO = "--undo" in sys.argv
SHOW = "--show" in sys.argv

CATALOGUE_NAME = "Phase 4 Manual Test"
CASE_UOM = "FM Case"

SKUS = [
	{"code": "SE-1000", "name": "Surf Excel Easy Wash 1kg", "per_case": 12, "rate": 122.00},
	{"code": "LB-100", "name": "Lifebuoy Total Soap 100g", "per_case": 48, "rate": 8.20},
	{"code": "RIN-250", "name": "Rin Detergent Bar 250g", "per_case": 36, "rate": 16.50},
	{"code": "TM-500", "name": "Taj Mahal Tea 500g", "per_case": 24, "rate": 275.00},
	# No rate. The app must name it, not book it free.
	{"code": "WH-500", "name": "Wheel 2-in-1 Powder 500g", "per_case": 30, "rate": None},
]

SCHEMES = [
	{
		"scheme_name": "Surf Excel - buy 10 get 1 free",
		"scheme_type": "Free Goods",
		"priority": 10,
		"basis": "Qty",
		"basis_uom": "Unit",
		"items": ["SE-1000"],
		"slabs": [{
			"slab_idx": 1, "from_value": 10, "is_open_ended": 1,
			"benefit_kind": "Free Goods", "per": "Multiple",
			"free_item": "SE-1000", "free_qty": 1,
		}],
		"pitch": "Every ten packs, one free. Twenty-five packs is two free.",
	},
	{
		"scheme_name": "Lifebuoy - 5% off on 2 cases",
		"scheme_type": "Volume Slab",
		"priority": 20,
		"basis": "Qty",
		"basis_uom": "Case",
		"items": ["LB-100"],
		"slabs": [{
			"slab_idx": 1, "from_value": 2, "is_open_ended": 1,
			"benefit_kind": "Percent Discount", "per": "Slab", "discount_pct": 5,
		}],
		"pitch": "Two cases or more, five percent off the soap.",
	},
	{
		"scheme_name": "Bill over 10,000 - Rs 400 back",
		"scheme_type": "Value Slab",
		"priority": 30,
		"basis": "Value",
		"basis_uom": "Unit",
		"measured_over": "Order",
		"items": [],
		"slabs": [{
			"slab_idx": 1, "from_value": 10000, "is_open_ended": 1,
			"benefit_kind": "Value Discount", "per": "Slab", "discount_amount": 400,
		}],
		"pitch": "Cross ten thousand on the whole bill and four hundred comes off.",
	},
	{
		"scheme_name": "Tea festival - Rs 4,000 of tea",
		"scheme_type": "Value Slab",
		"priority": 40,
		"basis": "Value",
		"basis_uom": "Unit",
		"items": ["TM-500"],
		"slabs": [{
			"slab_idx": 1, "from_value": 4000, "is_open_ended": 1,
			"benefit_kind": "Free Goods", "per": "Slab",
			"free_item": "TM-500", "free_qty": 1,
		}],
		"pitch": "Four thousand rupees of tea and a free 500g jar goes in the box.",
	},
]


def note(kind, what, detail=""):
	print(f"  {kind:<9} {what:<46} {detail}")


# --------------------------------------------------------------------------------------
# building
# --------------------------------------------------------------------------------------


def ensure_case_uom() -> str:
	if not frappe.db.exists("UOM", CASE_UOM):
		frappe.get_doc({"doctype": "UOM", "uom_name": CASE_UOM, "must_be_whole_number": 1}).insert(
			ignore_permissions=True
		)
		note("created", "UOM " + CASE_UOM)
	return CASE_UOM


def ensure_item(sku: dict) -> str:
	code = sku["code"]
	if frappe.db.exists("Item", code):
		note("exists", "Item " + code, sku["name"])
		return code

	data = {
		"doctype": "Item",
		"item_code": code,
		"item_name": sku["name"],
		"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups",
		"stock_uom": "Nos" if frappe.db.exists("UOM", "Nos") else frappe.db.get_value("UOM", {}, "name"),
		"is_stock_item": 1,
		"uoms": [{"uom": CASE_UOM, "conversion_factor": sku["per_case"]}],
	}
	# india_compliance, where the site has it, refuses an Item with no HSN code. FieldMate has no
	# opinion about GST; the seed only has to produce an item this site will accept.
	if frappe.get_meta("Item").has_field("gst_hsn_code"):
		data["gst_hsn_code"] = frappe.db.get_value("GST HSN Code", {}, "name")
	for field in frappe.get_all("Custom Field", filters={"dt": "Item", "reqd": 1, "fieldtype": "Select"},
	                            fields=["fieldname", "options"]):
		choices = [c for c in (field.options or "").split("\n") if c]
		if choices:
			data.setdefault(field.fieldname, choices[0])

	frappe.get_doc(data).insert(ignore_permissions=True)
	note("created", "Item " + code, f"{sku['name']}, {sku['per_case']}/case")
	return code


def ensure_price(sku: dict, price_list: str) -> None:
	if sku["rate"] is None:
		note("skipped", "Item Price " + sku["code"], "left unpriced ON PURPOSE - see the docstring")
		return
	existing = frappe.db.get_value("Item Price", {"item_code": sku["code"], "price_list": price_list}, "name")
	if existing:
		frappe.db.set_value("Item Price", existing, "price_list_rate", sku["rate"])
		note("updated", "Item Price " + sku["code"], "Rs {:.2f}".format(sku["rate"]))
		return
	frappe.get_doc({
		"doctype": "Item Price",
		"item_code": sku["code"],
		"price_list": price_list,
		"selling": 1,
		"price_list_rate": sku["rate"],
	}).insert(ignore_permissions=True)
	note("created", "Item Price " + sku["code"], "Rs {:.2f}".format(sku["rate"]))


def ensure_catalogue() -> str:
	if frappe.db.exists("FieldMate Product Catalogue", CATALOGUE_NAME):
		note("exists", "Catalogue " + CATALOGUE_NAME)
		return CATALOGUE_NAME

	doc = frappe.get_doc({
		"doctype": "FieldMate Product Catalogue",
		"catalogue_name": CATALOGUE_NAME,
		"is_active": 1,
		# No territory, channel or class. Blank is everywhere, which is what makes this work for
		# whichever rep signs in to test.
		"items": [
			{"item_code": sku["code"], "uom": CASE_UOM, "is_focus": 1 if i < 2 else 0,
			 "sort_order": (i + 1) * 10}
			for i, sku in enumerate(SKUS)
		],
	})
	doc.insert(ignore_permissions=True)
	note("created", "Catalogue " + CATALOGUE_NAME, f"{len(SKUS)} SKUs")
	return doc.name


def ensure_scheme(spec: dict) -> str | None:
	existing = frappe.db.get_value("FieldMate Scheme", {"scheme_name": spec["scheme_name"]}, "name")
	if existing:
		note("exists", "Scheme " + spec["scheme_name"], existing)
		return existing

	# One savepoint per scheme. A bare frappe.db.rollback() would discard everything built so far
	# in this run, which once left a seed reporting six creations against an empty database.
	mark = "fm_seed_" + frappe.generate_hash(length=8)
	frappe.db.savepoint(mark)
	try:
		doc = frappe.get_doc({
			"doctype": "FieldMate Scheme",
			"scheme_name": spec["scheme_name"],
			"scheme_type": spec["scheme_type"],
			"priority": spec["priority"],
			"is_active": 1,
			"basis": spec["basis"],
			"basis_uom": spec["basis_uom"],
			"measured_over": spec.get("measured_over", "Item Set"),
			"stacking": "Stackable",
			"valid_from": add_days(today(), -1),
			"valid_to": add_days(today(), 365),
			"on_exhaust": "Warn",
			"rep_pitch": spec["pitch"],
			"items": [{"item_code": code, "case_uom": CASE_UOM} for code in spec["items"]],
			"slabs": spec["slabs"],
		})
		doc.insert(ignore_permissions=True)
		doc.submit()
		note("created", "Scheme " + spec["scheme_name"], doc.name)
		return doc.name
	except Exception as e:
		frappe.db.rollback(save_point=mark)
		note("REFUSED", "Scheme " + spec["scheme_name"], str(e)[:70])
		return None


def build() -> None:
	price_list = (
		frappe.db.get_single_value("FieldMate Settings", "default_price_list")
		or frappe.db.get_single_value("Selling Settings", "selling_price_list")
		or frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
	)
	print(f"\nPrice list: {price_list}\n")

	ensure_case_uom()
	for sku in SKUS:
		ensure_item(sku)
		ensure_price(sku, price_list)

	print()
	ensure_catalogue()

	print()
	for spec in SCHEMES:
		ensure_scheme(spec)

	frappe.db.commit()


# --------------------------------------------------------------------------------------
# reading back and undoing
# --------------------------------------------------------------------------------------


def show_state() -> None:
	print("\n=== what a rep will see ===")
	print("  Catalogue          :", "yes" if frappe.db.exists("FieldMate Product Catalogue", CATALOGUE_NAME) else "NO")
	print("  SKUs in it         :", frappe.db.count("FieldMate Catalogue Item", {"parent": CATALOGUE_NAME}))
	print("  Priced SKUs        :", frappe.db.count("Item Price", {"item_code": ["in", [s["code"] for s in SKUS]], "selling": 1}))
	print("  Live schemes       :", frappe.db.count("FieldMate Scheme", {"is_active": 1, "docstatus": 1}))
	print("  Approved outlets   :", frappe.db.count("FieldMate Outlet", {"approval_status": "Approved"}))
	print("  Orders booked      :", frappe.db.count("FieldMate Order"))
	print("  Sales Orders       :", frappe.db.count("Sales Order"), "  <- must not move when you book")

	print("\n=== schemes in force ===")
	for row in frappe.get_all("FieldMate Scheme", filters={"is_active": 1, "docstatus": 1},
	                          fields=["name", "scheme_name", "priority", "basis", "basis_uom"],
	                          order_by="priority asc"):
		print(f"  {row.priority:<4} {row.scheme_name:<40} {row.basis} / {row.basis_uom}")


def undo() -> None:
	print()
	for spec in SCHEMES:
		name = frappe.db.get_value("FieldMate Scheme", {"scheme_name": spec["scheme_name"]}, "name")
		if not name:
			continue
		doc = frappe.get_doc("FieldMate Scheme", name)
		if doc.docstatus == 1:
			doc.flags.ignore_permissions = True
			doc.cancel()
		frappe.delete_doc("FieldMate Scheme", name, force=True, ignore_permissions=True)
		note("deleted", "Scheme " + spec["scheme_name"])

	if frappe.db.exists("FieldMate Product Catalogue", CATALOGUE_NAME):
		frappe.delete_doc("FieldMate Product Catalogue", CATALOGUE_NAME, force=True,
		                  ignore_permissions=True)
		note("deleted", "Catalogue " + CATALOGUE_NAME)

	# Items and prices are left alone. They may have been used by an order, and deleting a
	# priced Item out from under a submitted document is how a test site stops being usable.
	note("kept", "Items and Item Prices", "an order may reference them")
	frappe.db.commit()


def main() -> None:
	frappe.init(site=SITE)
	frappe.connect()
	require_test_site(SITE)
	frappe.set_user("Administrator")
	print(f"Site: {SITE}")

	if UNDO:
		undo()
	elif SHOW:
		pass
	else:
		build()

	show_state()
	frappe.destroy()


if __name__ == "__main__":
	main()
