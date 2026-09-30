"""Seed everything the Phase 9 manual test needs, in one command.

    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase9.py
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase9.py --undo
    cd sites && ../env/bin/python ../apps/fieldmate/scripts/setup_phase9.py --show

The portal opens on nothing without this. A depot login needs a `FieldMate Portal User` row
pointing at a distributor profile, and a claim needs somewhere for its credit note to go - which
means the profile needs a Customer and Settings needs a settlement item.

It builds **two** depot logins, at two different distributors. That is not decoration: the one
thing worth testing by hand in this phase is whether one depot can read the other's order book,
and you cannot test that with one login.

Nothing here invents a distributor. It attaches to the profiles already on the site, because a
portal scoped to a fixture nobody sells through proves nothing about the site it runs on. If
there is only one profile, it says so and builds one login.

Safe to run twice: everything is looked up by name first.
"""

import sys

import frappe

from _guard import require_test_site

SITE = "testerp2.web.gargsystems.com"
for arg in sys.argv[1:]:
	if not arg.startswith("--"):
		SITE = arg

UNDO = "--undo" in sys.argv
SHOW = "--show" in sys.argv

# A fixed, obvious password. This is a seed script for a test site and the alternative is a
# password nobody can find again twenty minutes later.
PASSWORD = "FieldMate@9"
EMAILS = ("depot.one@fieldmate.test", "depot.two@fieldmate.test")
SETTLEMENT_ITEM = "FM-SCHEME-CLAIM"


def note(verb: str, what: str, detail: str = "") -> None:
	print(f"  {verb:8} {what}" + (f"   ({detail})" if detail else ""))


# --------------------------------------------------------------------------------------


def settlement_item() -> str:
	"""A non-stock item for the credit note to sit on.

	Non-stock, because a claim settles money and moves no goods (ADR-026). ERPNext wants an
	expense account on a non-stock item on some benches, so the company default is set where the
	field exists rather than left for the first approval to discover.
	"""
	if frappe.db.exists("Item", SETTLEMENT_ITEM):
		note("kept", f"Item {SETTLEMENT_ITEM}")
		return SETTLEMENT_ITEM

	data = {
		"doctype": "Item",
		"item_code": SETTLEMENT_ITEM,
		"item_name": "Scheme Claim Settlement",
		"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
		"stock_uom": "Nos" if frappe.db.exists("UOM", "Nos")
		             else frappe.db.get_value("UOM", {}, "name"),
		"is_stock_item": 0,
		"is_sales_item": 1,
		"is_purchase_item": 0,
		"description": "Settlement line for an approved FieldMate scheme claim. Not a product.",
	}
	if frappe.get_meta("Item").has_field("gst_hsn_code"):
		data["gst_hsn_code"] = frappe.db.get_value("GST HSN Code", {}, "name")
	frappe.get_doc(data).insert(ignore_permissions=True)
	note("created", f"Item {SETTLEMENT_ITEM}", "non-stock, one line per claim")
	return SETTLEMENT_ITEM


def configure_settings(item: str) -> None:
	settings = frappe.get_single("FieldMate Settings")
	company = settings.default_company or frappe.db.get_value("Company", {}, "name")

	settings.claim_settlement_item = item
	if not settings.claim_expense_account:
		# Any real income account, so the gate and the manual test have something to assert
		# against. A site that budgets trade spend separately should point this at that account
		# instead - which is the whole reason the field exists.
		settings.claim_expense_account = frappe.db.get_value(
			"Account", {"company": company, "root_type": "Income", "is_group": 0}, "name")
	if not settings.claim_cost_center:
		settings.claim_cost_center = frappe.db.get_value("Company", company, "cost_center")

	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)
	note("set", "FieldMate Settings", f"account {settings.claim_expense_account}, "
	                                  f"cost centre {settings.claim_cost_center}")


def distributors() -> list[str]:
	"""The profiles already on the site, newest first, with a Customer behind them.

	A profile with no Customer cannot be claimed against, so offering one as a depot login would
	hand the tester a screen that fails at the last step for a reason nothing on it explains.
	"""
	rows = frappe.get_all("FieldMate Distributor Profile",
	                      fields=["name", "customer"], order_by="creation desc")
	usable = [r.name for r in rows if r.customer]
	if len(usable) < len(rows):
		note("skipped", f"{len(rows) - len(usable)} distributor profile(s)", "no Customer on them")
	return usable


def portal_login(email: str, distributor: str, designation: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": designation,
			"last_name": "Desk",
			"send_welcome_email": 0,
			"user_type": "Website User",
		})
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)
		note("created", f"User {email}")
	from frappe.utils.password import update_password
	update_password(email, PASSWORD)

	if frappe.db.exists("FieldMate Portal User", email):
		frappe.db.set_value("FieldMate Portal User", email,
		                    {"distributor": distributor, "is_active": 1})
		note("kept", f"Portal user {email}", f"-> {distributor}")
		return

	row = frappe.get_doc({
		"doctype": "FieldMate Portal User",
		"user": email,
		"distributor": distributor,
		"designation": designation,
		"is_active": 1,
	})
	row.flags.ignore_permissions = True
	row.insert(ignore_permissions=True)
	note("created", f"Portal user {email}", f"-> {distributor}")


# --------------------------------------------------------------------------------------


def build() -> None:
	print("\nBuilding Phase 9 fixtures")
	print("-" * 72)

	configure_settings(settlement_item())

	profiles = distributors()
	if not profiles:
		print("\n  !! No distributor profile with a Customer on it. Run setup_phase4.py first,")
		print("     or set a Customer on a FieldMate Distributor Profile, then re-run this.\n")
		return

	portal_login(EMAILS[0], profiles[0], "Storekeeper")
	if len(profiles) > 1:
		portal_login(EMAILS[1], profiles[1], "Accountant")
	else:
		print("\n  !! Only one distributor profile on this site, so only one depot login was")
		print("     made. Gate 9 criterion 1 - one depot cannot read another's orders - cannot")
		print("     be tested by hand until there is a second one.\n")

	frappe.db.commit()


def undo() -> None:
	print("\nRemoving Phase 9 fixtures")
	print("-" * 72)

	for email in EMAILS:
		for doctype in ("FieldMate Portal User", "User"):
			if frappe.db.exists(doctype, email):
				try:
					frappe.delete_doc(doctype, email, force=True, ignore_permissions=True)
					note("removed", f"{doctype} {email}")
				except Exception as e:
					note("kept", f"{doctype} {email}", str(e)[:50])

	# Settings and the settlement item are left alone. A claim already settled references that
	# item on a submitted credit note, and deleting it out from under one is how a test site
	# stops being usable.
	note("kept", "FieldMate Settings and the settlement item",
	     "a settled claim references them")
	frappe.db.commit()


def show_state() -> None:
	print("\nState")
	print("-" * 72)

	settings = frappe.get_single("FieldMate Settings")
	print(f"  settlement item       {settings.claim_settlement_item or '(not set)'}")
	print(f"  expense account       {settings.claim_expense_account or '(company default)'}")
	print(f"  cost centre           {settings.claim_cost_center or '(company default)'}")

	rows = frappe.get_all("FieldMate Portal User",
	                      fields=["name", "distributor", "designation", "is_active"])
	print(f"  portal logins         {len(rows)}")
	for row in rows:
		customer = frappe.db.get_value(
			"FieldMate Distributor Profile", row.distributor, "customer")
		name = frappe.db.get_value("Customer", customer, "customer_name") or row.distributor
		state = "active" if row.is_active else "INACTIVE"
		print(f"      {row.name:32} {name}  ({row.designation}, {state})")

	print(f"  claims on the site    {frappe.db.count('FieldMate Claim')}")
	print(f"  queued orders         "
	      f"{frappe.db.count('FieldMate Order', {'order_status': 'Sent To Distributor'})}")

	if not UNDO and any(frappe.db.exists("User", e) for e in EMAILS):
		print("\n  Sign in at /login with:")
		for email in EMAILS:
			if frappe.db.exists("User", email):
				print(f"      {email}   /   {PASSWORD}")
		print("  Then open /distributor/orders\n")


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
