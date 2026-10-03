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
