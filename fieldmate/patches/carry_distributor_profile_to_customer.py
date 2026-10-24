"""Move what FieldMate Distributor Profile knew onto the Customer it describes.

The profile existed because FieldMate needed a few things about a distributor that an ERPNext
Customer did not hold. Most of them it held all along - territory, price list, GSTIN, contacts -
and the rest are now `fm_` fields beside them. One party, one record (ADR-013).

This only carries data. Repointing the eleven links, rewriting the reads and dropping the doctype
come after, as their own change: a patch that moved data and rewired the app in one step is one
nobody can run halfway and inspect.

**Nothing is overwritten.** A Customer that already has a value keeps it, because the profile is
the thinner record of the two and on any site where somebody set the Customer up properly it is
the Customer that is right. Territory is the single exception, and only against the root node -
see `_carry_territory`.

**What is not carried is reported, never dropped quietly.** Credit days, a non-Active status and
the contact fields have no `fm_` field waiting for them, each for a stated reason. Every one of
them is printed and logged against the profile it came from, so that a person decides rather than
a patch deciding by omission.
"""

import frappe
from frappe.utils import cint

from fieldmate.services import party as party_service
from fieldmate.setup import install

# profile field -> Customer field, for the values that have a home and need no judgement.
CARRY = {
	# What the shops under this distributor pay. Deliberately NOT `default_price_list`, which is
	# what the distributor pays US and is what ERPNext bills them from - writing an unknown list
	# there would change what a live party is charged.
	"price_list": "fm_ptr_price_list",
	# `distributor_code` is deliberately not carried any more: the Customer field it landed in
	# has been dropped, and the depot's code is its own id. See
	# `patches/drop_the_distributor_code.py`.
	"assigned_to": "fm_assigned_to",
	"warehouse": "fm_warehouse",
	"min_order_value": "fm_min_order_value",
	"gstin": "gstin",
}


def execute():
	if not frappe.db.exists("DocType", "FieldMate Distributor Profile"):
		return
	if not frappe.db.exists("DocType", "Customer"):
		return

	# Build our own landing ground first. A `post_model_sync` patch runs BEFORE the `after_migrate`
	# hooks, so `create_customer_fields` has not run yet and the fm_ columns this patch writes
	# into do not exist - selecting one raises "Unknown column" and aborts the whole migrate. It
	# is idempotent, so calling it here and again from the hook costs nothing.
	install.create_customer_fields()

	rows = frappe.get_all(
		"FieldMate Distributor Profile",
		fields=["name", "customer", "status", "territory", "delivery_days", "credit_days",
		        "onboarding_date", "contact_person", "mobile_no", "email_id", "notes",
		        *CARRY.keys()],
		limit_page_length=0,
	)
	if not rows:
		return

	carried = orphaned = 0
	notes: list[str] = []

	for row in rows:
		customer = row.get("customer") or row["name"]
		if not frappe.db.exists("Customer", customer):
			# Left alone and reported. Deleting it here would destroy the only record that this
			# distributor was ever set up, and the orphan is a sign something else went wrong.
			orphaned += 1
			notes.append(f"{row['name']}: names Customer {customer}, which does not exist. "
			             f"Nothing was carried.")
			continue

		updates = {}
		for source, target in CARRY.items():
			value = row.get(source)
			if value in (None, "", 0):
				continue
			if not frappe.db.has_column("Customer", target):
				# `gstin` only exists where india_compliance is installed.
				notes.append(f"{row['name']}: {source} is {value!r} but Customer has no "
				             f"{target} field on this site.")
				continue
			if frappe.db.get_value("Customer", customer, target):
				continue          # the Customer already knows, and is the better record
			updates[target] = value

		updates.update(_carry_territory(row, customer, notes))
		updates.update(_carry_delivery_days(row, customer, notes))
		updates.update(_tier(customer))
		_report_what_has_no_home(row, customer, notes)

		if updates:
			# `db.set_value` rather than a document save: this runs against live parties, and a
			# full save would fire every ERPNext Customer hook - territory rebuilds, loyalty
			# programme lookups, address syncing - for a patch that is only filling in blanks.
			# The cache clear is the half that goes with it, because set_value writes past the
			# document cache and anything reading the Customer afterwards would see the old row.
			frappe.db.set_value("Customer", customer, updates, update_modified=False)
			frappe.clear_document_cache("Customer", customer)
			carried += 1

	# No commit here. `patch_handler` commits once the patch returns and rolls back if it raises,
	# which is the behaviour this wants: a half-carried set of parties is worse than none. It also
	# keeps the patch callable from a test, where a commit would escape the case rollback.
	print(f"  FieldMate: {len(rows)} distributor profile(s), {carried} carried onto a Customer, "
	      f"{orphaned} with no Customer")
	for note in notes:
		print(f"    - {note}")
	if notes:
		frappe.log_error(
			title="FieldMate: distributor profiles needing a look",
			message="Retiring FieldMate Distributor Profile carried what had somewhere to go. "
			        "These did not, and want a decision:\n\n" + "\n".join(notes),
		)


# --------------------------------------------------------------------------------------
# the ones that need judgement
# --------------------------------------------------------------------------------------


def _carry_territory(row, customer: str, notes: list[str]) -> dict:
	"""The one field allowed to overwrite, and only when what it overwrites says nothing.

	Territory is `reqd` on the profile and nearly always filled in. On the Customer it is a Link
	with a default, so Frappe fills it from the session - which means a Customer created in Desk
	by somebody who never touched the field reads "All Territories", the root of the tree. That
	is not a territory; it is the absence of one wearing a name. So the profile's real territory
	replaces a root node, and never replaces a real one.
	"""
	wanted = row.get("territory")
	if not wanted or not frappe.db.exists("Territory", wanted):
		return {}

	current = frappe.db.get_value("Customer", customer, "territory")
	if not current:
		return {"territory": wanted}
	if current == wanted:
		return {}
	if frappe.db.get_value("Territory", current, "parent_territory"):
		notes.append(f"{row['name']}: profile territory is {wanted!r} but the Customer says "
		             f"{current!r}. The Customer was left alone.")
		return {}
	return {"territory": wanted}        # the root node, which tells nobody anything


def _carry_delivery_days(row, customer: str, notes: list[str]) -> dict:
	"""A lead time in days, out of a field that was typed as free text.

	The profile declared `delivery_days` as Data and described it as "which days this distributor
	delivers, e.g. Mon, Wed, Fri", but the phone has always read it with `Number()` and the live
	data is a bare "2". The data and the reader agree; the description was the odd one out. So it
	becomes an Int lead time, and anything that is not a number is reported rather than coerced
	to zero - a silent zero would read as same-day dispatch.
	"""
	raw = row.get("delivery_days")
	if raw in (None, ""):
		return {}
	if frappe.db.get_value("Customer", customer, "fm_delivery_days"):
		return {}

	text = str(raw).strip()
	if not text.isdigit():
		notes.append(f"{row['name']}: delivery_days reads {raw!r}, which is not a number of "
		             f"days. Set Delivery Lead Days on the Customer by hand.")
		return {}
	return {"fm_delivery_days": cint(text)}


def _tier(customer: str) -> dict:
	"""Every profile was a distributor buying from us, because that is all the app had.

	A site with super stockists sets those afterwards, by hand, because only somebody there knows
	which parties they are.
	"""
	updates = {}
	if not frappe.db.get_value("Customer", customer, "fm_tier"):
		updates["fm_tier"] = "Distributor"
	if not frappe.db.get_value("Customer", customer, "fm_buys_from"):
		updates["fm_buys_from"] = "Company"
	return updates


def _report_what_has_no_home(row, customer: str, notes: list[str]) -> None:
	"""Say out loud what this patch is not carrying, and why."""
	name = row["name"]

	# Credit days are derived from the Payment Terms Template, not stored a second time - see the
	# comment above CUSTOMER_FIELDS in setup/install.py. Where the party has no template, the
	# number on the profile is the only record of its terms, so it is reported.
	if cint(row.get("credit_days")) and party_service.credit_days(customer) is None:
		notes.append(
			f"{name}: profile allowed {cint(row['credit_days'])} credit days, but {customer} has "
			f"no Payment Terms Template. Set one in ERPNext, or the counter will show no terms.")

	# Customer has `disabled`, which is one bit where the profile had three states. Setting it
	# here would block every ERPNext transaction for this party, which is too large a thing for a
	# patch to do on its own.
	status = row.get("status")
	if status and status != "Active":
		notes.append(f"{name}: profile status was {status!r}. Tick Disabled on {customer} if "
		             f"they should not be sold to.")

	# Contacts belong in a Contact and an Address, which is where ERPNext bills and ships from.
	# Creating those from four loose text fields guesses at which is primary and would attach
	# half-built records to a live party.
	contact = {k: row.get(k) for k in ("contact_person", "mobile_no", "email_id")
	           if row.get(k)}
	if contact:
		notes.append(f"{name}: contact details {contact} were not carried. Add them as a Contact "
		             f"against {customer}.")
	if row.get("notes"):
		notes.append(f"{name}: the profile's Notes were not carried: {row['notes']!r}")

	# `onboarding_date` is deliberately not reported. The profile's controller filled it in on
	# every insert, so a note about it would fire for every party on every site - and a note that
	# always fires is one nobody reads. The Customer's own creation date says the same thing.
