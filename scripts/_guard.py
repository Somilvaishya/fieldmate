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
