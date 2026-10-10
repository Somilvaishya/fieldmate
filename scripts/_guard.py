"""One check every script in this folder runs before it touches anything.

Every script here either posts real accounting documents (the gates raise Sales Invoices and
Payment Entries to prove the rules hold) or deletes them (`reset_fieldmate`). All of them take
the site as an argument, and all of them default to a site name written into the file - so
a fat-fingered argument, a copied command line, or a default that outlived the site it was
written for is enough to run any of this against production.

Nothing in Frappe stops that. A site does not know it is a test site, so it has to be told:

    bench --site <site> set-config fieldmate_test_site 1

The flag is deliberately ours and deliberately not `developer_mode`, which is on for perfectly
ordinary reasons on sites nobody would want wiped.
"""

import sys

import frappe

FLAG = "fieldmate_test_site"


def require_test_site(site: str, what: str = "This script") -> None:
	"""Stop unless the site has been marked a test site. Call after `frappe.connect()`."""
	if frappe.conf.get(FLAG):
		return

	print(f"\n  REFUSED: {site} is not marked as a FieldMate test site.\n")
	print(f"  {what} creates, posts or deletes real documents, so it will not run")
	print("  anywhere that has not said out loud that it is safe to do that.\n")
	print("  If this really is a test site:\n")
	print(f"      bench --site {site} set-config {FLAG} 1\n")
	print("  If you meant a different site, pass it as the first argument.\n")
	sys.exit(2)


def selling_price_list() -> str | None:
	"""The list a gate should price into, and the one a cart will resolve to.

	Every one of these scripts used to take "any selling, enabled Price List", which is not a
	rule - it is whatever MariaDB returned first. That held while a site had one. The season
	tests now create a second selling list per run to prove a booking is priced from the
	season's, and the moment a few of those were left behind the gates began pricing into one
	list while the cart read another, and failed with "these have no price yet" - a message that
	names the symptom and hides the cause.

	`pricing.price_list_for` ends its chain at Selling Settings, so that is the answer, and
	naming it means adding a price list cannot move it.
	"""
	named = frappe.db.get_single_value("Selling Settings", "selling_price_list")
	if named and frappe.db.exists("Price List", named):
		return named
	return frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")


def hsn_code() -> str | None:
	"""An HSN code an Item will actually be accepted with, or None where none is needed.

	india_compliance refuses a sales Item with no HSN/SAC **and one of the wrong length**: GST
	Settings accepts six or eight digits by default, so the four-digit chapter headings - which
	are most of the eighteen thousand seeded rows - are not usable. Taking any row therefore
	works on a site without the app and fails on one with it, which is exactly what happened the
	day it was installed.

	340111 is toilet soap, which is what these scripts spend their time pretending to sell, and
	it carries no taxes of its own - an HSN that did would be copied onto every item naming it
	and would quietly override what a tax check is asserting.
	"""
	if not frappe.get_meta("Item").has_field("gst_hsn_code"):
		return None

	for code in ("340111", "340119", "340290"):
		if frappe.db.exists("GST HSN Code", code):
			return code

	row = frappe.db.sql(
		"select name from `tabGST HSN Code` where length(name) in (6, 8) limit 1")
	return row[0][0] if row else None


def pause_open_seasons(company: str | None) -> list[str]:
	"""Close any season of `company` whose book is open, and hand back what was closed.

	**An open season changes what a primary order is.** `channel.resolve` calls a primary order
	dated inside a booking window a *Booking* of that season and prices it from the season's own
	list. That is the design and it is right - but it makes every gate that books a primary order
	depend on whatever seasons happen to be live on the site at the time.

	Both of these failed exactly that way the day `setup_phase2_season.py` first ran. The Phase 1
	gate booked a primary order, got a booking priced from a season list its item was not on, and
	refused with "these have no price yet" - a message naming the symptom and hiding the cause.
	The Phase 2 gate could not create its own season at all, because the master refuses a second
	open book over the same dates.

	Deactivated rather than deleted, which is what a real site would do and what the master's own
	refusal tells a person to do. Every caller puts them back in a `finally`.
	"""
	if not company:
		return []

	names = frappe.get_all("FieldMate Season",
	                       filters={"company": company, "is_active": 1}, pluck="name")
	for name in names:
		frappe.db.set_value("FieldMate Season", name, "is_active", 0, update_modified=False)
		frappe.clear_document_cache("FieldMate Season", name)
	if names:
		frappe.db.commit()
		print(f"  paused {len(names)} open season(s) for the run: {', '.join(names)}")
	return names


def resume_seasons(names: list[str]) -> None:
	"""Put back what `pause_open_seasons` closed. Safe to call with an empty list."""
	for name in names or []:
		if not frappe.db.exists("FieldMate Season", name):
			# Purged by the gate that made it, which is the ordinary case for its own season.
			continue
		frappe.db.set_value("FieldMate Season", name, "is_active", 1, update_modified=False)
		frappe.clear_document_cache("FieldMate Season", name)
	if names:
		frappe.db.commit()
