"""Point Insights at the KPI snapshot, where Insights is installed.

Guarded the way `compat` guards HRMS: this is an optional app whose data model has changed
between major versions, so nothing here assumes it is present and nothing throws when it is not.
A site without Insights gets a sentence saying so, not an error.

What it registers is the **snapshot table only**. Insights is a place people build their own
charts, and the whole point of Phase 8 is that a chart somebody builds next year still means the
same thing as the one shipped today - which it does if it is reading one materialised table and
does not if it is reading visits (Gate 8 criterion 3).
"""

from __future__ import annotations

import frappe

# The tables analytics may see. Deliberately short, and deliberately not the raw documents.
EXPOSED = (
	"FieldMate KPI Snapshot",
	"FieldMate Achievement",
	"FieldMate Alert Log",
)


def available() -> bool:
	"""Is Insights installed on THIS site, not merely present on the bench?

	The distinction matters: every app in `apps/` is importable from any site's python, and a
	check on the import alone would have this function report success on a site where none of
	the DocTypes exist.
	"""
	return "insights" in frappe.get_installed_apps()


def _table_doctype() -> str | None:
	"""Which generation of Insights this site has, if any.

	v3 renamed the table DocType rather than migrating it, so the name is the version test. A
	site on v2 gets the older one; a site on neither gets None and everything below no-ops.
	"""
	for candidate in ("Insights Table v3", "Insights Table"):
		if frappe.db.exists("DocType", candidate):
			return candidate
	return None


def register_tables() -> dict:
	"""Make the snapshot visible to Insights. Idempotent.

	Returns what it did rather than printing, so `after_migrate` stays quiet on the sites where
	there is nothing to do - which is most of them.
	"""
	if not available():
		return {"insights": False, "reason": "not installed on this site", "registered": []}

	table_doctype = _table_doctype()
	if not table_doctype:
		return {"insights": True, "reason": "no Insights table DocType found", "registered": []}

	source = _site_data_source()
	if not source:
		return {"insights": True, "reason": "no data source for this site's own database",
		        "registered": []}

	registered, skipped = [], []
	for doctype in EXPOSED:
		if not frappe.db.exists("DocType", doctype):
			continue
		table = f"tab{doctype}"
		if frappe.db.exists(table_doctype, {"table": table, "data_source": source}):
			skipped.append(doctype)
			continue
		try:
			doc = frappe.get_doc({
				"doctype": table_doctype,
				"data_source": source,
				"table": table,
				"label": doctype,
				"is_query_based": 0,
			})
			doc.flags.ignore_permissions = True
			doc.insert(ignore_permissions=True)
			registered.append(doctype)
		except Exception:
			# An Insights schema that has moved again is not a reason to fail a migrate. The
			# app works without it; the charts on the Desk workspace do not go through here.
			frappe.log_error(title=f"fieldmate insights register {doctype}")

	return {"insights": True, "source": source, "registered": registered, "already": skipped}


def _site_data_source() -> str | None:
	"""The data source pointing at this site's own database.

	Insights creates one on install and names it differently across versions, so it is found by
	what it points at rather than by what it is called.
	"""
	for doctype in ("Insights Data Source v3", "Insights Data Source"):
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		if meta.has_field("is_site_db"):
			found = frappe.db.get_value(doctype, {"is_site_db": 1}, "name")
			if found:
				return found
		found = frappe.db.get_value(doctype, {"database_name": frappe.conf.db_name}, "name") \
			if meta.has_field("database_name") else None
		if found:
			return found
		found = frappe.db.get_value(doctype, {"name": ["like", "%Site DB%"]}, "name")
		if found:
			return found
	return None


def after_migrate() -> None:
	"""Wired into hooks. Silent on a site without Insights, which is the common case."""
	try:
		result = register_tables()
	except Exception:
		frappe.log_error(title="fieldmate insights after_migrate")
		return
	if result.get("registered"):
		frappe.logger("fieldmate").info(
			f"registered {len(result['registered'])} tables with Insights: "
			+ ", ".join(result["registered"]))


def report() -> dict:
	"""What a person running `bench execute` would want to know. Used by the manual tests."""
	return {
		"installed_on_site": available(),
		"table_doctype": _table_doctype(),
		"data_source": _site_data_source(),
		"exposed": [d for d in EXPOSED if frappe.db.exists("DocType", d)],
	}
