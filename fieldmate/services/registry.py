"""Which DocTypes the field client may sync, and how.

Nothing is syncable unless it is registered here. That is deliberate: `sync.push` accepts a
DocType name from a phone, so an open-ended handler would be a write primitive for anything on
the site. The registry is the allow-list.

Phase 0 ships the machinery with an empty-ish registry. Phase 1 onward registers each field
DocType as it is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Syncable:
	doctype: str
	# Field holding the device-assigned identity. Upserts match on this.
	uuid_field: str = "client_uuid"
	# May the device create these? Masters pull down but are never pushed up.
	push: bool = False
	# Does the device receive these in sync.pull?
	pull: bool = True
	# Fields sent on pull. Empty means all non-system fields.
	pull_fields: tuple[str, ...] = ()
	# Link fields naming a parent that must exist first. The outbox respects this ordering:
	# a visit lands before its order, an order before its collection.
	depends_on: tuple[str, ...] = ()
	# Fields the device may never set, whatever it sends. Evidence is recomputed server-side.
	server_owned: tuple[str, ...] = field(default_factory=tuple)
	# For submittable DocTypes: may a push submit the record outright?
	#
	# Without this an offline day lands as a pile of drafts, and every count that matters -
	# coverage, productivity, the day's own summary - reads submitted rows only. The rep would
	# see a day's work recorded and a day's work uncounted.
	submit_on_push: bool = False


_REGISTRY: dict[str, Syncable] = {}


def register(entry: Syncable) -> None:
	_REGISTRY[entry.doctype] = entry


def get(doctype: str) -> Syncable | None:
	return _REGISTRY.get(doctype)


def is_pushable(doctype: str) -> bool:
	entry = _REGISTRY.get(doctype)
	return bool(entry and entry.push)


def pullable() -> list[Syncable]:
	return [e for e in _REGISTRY.values() if e.pull]


def all_entries() -> list[Syncable]:
	return list(_REGISTRY.values())


def clear() -> None:
	"""Test hook only. Never call from application code."""
	_REGISTRY.clear()


# --------------------------------------------------------------------------------------
# Registrations
# --------------------------------------------------------------------------------------
# Phase 1 adds: FieldMate Outlet (push+pull), FieldMate Beat, FieldMate Field User,
#               FieldMate Outlet Channel / Class, catalogues (pull only).
# Phase 2 adds: FieldMate Journey Plan, Day Start, Day End, Location Trail.
# Phase 3 adds: FieldMate Visit and its children.
# Phase 4 adds: FieldMate Order, FieldMate Scheme (pull only).
# Phase 6 adds: FieldMate Collection.
#
register(
	Syncable(
		doctype="FieldMate Outlet",
		uuid_field="client_uuid",
		push=True,
		pull=True,
		# Without this, pull sends all 46 columns of every outlet: 5,000 shops measured at
		# 6.6 MB on the wire against a 2.5 MB budget. The device needs what a list row, a
		# map pin and a check-in decision require, and nothing else.
		pull_fields=(
			"name", "outlet_name", "outlet_status", "approval_status",
			"channel", "outlet_class", "outlet_type", "territory", "primary_beat",
			"distributor", "city", "mobile_no", "owner_name",
			"latitude", "longitude", "enable_geo_fence", "geo_fence_radius_m",
			"monthly_potential", "modified",
		),
		# Approval and provenance are the server's to set. A device that could send
		# approval_status would make manager approval decorative.
		server_owned=("approval_status", "approved_by", "created_by_rep", "outstanding_amount",
		              "avg_monthly_business", "sync_status", "synced_at"),
	)
)

register(Syncable(doctype="FieldMate Deviation Reason", push=False, pull=True,
                  pull_fields=("name", "reason", "is_active", "applies_to", "requires_note")))

register(Syncable(doctype="FieldMate Journey Plan", push=False, pull=True,
                  pull_fields=("name", "field_user", "from_date", "to_date", "modified")))

register(Syncable(doctype="FieldMate Beat", push=False, pull=True,
                  pull_fields=("name", "beat_name", "territory", "assigned_to",
                               "frequency", "visit_day", "week_pattern", "is_active",
                               "outlet_count", "modified")))

register(Syncable(doctype="FieldMate Outlet Channel", push=False, pull=True,
                  pull_fields=("name", "channel_name", "is_active", "default_visit_frequency")))
register(Syncable(doctype="FieldMate Outlet Class", push=False, pull=True,
                  pull_fields=("name", "class_name", "is_active", "visits_per_month",
                               "min_visit_duration_minutes")))

# ---------------------------------------------------------------------------- Phase 3
# A visit is pushed, never pulled. The phone that recorded it already has it, and a rep has no
# reason to download somebody else's visits - that is a manager's report, not a field master.
register(
	Syncable(
		doctype="FieldMate Visit",
		uuid_field="client_uuid",
		push=True,
		pull=False,
		submit_on_push=True,
		depends_on=("outlet", "day_start"),
		# Everything a device could use to flatter its own coverage numbers. The controller
		# recomputes these on every save; listing them here means a push never even gets to
		# propose a value.
		server_owned=(
			"distance_from_outlet_m", "is_geo_fence_breach", "is_planned", "is_deviation",
			"duration_minutes", "is_short_visit", "order_value", "lines_sold",
			"collection_amount", "merchandising_audit", "geo_fence_exception",
			"visit_sequence",
		),
	)
)

register(
	Syncable(
		doctype="FieldMate Merchandising Audit",
		uuid_field="client_uuid",
		push=True,
		pull=False,
		submit_on_push=True,
		depends_on=("outlet", "visit"),
		# Shelf share and compliance are the whole point of the audit, so they are measured
		# from the rows, never accepted as a figure.
		server_owned=(
			"our_facings", "shelf_share_pct", "line_count", "available_count",
			"must_sell_available", "must_sell_total", "must_sell_compliance_pct",
		),
	)
)

# Masters the visit screens need offline: the no-order sheet and the survey renderer.
register(Syncable(doctype="FieldMate No Order Reason", push=False, pull=True,
                  pull_fields=("name", "reason", "category", "is_active", "requires_note",
                               "counts_as_productive")))

register(Syncable(doctype="FieldMate Checklist Template", push=False, pull=True,
                  pull_fields=("name", "template_name", "version", "is_active", "applies_to",
                               "effective_from", "territory", "channel", "outlet_class",
                               "beat", "question_count", "modified")))

register(Syncable(doctype="FieldMate Must Sell List", push=False, pull=True,
                  pull_fields=("name", "list_name", "is_active", "territory", "channel",
                               "outlet_class", "valid_from", "valid_to", "item_count",
                               "modified")))

# The device's own record is readable by the device, but it is created through
# sync.register_device rather than pushed as part of a batch.
register(
	Syncable(
		doctype="FieldMate Device Registry",
		uuid_field="device_uuid",
		push=False,
		pull=True,
		pull_fields=("device_uuid", "device_name", "platform", "status", "app_version"),
	)
)
