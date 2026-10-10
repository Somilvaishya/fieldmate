"""Install-time setup: version guard and roles.

The guard exists so that installing on an unsupported host fails loudly here, at install, rather
than quietly at month end when a report returns the wrong number.
"""

from __future__ import annotations

import frappe

from fieldmate.compat import (
	OPTIONAL_APPS,
	REQUIRED_APPS,
	app_version,
	is_installed,
	version_report,
)

# Role matrix — see .claude/skills/fieldmate/references/data-model.md
# desk_access False means the role lives only in the PWA / portal, never in Frappe Desk.
ROLES = [
	("FieldMate Field Rep", False),
	("FieldMate Area Manager", True),
	("FieldMate Regional Manager", True),
	("FieldMate Sales Head", True),
	("FieldMate Admin", True),
	("FieldMate Distributor", False),
	# Phase 2. Whoever turns a season's allocation into vehicles leaving a gate. Desk only: a
	# dispatch planner works off a screen with a whole season on it, never off a handset.
	("FieldMate Dispatch Planner", True),
]


def before_install() -> None:
	"""Refuse to install on a host we do not support."""
	check_host_versions()


def after_install() -> None:
	create_roles()
	create_idempotency_fields()
	create_customer_fields()
	create_item_mrp_field()
	frappe.db.commit()


def check_host_versions() -> None:
	"""Assert minimum Frappe / ERPNext / HRMS versions, or raise with a readable message."""
	problems: list[str] = []

	# Required: must be present, and new enough.
	for app, minimum in REQUIRED_APPS.items():
		if app != "frappe" and not is_installed(app):
			problems.append(f"{app} is not installed (FieldMate requires >= {_fmt(minimum)})")
			continue

		found = app_version(app)
		if not found:
			problems.append(f"{app} version could not be determined")
		elif found[: len(minimum)] < minimum:
			problems.append(f"{app} {_fmt(found)} is below the required {_fmt(minimum)}")

	# Optional: absence is fine; being present but too old is not, because we would then call
	# into it expecting behaviour it does not have.
	for app, minimum in OPTIONAL_APPS.items():
		if not is_installed(app):
			continue
		found = app_version(app)
		if found and found[: len(minimum)] < minimum:
			problems.append(f"{app} {_fmt(found)} is below the required {_fmt(minimum)}")

	if problems:
		frappe.throw(
			"FieldMate cannot be installed on this bench:\n\n- "
			+ "\n- ".join(problems)
			+ "\n\nDetected: "
			+ ", ".join(f"{k} {v}" for k, v in version_report().items()),
			title="Unsupported host",
		)


def create_roles() -> None:
	"""Create the six FieldMate roles, and keep their desk access right. Safe to re-run.

	Correcting an existing role rather than skipping it is the whole of this function's job on
	any site but a brand new one. Frappe creates a Role by itself the moment a DocType permission
	names one, and it creates it with `desk_access = 1`; our DocTypes are installed before this
	runs, so by the time it is called every role already exists and this used to leave them
	exactly as Frappe had made them. A Field Rep and a Distributor would get the Desk - which is
	the one thing the matrix below exists to prevent - and nothing said so.

	Found by running the suite on a site that had never seen FieldMate before.
	"""
	for role_name, desk_access in ROLES:
		wanted = 1 if desk_access else 0

		if not frappe.db.exists("Role", role_name):
			frappe.get_doc(
				{
					"doctype": "Role",
					"role_name": role_name,
					"desk_access": wanted,
					"is_custom": 1,
				}
			).insert(ignore_permissions=True)
			continue

		if frappe.db.get_value("Role", role_name, "desk_access") != wanted:
			frappe.db.set_value("Role", role_name, "desk_access", wanted)


# Where a caller's idempotency key is kept on the ERPNext documents we post. Custom Fields rather
# than core edits, so `bench update` stays boring (compat rule 3).
IDEMPOTENCY_FIELDS = (
	("Sales Order", "A field order retried after a dropped connection must not become two "
	                "company commitments."),
	("Payment Entry", "A deposit confirmation retried must not pay the same money twice."),
	("Sales Invoice", "A claim approval clicked twice must not credit the distributor twice."),
	("Expense Claim", "A settled travel claim retried must not pay the rep twice."),
	# Phase 2. Dispatching a season is a button somebody will press twice while a long run is
	# still going, and a second Delivery Note would take the same stock out of the warehouse
	# again - a discrepancy found weeks later by somebody counting shelves.
	("Delivery Note", "A dispatch run started twice must not ship the same booking twice."),
	("Delivery Trip", "A route built twice must not send two vehicles for one load."),
)


def create_idempotency_fields() -> None:
	"""Give each document we post somewhere to keep our key. Idempotent.

	Every adapter in `compat` **refuses to post** without this rather than posting blind, because
	the alternative is a duplicate nothing on the site can detect. So this is not decoration:
	without it those adapters simply do not work.
	"""
	for doctype, description in IDEMPOTENCY_FIELDS:
		# Expense Claim belongs to HRMS, which is optional. A field on a DocType that is not
		# installed is not a problem to report - it is a document this bench cannot post, and
		# `compat.make_expense_claim` already answers None for that case.
		if not frappe.db.exists("DocType", doctype):
			continue
		if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "fm_source_key"}):
			continue
		frappe.get_doc({
			"doctype": "Custom Field",
			"dt": doctype,
			"fieldname": "fm_source_key",
			"label": "FieldMate Source",
			"fieldtype": "Data",
			"read_only": 1,
			"no_copy": 1,
			"print_hide": 1,
			"unique": 1,
			"insert_after": "naming_series" if frappe.get_meta(doctype).has_field("naming_series")
			                else "title",
			"description": description,
		}).insert(ignore_permissions=True)


# What FieldMate needs to know about a party we bill, beyond what ERPNext Customer already
# holds. Credit limit, payment terms, default price list, territory, GSTIN and addresses are all
# the Customer's own and are deliberately not repeated here: a second copy of a credit limit is a
# second number to disagree with the first.
#
# These live on Customer rather than on a FieldMate party record because there is only one party.
# A super stockist, a distributor and a wholesaler are all customers we bill; what separates them
# is a tier, not a different document. FieldMate Outlet stays separate for the opposite reason -
# a kirana is never billed by us, and keeping thousands of shops out of the Customer master keeps
# them out of our receivables.
#
# Credit days are deliberately absent, and `test_credit_is_not_duplicated_onto_customer` keeps
# them absent. A party's credit terms are its Payment Terms Template, which has rows - "half in
# fifteen days, half in thirty" is a real arrangement and no single integer states it. What the
# phone needs is one number to read out, so that number is **derived** from the template by
# `services.party.credit_days` and sent in the sync payload. Deriving costs a join; storing a
# second copy costs somebody an afternoon the first time the two disagree.
CUSTOMER_FIELDS = (
	{
		"fieldname": "fm_channel_section",
		"fieldtype": "Section Break",
		"label": "FieldMate Channel",
		"insert_after": "customer_group",
		"collapsible": 1,
	},
	{
		"fieldname": "fm_distributor_code",
		"label": "Distributor Code",
		"fieldtype": "Data",
		"insert_after": "fm_channel_section",
		"description": "What this party calls itself in their own books. Shown in the distributor "
		               "portal header so they can see they are looking at their own account.",
	},
	{
		"fieldname": "fm_tier",
		"label": "Channel Tier",
		"fieldtype": "Select",
		"options": "\nCFA\nSuper Stockist\nDistributor\nSub-stockist\nWholesaler\nModern Trade",
		"insert_after": "fm_distributor_code",
		"description": "What this party is in the chain. Blank means FieldMate does not sell "
		               "through them.",
	},
	{
		"fieldname": "fm_buys_from",
		"label": "Buys From",
		"fieldtype": "Select",
		"options": "Company\nParent",
		"default": "Company",
		"insert_after": "fm_tier",
		"description": "Company means we bill them, so a rep's order on them is a primary sale. "
		               "Parent means they buy from their super stockist and our sale is to that "
		               "super stockist instead.",
	},
	{
		"fieldname": "fm_parent_customer",
		"label": "Buys From Party",
		"fieldtype": "Link",
		"options": "Customer",
		"insert_after": "fm_buys_from",
		"depends_on": "eval:doc.fm_buys_from=='Parent'",
		"description": "The super stockist this party buys from.",
	},
	{
		"fieldname": "fm_assigned_to",
		"label": "Assigned Rep",
		"fieldtype": "Link",
		"options": "FieldMate Field User",
		"insert_after": "fm_parent_customer",
	},
	{
		"fieldname": "fm_channel_column",
		"fieldtype": "Column Break",
		"insert_after": "fm_assigned_to",
	},
	{
		"fieldname": "fm_ptr_price_list",
		"label": "PTR Price List",
		"fieldtype": "Link",
		"options": "Price List",
		"insert_after": "fm_channel_column",
		"description": "What the shops under this party pay. The party's own Default Price List "
		               "is what THEY pay us.",
	},
	{
		"fieldname": "fm_warehouse",
		"label": "Ships From",
		"fieldtype": "Link",
		"options": "Warehouse",
		"insert_after": "fm_ptr_price_list",
	},
	{
		"fieldname": "fm_min_order_value",
		"label": "Minimum Order Value",
		"fieldtype": "Currency",
		"insert_after": "fm_warehouse",
	},
	{
		"fieldname": "fm_max_open_invoices",
		"label": "Max Open Invoices",
		"fieldtype": "Int",
		"insert_after": "fm_min_order_value",
		"description": "A second credit control beside the limit: a party may be within its "
		               "limit and still have too many bills running. Zero means no ceiling.",
	},
	{
		"fieldname": "fm_delivery_days",
		"label": "Delivery Lead Days",
		"fieldtype": "Int",
		"insert_after": "fm_max_open_invoices",
		"description": "How many days after booking this party dispatches. The rep reads the "
		               "dispatch date off this at the counter, so it is mirrored on the phone.",
	},
	{
		"fieldname": "fm_min_cover_days",
		"label": "Min Cover Days",
		"fieldtype": "Int",
		"insert_after": "fm_delivery_days",
		"description": "Stock norms for replenishment. Below the minimum, a top-up is suggested; "
		               "the maximum is what it is topped up to.",
	},
	{
		"fieldname": "fm_max_cover_days",
		"label": "Max Cover Days",
		"fieldtype": "Int",
		"insert_after": "fm_min_cover_days",
	},
)


def create_customer_fields() -> None:
	"""Put the channel fields on ERPNext Customer. Idempotent, and kept current.

	Unlike `create_idempotency_fields`, an existing field is updated rather than skipped. These
	carry descriptions and option lists that will grow - a new tier, a reworded note - and a
	field that was created once and never revisited is how a site ends up with options the code
	no longer understands.
	"""
	if not frappe.db.exists("DocType", "Customer"):
		return

	for spec in CUSTOMER_FIELDS:
		spec = dict(spec)
		fieldname = spec.pop("fieldname")
		existing = frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": fieldname})

		if existing:
			doc = frappe.get_doc("Custom Field", existing)
			changed = False
			for key, value in spec.items():
				if doc.get(key) != value:
					doc.set(key, value)
					changed = True
			if changed:
				doc.flags.ignore_permissions = True
				doc.save(ignore_permissions=True)
			continue

		frappe.get_doc({
			"doctype": "Custom Field", "dt": "Customer", "fieldname": fieldname, **spec
		}).insert(ignore_permissions=True)


def create_item_mrp_field() -> None:
	"""Give Item somewhere to record the price printed on the pack. Idempotent.

	ERPNext has no MRP of its own - it is a legal marking on the consumer pack rather than an
	accounting figure - so every company that tracks one has added a field for it. `compat` has
	always *probed* for that field and answered None where there is none, and it still does: this
	creates the field and never a value. An MRP FieldMate invented would be a number printed on a
	phone that nobody in the company ever agreed to, read out to a shopkeeper who can check the
	pack in his own hand.

	**Refused where the site already has an `mrp` column.** That is the other name in the wild,
	and `compat.MRP_FIELDS` prefers `fm_mrp` - so creating an empty `fm_mrp` beside a populated
	`mrp` would hide every real MRP on the site behind a blank one, and `pricing.is_above_mrp`
	would stop checking anything. Doing nothing is the correct outcome there: the site already
	has what this field is for, and `compat` finds it.
	"""
	if not frappe.db.exists("DocType", "Item"):
		return
	if frappe.db.has_column("Item", "mrp"):
		return
	if frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": "fm_mrp"}):
		return

	meta = frappe.get_meta("Item")
	frappe.get_doc({
		"doctype": "Custom Field",
		"dt": "Item",
		"fieldname": "fm_mrp",
		"label": "MRP",
		"fieldtype": "Currency",
		"insert_after": "standard_rate" if meta.has_field("standard_rate") else "item_name",
		"description": "The price printed on the consumer pack, per stock UOM. FieldMate refuses "
		               "an order line priced above it. Blank means this company does not record "
		               "an MRP for the item, and nothing is checked.",
	}).insert(ignore_permissions=True)


def _fmt(version: tuple[int, ...]) -> str:
	return ".".join(str(p) for p in version)
