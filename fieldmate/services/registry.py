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
# Phase 4 adds: FieldMate Order (push), FieldMate Distributor Profile (pull) and the
#               compiled scheme specs (pull) - not the scheme masters, see ADR-021.
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

# ---------------------------------------------------------------------------- the day
#
# A day captured with no signal has to land like anything else. Without these two entries a
# rep who started their day in a village kept nothing: the API call failed, nothing was
# queued, and every visit afterwards was refused because the server had no open day. The
# visit's `day_start` link resolves through `depends_on`, so a queued day and the visits
# that hang off it can travel in the same batch.
register(
	Syncable(
		doctype="FieldMate Day Start",
		uuid_field="client_uuid",
		push=True,
		pull=False,
		submit_on_push=True,
		server_owned=("employee_checkin", "synced_at", "journey_plan", "planned_beat"),
	)
)

register(
	Syncable(
		doctype="FieldMate Day End",
		uuid_field="client_uuid",
		push=True,
		pull=False,
		submit_on_push=True,
		depends_on=("day_start",),
		# Everything the day produced is counted from the records on the server. A phone
		# that has been offline all day cannot know what finally synced.
		server_owned=(
			"employee_checkin", "synced_at", "duration_hours", "distance_km", "coverage_pct",
			"planned_visits", "actual_visits", "productive_visits", "new_outlets",
			"orders_count", "order_value", "collection_amount",
		),
	)
)


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

# ---------------------------------------------------------------------------- Phase 4
# An order is pushed and never pulled, for the same reason a visit is: the phone that took it
# already holds it, and one rep has no business downloading another rep's order book.
#
# Submitted on push, because a draft order is an order the distributor never sees. Submitting is
# the whole event here - it routes the order to that distributor's queue and does nothing else.
# No Sales Order, no invoice, no stock movement, no GL Entry (ADR-023): a shop order is a
# secondary sale and is terminal in our books, so there is nothing a bad push could post.
register(
	Syncable(
		doctype="FieldMate Order",
		uuid_field="client_uuid",
		push=True,
		# Phase 9 turned this on. The distributor now works the order at his end - accepts it,
		# bills it, delivers it - and the rep is the person the shopkeeper asks about it the next
		# morning. Without a pull the phone would still be showing "Sent To Distributor" on an
		# order that was delivered on Tuesday, and the rep would be the last person in the chain
		# to know. Narrow by design: every field below is server-owned anyway, so the phone is
		# reading back the office's answer and never proposing one.
		pull=True,
		pull_fields=("name", "client_uuid", "order_date", "outlet", "field_user", "visit",
		             "order_status", "credit_status", "approval_status", "net_total",
		             "total_qty", "total_lines", "expected_delivery_date",
		             "sent_to_distributor_on", "distributor_reference", "docstatus", "modified"),
		submit_on_push=True,
		# An order taken at a shop created the same morning has to travel in the same batch as
		# that shop, and an order taken during a call has to land after the call it came out of.
		depends_on=("outlet", "visit"),
		# Every figure the business acts on, and every state only the office can move the order
		# into. The totals are recomputed from the engine on save, so a value sent for one of
		# them would be overwritten anyway - discarding it here means the phone never even gets
		# to propose the number a manager will read. order_status and the two hand-off fields are
		# listed for a different reason: a device that could mark its own order Accepted, or stamp
		# a distributor reference it invented, would make the distributor's queue decorative.
		#
		# `proposed_net_total` is deliberately absent. It is not the server's figure and is not
		# meant to be - it is the device's own statement of the number the rep said out loud
		# across a counter, and it has to survive exactly as sent or there is nothing left to
		# compare the server against when the two engines drift.
		server_owned=(
			"gross_total", "discount_total", "net_total", "tax_total", "grand_total",
			"incentive_amount", "total_qty", "total_lines",
			"credit_status", "credit_limit_at_order", "outstanding_at_order",
			"approval_required", "approval_rule", "approval_status", "approved_by", "approved_on",
			"totals_match", "sales_order", "order_status",
			"sent_to_distributor_on", "distributor_reference",
			"sync_status", "synced_at",
		),
	)
)

# The rep picks nothing here - the outlet already names its distributor - but the phone still has
# to show who the order is going to and what it can promise about delivery, and it has to do that
# with no signal. Delivery days and the minimum order value are read out to the shopkeeper at the
# counter, so they cannot wait for a round trip.
register(Syncable(doctype="FieldMate Distributor Profile", push=False, pull=True,
                  pull_fields=("name", "customer", "distributor_code", "status", "territory",
                               "price_list", "min_order_value", "credit_days", "delivery_days",
                               "mobile_no", "modified")))

# TODO (Phase 4, blocked): the compiled scheme specs the cart re-prices against offline.
# ADR-021 is explicit that the phone caches *compiled specs* and never the scheme masters, so
# there is nothing here to register yet - `services/scheme_compile.py` and whatever it writes the
# compiled JSON to do not exist at the time of writing. Registering `FieldMate Scheme` in the
# meantime would be worse than leaving the gap: the device would cache unresolved masters, the
# two engines would be fed different input, and Gate 4 parity would be measuring the wrong thing.

# ---------------------------------------------------------------------------- Phase 5
# A stock count is captured in the field like everything else, and just as often
# with no signal - a godown at 6am and a kirana shelf at noon are both places the network is not.
register(
	Syncable(
		doctype="FieldMate Retailer Stock",
		uuid_field="client_uuid",
		push=True,
		pull=False,
		submit_on_push=True,
		depends_on=("outlet", "visit"),
		# Counted against listed, and whether the count was finished, are read from the rows.
		# A phone that proposed its own coverage figure could flatter it.
		server_owned=("counted_lines", "total_lines", "coverage_pct", "is_partial",
		              "previous_stock", "days_since_previous", "sync_status", "synced_at"),
	)
)

# ---------------------------------------------------------------------------- Phase 6
# Money taken at a counter has to reach us whatever the signal was like when it was taken. The
# receipt number is issued server-side, so a phone that queued three collections in a village
# gets three real numbers when they land rather than three guesses.
register(
	Syncable(
		doctype="FieldMate Collection",
		uuid_field="client_uuid",
		push=True,
		pull=False,
		submit_on_push=True,
		depends_on=("outlet", "visit"),
		server_owned=("receipt_no", "party", "posts_to_ledger", "status", "deposit",
		              "payment_entry", "allocated_amount", "unallocated_amount",
		              "sync_status", "synced_at"),
	)
)

register(
	Syncable(
		doctype="FieldMate Collection Deposit",
		uuid_field="client_uuid",
		push=True,
		pull=False,
		submit_on_push=True,
		# Everything about what the deposit is worth is read from the collections inside it.
		# A phone that could state its own totals could declare more than it is carrying.
		server_owned=("cash_amount", "cheque_amount", "cheque_count", "total_amount",
		              "ours_amount", "status", "confirmed_by", "confirmed_on",
		              "sync_status", "synced_at"),
	)
)

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
