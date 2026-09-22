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
