"""Seed everything the Phase 2 manual test needs, in one command.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase2_season.py
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase2_season.py --show
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase2_season.py --undo

**Without this, every Phase 2 screen opens on nothing.** A booking is a primary order dated inside
an open season, so with no season there are no bookings, the season book is empty, the allocation
and cockpit pages have nothing to list, and the showcase cannot be shared because no catalogue is
marked as one. All of that looks exactly like broken software, and it is an empty site.

Four things, and the order matters:

1. a **season** whose booking window is open today and whose delivery window is in the future,
   with an advance percentage and a payment terms template for the balance;
2. a **price list of its own** with every catalogue item priced on it - a booking is priced from
   the season's list, not the party's, and an item missing from it reads as "no price yet" on the
   phone, which is the single likeliest way this seeding goes wrong;
3. the party's **warehouse**, because allocation reserves stock *somewhere* and the somewhere is
   the depot that will ship;
4. **stock in that warehouse, deliberately short** of what two bookings will ask for, so the
   allocation rules have a real decision to make. A run against plentiful stock proves nothing:
   every rule hands everybody everything and the three look identical.

It does **not** create a booking. That is the rep's own job on the phone and it is section 2 of
the sheet - seeding one would skip the half of this phase a person is here to check.

Nothing here invents a distributor or an item. It attaches to what the site already sells, because
a season priced against a fixture nobody sells through proves nothing about the site it runs on.

Safe to run twice: everything is looked up by name first.
"""

import sys

import frappe
from frappe.utils import add_days, flt, today

from _guard import require_test_site, selling_price_list

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
	if not arg.startswith("--"):
		SITE = arg

UNDO = "--undo" in sys.argv
SHOW = "--show" in sys.argv

# Fixed, obvious names. This is a seed script for a test site and the alternative is a season
# nobody can find again twenty minutes later.
SEASON = "Holi 2027 (manual test)"
SEASON_LIST = "Holi 2027 Booking"
TERMS = "Holi 2027 Balance"
SHOWCASE_SUFFIX = " (showcase)"

# What two bookings of 20 and 10 will ask for is 30. Twenty is short on purpose - see the note at
# the top about why a plentiful warehouse proves nothing.
STOCK_QTY = 20

# A season sells below the everyday list, which is the commercial point of booking early.
SEASON_DISCOUNT_PCT = 10


def note(verb: str, what: str, detail: str = "") -> None:
	print(f"  {verb:8} {what}" + (f"   ({detail})" if detail else ""))


def company() -> str:
	from fieldmate.services import settings as settings_service

	return (settings_service.value("default_company")
	        or frappe.db.get_value("Company", {}, "name"))


def the_party() -> str | None:
	"""The distributor this site sells to. Never invented - see the note at the top."""
	rows = frappe.get_all("Customer", filters={"fm_tier": ["is", "set"], "disabled": 0},
	                      fields=["name", "fm_tier"], order_by="creation")
	if not rows:
		print("\n  REFUSED: no Customer on this site has a FieldMate channel tier, so there is")
		print("  nobody to book a season on. Set one up first - docs/USER_MANUAL.md part 2.\n")
		return None
	if len(rows) > 1:
		note("note", f"{len(rows)} parties have a tier", f"using {rows[0].name}")
	return rows[0].name


def catalogue_items() -> list[str]:
	"""Every item on an active catalogue. These are what a rep will see on the phone."""
	live = frappe.get_all("FieldMate Product Catalogue", filters={"is_active": 1}, pluck="name")
	if not live:
		return []
	codes = frappe.get_all("FieldMate Catalogue Item",
	                       filters={"parent": ["in", live]}, pluck="item_code")
	return sorted({code for code in codes if code and frappe.db.exists("Item", code)})


# --------------------------------------------------------------------------------------
# the pieces
# --------------------------------------------------------------------------------------


def balance_terms() -> str:
	"""Half thirty days after the bill, half sixty. ERPNext builds the schedule from this.

	Named on the season rather than copied onto the order: the schedule finance maintains is the
	one on the template, and a second copy of it is a second thing to keep in step.
	"""
	if frappe.db.exists("Payment Terms Template", TERMS):
		note("kept", f"Payment Terms Template {TERMS}")
		return TERMS

	frappe.get_doc({
		"doctype": "Payment Terms Template", "template_name": TERMS,
		"terms": [
			{"payment_term_name": "Holi balance - 30 days",
			 "due_date_based_on": "Day(s) after invoice date",
			 "invoice_portion": 50, "credit_days": 30},
			{"payment_term_name": "Holi balance - 60 days",
			 "due_date_based_on": "Day(s) after invoice date",
			 "invoice_portion": 50, "credit_days": 60},
		],
	}).insert(ignore_permissions=True)
	note("made", f"Payment Terms Template {TERMS}", "50% at 30 days, 50% at 60")
	return TERMS


def season_price_list(items: list[str]) -> str:
	"""The season's own list, priced below the everyday one.

	**Every catalogue item is priced on it.** A booking is priced from the season's list, so an
	item the list has no price for reads as "no price yet" on the phone - and a rep standing in a
	godown cannot tell that from a broken app.
	"""
	currency = frappe.db.get_value("Company", company(), "default_currency") or "INR"
	if not frappe.db.exists("Price List", SEASON_LIST):
		frappe.get_doc({
			"doctype": "Price List", "price_list_name": SEASON_LIST,
			"selling": 1, "enabled": 1, "currency": currency,
		}).insert(ignore_permissions=True)
		note("made", f"Price List {SEASON_LIST}")
	else:
		note("kept", f"Price List {SEASON_LIST}")

	everyday = selling_price_list()
	priced = unpriced = 0
	for code in items:
		if frappe.db.exists("Item Price", {"item_code": code, "price_list": SEASON_LIST}):
			continue
		base = frappe.db.get_value(
			"Item Price", {"item_code": code, "price_list": everyday}, "price_list_rate")
		if not base:
			# Named rather than skipped in silence. An item nobody has priced anywhere is a
			# pricing job somebody has not done, and it will read as a broken screen.
			unpriced += 1
			note("skipped", f"{code}", f"no price on {everyday} to discount from")
			continue
		frappe.get_doc({
			"doctype": "Item Price", "item_code": code, "price_list": SEASON_LIST,
			"selling": 1,
			"price_list_rate": flt(flt(base) * (100 - SEASON_DISCOUNT_PCT) / 100, 2),
		}).insert(ignore_permissions=True)
		priced += 1

	if priced:
		note("priced", f"{priced} item(s) on {SEASON_LIST}",
		     f"{SEASON_DISCOUNT_PCT}% under {everyday}")
	if unpriced:
		note("WARN", f"{unpriced} catalogue item(s) have no price at all",
		     "they will read as 'no price yet' on the phone")
	return SEASON_LIST


def the_season(price_list: str, terms: str) -> str:
	"""A season whose book is open today and whose lorries leave in two months.

	The windows are relative to the day this runs, so the sheet works whenever somebody picks it
	up rather than only in the week it was written.
	"""
	if frappe.db.exists("FieldMate Season", {"season_name": SEASON}):
		name = frappe.db.get_value("FieldMate Season", {"season_name": SEASON}, "name")
		# **Re-opened if it was closed.** A gate run closes every open season for its duration
		# and puts it back at the end - so a gate interrupted halfway leaves this one shut, and a
		# closed season looks exactly like a working site on which nothing will book. Running
		# this script again is what the sheet tells a person to do about that, so it has to work.
		if not frappe.db.get_value("FieldMate Season", name, "is_active"):
			frappe.db.set_value("FieldMate Season", name, "is_active", 1, update_modified=False)
			frappe.clear_document_cache("FieldMate Season", name)
			note("re-opened", f"FieldMate Season {name}", "it had been left closed")
		else:
			note("kept", f"FieldMate Season {name}")
		return name

	# Any other season of this company whose book is open today would clash: `season.open_for`
	# refuses to choose between two, and the master refuses to create the second. So they are
	# closed rather than deleted, which is what a real site would do and what the master's own
	# message tells a person to do.
	for other in frappe.get_all("FieldMate Season",
	                            filters={"company": company(), "is_active": 1}, pluck="name"):
		frappe.db.set_value("FieldMate Season", other, "is_active", 0, update_modified=False)
		note("closed", f"FieldMate Season {other}", "two open books cannot both be the season")

	doc = frappe.get_doc({
		"doctype": "FieldMate Season", "season_name": SEASON, "company": company(),
		"is_active": 1,
		"festival_date": add_days(today(), 120),
		"booking_from": add_days(today(), -7),
		"booking_to": add_days(today(), 45),
		# A gap between the book shutting and changes shutting is the ordinary case, and it is
		# the whole reason `change_cutoff` is its own field.
		"change_cutoff": add_days(today(), 40),
		"delivery_from": add_days(today(), 60),
		"delivery_to": add_days(today(), 110),
		"price_list": price_list,
		"advance_pct": 25,
		"payment_terms_template": terms,
		"notes": "Seeded by scripts/setup_phase2_season.py for the Phase 2 manual test sheet.",
	}).insert(ignore_permissions=True)
	note("made", f"FieldMate Season {doc.name}",
	     f"book open to {doc.booking_to}, 25% advance, delivers {doc.delivery_from}")
	return doc.name


def party_warehouse(party: str) -> str | None:
	"""The depot that serves this party, which is where its bookings reserve from.

	Blank leaves ERPNext to default a warehouse per line off the Item master, which is fine for a
	company running one warehouse and useless for an allocation: stock goes into one warehouse
	and the Sales Order names another, and every rule then allocates nothing.
	"""
	current = frappe.db.get_value("Customer", party, "fm_warehouse")
	if current:
		note("kept", f"{party} ships from {current}")
		return current

	warehouse = (frappe.db.get_value("Warehouse", {"company": company(), "is_group": 0,
	                                               "warehouse_name": "Stores"}, "name")
	             or frappe.db.get_value("Warehouse", {"company": company(), "is_group": 0},
	                                    "name"))
	if not warehouse:
		note("WARN", "this company has no leaf warehouse", "nothing can be allocated")
		return None

	frappe.db.set_value("Customer", party, "fm_warehouse", warehouse, update_modified=False)
	frappe.clear_document_cache("Customer", party)
	note("set", f"{party} ships from {warehouse}")
	return warehouse


def short_stock(items: list[str], warehouse: str) -> None:
	"""Stock to allocate, and not enough of it.

	One Material Receipt for the lot, stamped so `--undo` can find it again. Short on purpose:
	with plenty in the warehouse all three allocation rules hand everybody everything and the
	section of the sheet that compares them has nothing to compare.
	"""
	stockable = [code for code in items
	             if frappe.db.get_value("Item", code, "is_stock_item")]
	if not stockable:
		note("WARN", "no catalogue item is a stock item", "nothing can be reserved")
		return

	existing = frappe.get_all("Stock Entry", filters={"remarks": ["like", f"{SEASON}%"],
	                                                  "docstatus": 1}, pluck="name")
	if existing:
		note("kept", f"Stock Entry {existing[0]}", f"{STOCK_QTY} of each in {warehouse}")
		return

	entry = frappe.get_doc({
		"doctype": "Stock Entry", "stock_entry_type": "Material Receipt",
		"company": company(),
		"remarks": f"{SEASON} - seeded stock",
		"items": [{"item_code": code, "qty": STOCK_QTY, "t_warehouse": warehouse,
		           "basic_rate": 50} for code in stockable],
	})
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	entry.submit()
	note("made", f"Stock Entry {entry.name}",
	     f"{STOCK_QTY} of each of {len(stockable)} item(s) into {warehouse}")


def the_showcase() -> str | None:
	"""A catalogue a party may be shown, which is not the same as one a rep works from.

	A **copy**, not a flag on the working catalogue. An ordinary catalogue carries focus flags,
	minimum order quantities and notes written for the person selling, and the point of the
	showcase rule is that putting one of those in front of a buyer is a leak. Copying it leaves
	the rep's own catalogue exactly as it was.
	"""
	source = frappe.db.get_value("FieldMate Product Catalogue",
	                             {"is_active": 1, "is_showcase": 0}, "name")
	if not source:
		source = frappe.db.get_value("FieldMate Product Catalogue", {"is_active": 1}, "name")
	if not source:
		note("WARN", "no active product catalogue", "nothing can be shared")
		return None

	name = f"{source}{SHOWCASE_SUFFIX}"
	if frappe.db.exists("FieldMate Product Catalogue", {"catalogue_name": name}):
		found = frappe.db.get_value(
			"FieldMate Product Catalogue", {"catalogue_name": name}, "name")
		note("kept", f"FieldMate Product Catalogue {found}")
		return found

	doc = frappe.copy_doc(frappe.get_doc("FieldMate Product Catalogue", source))
	doc.catalogue_name = name
	doc.is_active = 1
	doc.is_showcase = 1
	doc.blurb = "Everything we are taking orders for this Holi."
	if doc.meta.has_field("season"):
		doc.season = frappe.db.get_value("FieldMate Season", {"season_name": SEASON}, "name")
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	note("made", f"FieldMate Product Catalogue {doc.name}", f"copied from {source}")
	return doc.name


# --------------------------------------------------------------------------------------


def show() -> None:
	party = the_party()
	season = frappe.db.get_value("FieldMate Season", {"season_name": SEASON}, "name")
	print(f"\n  company          {company()}")
	print(f"  party            {party}")
	print(f"  warehouse        {frappe.db.get_value('Customer', party, 'fm_warehouse') if party else '-'}")
	print(f"  season           {season or '-'}")
	if season:
		doc = frappe.get_doc("FieldMate Season", season)
		# Printed, because a **closed** season looks identical to an open one in everything
		# below it, and closed is exactly the state a gate run interrupted halfway would leave
		# it in. A season that is not active is not the season, and nothing books into it.
		print(f"    active         {bool(doc.is_active)}"
		      + ("" if doc.is_active else "   <- nothing will book into it"))
		print(f"    book open      {doc.booking_from} to {doc.booking_to}")
		print(f"    changes until  {doc.change_cutoff}")
		print(f"    delivers       {doc.delivery_from} to {doc.delivery_to}")
		print(f"    advance        {doc.advance_pct}%  ·  balance {doc.payment_terms_template}")
		print(f"    priced from    {doc.price_list}")
		print(f"    bookings       {frappe.db.count('FieldMate Order', {'season': season})}")
	showcase = frappe.get_all("FieldMate Product Catalogue", filters={"is_showcase": 1},
	                          fields=["name", "is_active"])
	print(f"  showcase         {showcase or '-'}")
	print(f"  share links      {frappe.db.count('FieldMate Share Link')}")
	print(f"  reservation on   {bool(frappe.db.get_single_value('Stock Settings', 'enable_stock_reservation'))}")
	print()


def undo() -> None:
	"""Take the seeding back out. Bookings are left alone, deliberately.

	A booking that has posted a Sales Order, shipped a Delivery Note and been invoiced is real
	accounting, and a seeding script is not the thing that decides to reverse it. The season is
	closed instead, which is what a real site would do, and the sheet says to clean those up with
	`scripts/reset_fieldmate.py` if that is what is wanted.
	"""
	season = frappe.db.get_value("FieldMate Season", {"season_name": SEASON}, "name")
	if season:
		bookings = frappe.db.count("FieldMate Order", {"season": season})
		if bookings:
			frappe.db.set_value("FieldMate Season", season, "is_active", 0, update_modified=False)
			note("closed", f"FieldMate Season {season}",
			     f"{bookings} booking(s) against it, so it is not deleted")
		else:
			frappe.delete_doc("FieldMate Season", season, force=True, ignore_permissions=True)
			note("removed", f"FieldMate Season {season}")

	for name in frappe.get_all("FieldMate Product Catalogue",
	                           filters={"catalogue_name": ["like", f"%{SHOWCASE_SUFFIX}"]},
	                           pluck="name"):
		links = frappe.db.count("FieldMate Share Link", {"catalogue": name})
		if links:
			frappe.db.set_value("FieldMate Product Catalogue", name, "is_active", 0,
			                    update_modified=False)
			note("closed", f"FieldMate Product Catalogue {name}", f"{links} share link(s) on it")
			continue
		frappe.delete_doc("FieldMate Product Catalogue", name, force=True,
		                  ignore_permissions=True)
		note("removed", f"FieldMate Product Catalogue {name}")

	for name in frappe.get_all("Stock Entry",
	                           filters={"remarks": ["like", f"{SEASON}%"], "docstatus": 1},
	                           pluck="name"):
		try:
			doc = frappe.get_doc("Stock Entry", name)
			doc.flags.ignore_permissions = True
			doc.cancel()
			note("cancelled", f"Stock Entry {name}")
		except Exception as e:
			note("left", f"Stock Entry {name}", str(e)[:60])

	# The price list and the terms template are left: a Sales Order already posted names the
	# template, and removing it under a live document is not tidying up.
	note("left", f"Price List {SEASON_LIST} and Payment Terms Template {TERMS}",
	     "live documents name them")
	frappe.db.commit()


def main() -> None:
	frappe.init(site=SITE)
	frappe.connect()
	require_test_site(SITE, "This script")
	frappe.set_user("Administrator")

	if SHOW:
		show()
		frappe.destroy()
		return

	print(f"\nPhase 2 season seeding on {SITE}\n" + "-" * 72)

	if UNDO:
		undo()
		print("-" * 72 + "\n")
		frappe.destroy()
		return

	party = the_party()
	if not party:
		frappe.destroy()
		sys.exit(2)

	items = catalogue_items()
	if not items:
		print("\n  REFUSED: no active product catalogue has any item on it, so there is nothing")
		print("  to book. Build a FieldMate Product Catalogue first.\n")
		frappe.destroy()
		sys.exit(2)
	note("found", f"{len(items)} item(s) on the active catalogue(s)", ", ".join(items[:6]))

	terms = balance_terms()
	price_list = season_price_list(items)
	the_season(price_list, terms)
	warehouse = party_warehouse(party)
	if warehouse:
		short_stock(items, warehouse)
	the_showcase()

	if not frappe.db.get_single_value("Stock Settings", "enable_stock_reservation"):
		note("WARN", "stock reservation is switched off",
		     "allocation will refuse - Stock Settings > Enable Stock Reservation")

	frappe.db.commit()
	print("-" * 72)
	show()
	print("  Next: take a booking on the phone - see docs/MANUAL_TESTS_PHASE2_SEASON.md\n")
	frappe.destroy()


if __name__ == "__main__":
	main()
