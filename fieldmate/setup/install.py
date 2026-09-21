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
	"""Create the six FieldMate roles. Idempotent — safe to re-run on migrate."""
	for role_name, desk_access in ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		frappe.get_doc(
			{
				"doctype": "Role",
				"role_name": role_name,
				"desk_access": 1 if desk_access else 0,
				"is_custom": 1,
			}
		).insert(ignore_permissions=True)


def _fmt(version: tuple[int, ...]) -> str:
	return ".".join(str(p) for p in version)
