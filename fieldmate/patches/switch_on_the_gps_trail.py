"""Write the trail switch's default into the Single, instead of leaving it to be guessed.

`FieldMate Settings.track_gps_trail` is a Check with a default of 1: the trail is recorded unless
somebody turns it off. A **Single** stores one row per field in `tabSingles`, and a field added by
a migration gets no row at all - the DocType default is not written anywhere.

That absence is not read consistently, which is how this was found. On one site
`doc.get("track_gps_trail")` answered `None` and the service's own default of 1 applied; on
another, with the same empty `tabSingles`, it answered `0`. `settings.get()` treats 0 as a value
somebody chose - it has to, or an admin could never switch a Check off - so the second site read
**tracking switched off**, and every rep on it would have quietly stopped recording a trail after
a deploy that was only ever meant to add a switch.

A unit test did not catch it: the test site happened to be the one that answers `None`, so it
passed for a reason that had nothing to do with the code being right.

So the row is written. After this, "off" in `tabSingles` means somebody went to the settings page
and turned it off, which is the only thing it should ever have meant.

Only a missing row is filled. A site where this already ran, or where an admin has since switched
the trail off, is left exactly as it is - so this is safe to re-run.
"""

import frappe

DOCTYPE = "FieldMate Settings"
FIELD = "track_gps_trail"


def _stored_value() -> str | None:
	"""The row's value, or None when there is no row.

	Raw SQL on purpose. `frappe.db.get_value("Singles", ...)` goes through the query builder,
	which appends `order by modified` - a column `tabSingles` does not have - and fails with
	"Unknown column 'modified' in 'ORDER BY'". `get_single_value` would answer `None` for both
	"no row" and "row holding nothing", and telling those apart is the entire point here.
	"""
	rows = frappe.db.sql(
		"select value from tabSingles where doctype = %s and field = %s", (DOCTYPE, FIELD))
	return rows[0][0] if rows else None


def execute():
	meta = frappe.get_meta(DOCTYPE)
	if not meta.get_field(FIELD):
		return

	already = _stored_value()
	if already is not None:
		print(f"  FieldMate: the GPS trail switch is already set to {already!r}; left alone")
		return

	# The DocType's own default, read rather than repeated, so the two cannot drift.
	default = meta.get_field(FIELD).default or "0"
	frappe.db.sql(
		"insert into tabSingles (doctype, field, value) values (%s, %s, %s)",
		(DOCTYPE, FIELD, default))
	frappe.clear_document_cache(DOCTYPE, DOCTYPE)
	frappe.cache().delete_value("fieldmate_settings")
	print(f"  FieldMate: the GPS trail switch had no stored value; written as {default!r} "
	      f"(on, which is what it has always meant)")
