"""What `bench uninstall-app fieldmate` has to clear that Frappe does not.

Frappe drops every DocType in the FieldMate module, and with them the workspaces, reports, pages,
charts and number cards that name the module. It knows nothing about what FieldMate put on
*other* apps' records, and some of that goes on acting after the app is gone:

- **A Territory User Permission per field user**, applied to every DocType. Left behind, it
  keeps a former rep - or a Sales Head who still uses ERPNext - confined to one territory on
  Customers, invoices and reports, by a rule nobody on the site can trace to anything.
- **Scheduled jobs.** Frappe removes a job whose method left the hooks only on the next migrate.
  Until then the scheduler runs `fieldmate.tasks.*` every day against tables that are gone.
- **Private files attached to FieldMate documents** - visit photos, receipts, start-of-day
  selfies. Evidence about named people (docs/SECURITY.md, PII and retention), and once their
  documents are dropped nothing would ever purge them.
- **Custom Fields** on Sales Order, Payment Entry, Customer, Item and the rest.

Custom Fields are removed the way HRMS removes its own: the field definition goes and the
column stays. A Customer's tier or an Item's MRP is still in the table, so reinstalling brings
it back, and nothing typed into ERPNext's own records is destroyed by an uninstall.

Roles stay, as they do for HRMS. A role with no DocType behind it grants nothing.

Runs before the tables are dropped, which is the only time the field users can still be read.
"""

from __future__ import annotations

import click
import frappe

from fieldmate.setup.install import CUSTOMER_FIELDS, IDEMPOTENCY_FIELDS

MODULE = "FieldMate"


def before_uninstall() -> None:
	try:
		click.secho("Removing what FieldMate added outside its own module...", fg="yellow")
		removed = {
			"territory permissions": remove_territory_permissions(),
			"scheduled jobs": remove_scheduled_jobs(),
			"attached files": remove_attached_files(),
			"custom fields": remove_custom_fields(),
			"insights tables": remove_insights_tables(),
		}
	except Exception:
		click.secho(
			"FieldMate could not remove its customisations; nothing has been uninstalled. "
			"Fix the error below and run the uninstall again.",
			fg="bright_red",
		)
		raise

	for what, count in removed.items():
		click.echo(f"  {count} {what}")
	click.secho("FieldMate customisations removed.", fg="green")


def fieldmate_doctypes() -> list[str]:
	return frappe.get_all("DocType", filters={"module": MODULE}, pluck="name")


def remove_territory_permissions() -> int:
	"""Only the rows FieldMate wrote: this user, this territory, from a Field User record.

	A Territory permission somebody set by hand for a user who was never a field user is not
	ours, and stays. `services.field_user.sync_territory_permission` writes exactly one row per
	active field user, so matching on the pair finds that row and no other.
	"""
	count = 0
	for fu in frappe.get_all("FieldMate Field User", fields=["user", "territory"]):
		if not (fu.user and fu.territory):
			continue
		for name in frappe.get_all(
			"User Permission",
			filters={"user": fu.user, "allow": "Territory", "for_value": fu.territory},
			pluck="name",
		):
			frappe.delete_doc("User Permission", name, force=True, ignore_permissions=True)
			count += 1
	return count


def remove_scheduled_jobs() -> int:
	names = frappe.get_all("Scheduled Job Type", filters={"method": ("like", "fieldmate.%")}, pluck="name")
	for name in names:
		frappe.delete_doc("Scheduled Job Type", name, force=True, ignore_permissions=True)
	return len(names)


def remove_attached_files() -> int:
	"""Delete each File through its controller, which is what removes it from disk.

	A `frappe.db.delete` would leave every photo on the disk with no row pointing at it - the
	worst outcome, because then not even a File list shows that it is there.
	"""
	doctypes = fieldmate_doctypes()
	if not doctypes:
		return 0
	names = frappe.get_all("File", filters={"attached_to_doctype": ("in", doctypes)}, pluck="name")
	for name in names:
		frappe.delete_doc("File", name, force=True, ignore_permissions=True)
	return len(names)


def custom_fields() -> dict[str, list[str]]:
	"""Every Custom Field FieldMate creates, by DocType. Read from install.py, never retyped."""
	fields: dict[str, list[str]] = {doctype: ["fm_source_key"] for doctype, _ in IDEMPOTENCY_FIELDS}
	fields["Customer"] = [spec["fieldname"] for spec in CUSTOMER_FIELDS]
	fields["Item"] = ["fm_mrp"]
	return fields


def remove_custom_fields() -> int:
	count = 0
	for doctype, fieldnames in custom_fields().items():
		filters = {"dt": doctype, "fieldname": ("in", fieldnames)}
		count += frappe.db.count("Custom Field", filters)
		frappe.db.delete("Custom Field", filters)
		frappe.clear_cache(doctype=doctype)
	return count


def remove_insights_tables() -> int:
	"""Insights entries that point at a table about to be dropped. Silent without Insights."""
	count = 0
	for table_doctype in ("Insights Table v3", "Insights Table"):
		if not frappe.db.exists("DocType", table_doctype):
			continue
		# Through the controller: a v2 table carries its columns as child rows.
		for name in frappe.get_all(
			table_doctype, filters={"table": ("like", f"tab{MODULE} %")}, pluck="name"
		):
			frappe.delete_doc(table_doctype, name, force=True, ignore_permissions=True)
			count += 1
	return count
