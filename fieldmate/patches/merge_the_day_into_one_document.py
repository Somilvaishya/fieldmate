"""Fold `FieldMate Day Start` and `FieldMate Day End` into the one `FieldMate Day` they describe.

#16. A working day had two documents joined by a unique Link, which bought nothing: a join on
every read, a second naming series, and `field_user`, `day_date`, `client_uuid` and `remarks`
duplicated across both. `FieldMate Visit` had held check-in and check-out in one record from the
start; the day was the odd one out.

The data was declared test and demo and nobody asked for it to be kept. It is carried over
anyway, because deleting is the one thing that cannot be undone if that turns out to be wrong
about a single row, and carrying it costs one INSERT.

Each day **keeps the name its Day Start had**, which is what makes this cheap and safe. Every
record that belonged to a day - a visit, a trail, an expense claim, an attendance row - already
holds that name in `day_start`, so repointing it at the merged document is a column copy and not
a mapping that can lose a row. The names therefore read `FM-DS-00001` for days that existed
before the merge and `FM-DAY-00001` after it, which is accurate: those records were created under
that series.

Safe to re-run. It skips days already carried, and does nothing at all once the old tables are
gone.
"""

import frappe

# The link columns that named a Day Start. `day` was added by the model sync that ran before
# this patch; `day_start` is still there beside it, because Frappe does not drop columns.
LINKS = (
	("FieldMate Visit", "day"),
	("FieldMate Location Trail", "day"),
	("FieldMate Expense Claim", "day"),
	("FieldMate Attendance Summary", "day"),
)


def execute():
	if not frappe.db.table_exists("FieldMate Day Start"):
		print("  FieldMate: no Day Start table - nothing to merge")
		return

	carried = carry_the_days()
	repoint_what_belonged_to_them()
	retire_the_old_doctypes()
	print(f"  FieldMate: {carried} day(s) merged into FieldMate Day")


def carry_the_days() -> int:
	"""One INSERT. The end of the day is a LEFT JOIN, because a day may still be open.

	`nullif(..., '')` on both client ids matters: they are unique columns, and MariaDB allows
	many NULLs but only one empty string - so a handful of desk-created days with no client id
	would collide on the second one.

	Everything else off the join is wrapped in `coalesce`, because Frappe declares Float, Int
	and Currency columns `not null default 0` and Data `not null default ''`. A day still open
	has no Day End row, so the join hands those columns NULL and the insert is refused outright
	- which is how this patch failed the first time it ran.
	"""
	frappe.db.sql("""
		insert into `tabFieldMate Day` (
			name, naming_series, owner, creation, modified, modified_by, docstatus, idx,
			field_user, day_date, status, start_time, journey_plan, planned_beat,
			start_latitude, start_longitude, start_accuracy_m,
			is_mock_location, location_provider, selfie, start_checkin,
			end_time, duration_hours, end_latitude, end_longitude, end_accuracy_m, end_checkin,
			odometer_start, odometer_end, device_id, remarks,
			planned_visits, actual_visits, productive_visits, new_outlets,
			orders_count, order_value, collection_amount, distance_km, coverage_pct,
			client_uuid, end_client_uuid, created_offline, sync_status, synced_at
		)
		select
			ds.name, ds.naming_series, ds.owner, ds.creation, ds.modified, ds.modified_by,
			ds.docstatus, ds.idx,
			ds.field_user, ds.day_date, ds.status, ds.start_time, ds.journey_plan,
			ds.planned_beat,
			ds.latitude, ds.longitude, ds.accuracy_m,
			ds.is_mock_location, ds.location_provider, ds.selfie, ds.employee_checkin,
			de.end_time,
			coalesce(de.duration_hours, 0), coalesce(de.latitude, 0),
			coalesce(de.longitude, 0), coalesce(de.accuracy_m, 0),
			coalesce(de.employee_checkin, ''),
			ds.odometer_start, coalesce(de.odometer_end, 0), ds.device_id,
			-- The closing note is the one worth keeping where there is one: the morning's
			-- remark is rarely about how the day went.
			coalesce(nullif(de.remarks, ''), ds.remarks),
			coalesce(de.planned_visits, 0), coalesce(de.actual_visits, 0),
			coalesce(de.productive_visits, 0), coalesce(de.new_outlets, 0),
			coalesce(de.orders_count, 0), coalesce(de.order_value, 0),
			coalesce(de.collection_amount, 0), coalesce(de.distance_km, 0),
			coalesce(de.coverage_pct, 0),
			nullif(ds.client_uuid, ''), nullif(de.client_uuid, ''),
			ds.created_offline, ds.sync_status, ds.synced_at
		from `tabFieldMate Day Start` ds
		left join `tabFieldMate Day End` de on de.day_start = ds.name and de.docstatus < 2
		where not exists (
			select 1 from `tabFieldMate Day` d where d.name = ds.name
		)
	""")
	return frappe.db.sql("select count(*) from `tabFieldMate Day`")[0][0]


def repoint_what_belonged_to_them() -> None:
	"""Every record that named a Day Start now names the day, which is the same name."""
	for doctype, column in LINKS:
		if not frappe.db.table_exists(doctype):
			continue
		if not (frappe.db.has_column(doctype, column)
		        and frappe.db.has_column(doctype, "day_start")):
			continue
		frappe.db.sql(f"""
			update `tab{doctype}`
			set `{column}` = day_start
			where ifnull(day_start, '') != '' and ifnull(`{column}`, '') = ''
		""")


def retire_the_old_doctypes() -> None:
	"""Drop the pair, and their tables with them.

	`ignore_missing` because a half-finished earlier run may have taken one already, and
	`delete_doc` on a DocType is what drops `tab...` - removing the folder from the app only
	stops it being synced and leaves the table sitting there.
	"""
	for doctype in ("FieldMate Day End", "FieldMate Day Start"):
		if not frappe.db.exists("DocType", doctype):
			continue
		# The rows first: `delete_doc` on the DocType refuses while documents of it survive,
		# and these have been copied into FieldMate Day above.
		frappe.db.sql(f"delete from `tab{doctype}`")
		frappe.delete_doc("DocType", doctype, force=True, ignore_missing=True)
		print(f"  FieldMate: retired {doctype}")
