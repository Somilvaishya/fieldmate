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
]


def before_install() -> None:
	"""Refuse to install on a host we do not support."""
	check_host_versions()


def after_install() -> None:
	create_roles()
	create_idempotency_fields()
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


# Where a caller's idempotency key is kept on the two ERPNext documents we post. Custom Fields
# rather than core edits, so `bench update` stays boring (compat rule 3).
IDEMPOTENCY_FIELDS = (
	("Sales Order", "A field order retried after a dropped connection must not become two "
	                "company commitments."),
	("Payment Entry", "A deposit confirmation retried must not pay the same money twice."),
	("Sales Invoice", "A claim approval clicked twice must not credit the distributor twice."),
	("Expense Claim", "A settled travel claim retried must not pay the rep twice."),
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


def _fmt(version: tuple[int, ...]) -> str:
	return ".".join(str(p) for p in version)
