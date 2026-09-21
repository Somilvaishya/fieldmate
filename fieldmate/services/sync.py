"""Sync logic: idempotent push, delta pull, conflict capture.

The one rule everything here serves: **the client assigns identity, the server honours it.**
Every field-created record carries a device-generated uuid with a unique index. Push upserts on
it and returns whatever already exists, so a retry after a dropped connection is free.

Plain functions, no `frappe.request` — callable from a controller, a test or a job alike.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import cint, now_datetime

from fieldmate.services import registry

# A batch larger than this is refused rather than allowed to time out mid-way.
MAX_BATCH_SIZE = 500


# --------------------------------------------------------------------------------------
# pull
# --------------------------------------------------------------------------------------


def pull(user: str, since: str | None = None, doctypes: list[str] | None = None) -> dict:
	"""Everything that changed since the watermark, scoped to what this user may read.

	The watermark is taken *before* reading, never after. Taking it after would silently drop
	anything written during the read.
	"""
	watermark = now_datetime()
	wanted = set(doctypes or [])
	changes: dict[str, list] = {}

	for entry in registry.pullable():
		if wanted and entry.doctype not in wanted:
			continue
		if not frappe.has_permission(entry.doctype, "read", user=user):
			continue

		filters = {}
		if since:
			filters["modified"] = [">", since]

		changes[entry.doctype] = frappe.get_all(
			entry.doctype,
			filters=filters,
			fields=list(entry.pull_fields) or ["*"],
			limit_page_length=0,
			ignore_permissions=False,
		)

	return {
		"watermark": str(watermark),
		"since": since,
		"changes": changes,
		"counts": {dt: len(rows) for dt, rows in changes.items()},
	}


# --------------------------------------------------------------------------------------
# push
# --------------------------------------------------------------------------------------


def push(user: str, device, batch_uuid: str, records: list[dict], app_version: str | None = None) -> dict:
	"""Apply a batch of device-created records. Safe to call repeatedly with the same batch."""
	if not batch_uuid:
		raise ValueError("batch_uuid is required")
	if len(records) > MAX_BATCH_SIZE:
		raise ValueError(f"Batch of {len(records)} exceeds the limit of {MAX_BATCH_SIZE}")

	batch = _open_batch(batch_uuid, device, user, records, app_version)

	# A batch already completed is replayed from its stored results rather than re-applied.
	if batch.status in ("Completed", "Partial", "Failed") and batch.get("__already_done"):
		return _batch_summary(batch, replayed=True)

	results = []
	resolved: dict[str, str] = {}  # client_uuid -> server name, within this batch

	for record in records:
		results.append(_apply(record, user, device, batch, resolved))

	batch.accepted_count = sum(1 for r in results if r["status"] in ("created", "duplicate"))
	batch.rejected_count = sum(1 for r in results if r["status"] in ("rejected", "held"))
	batch.conflict_count = sum(1 for r in results if r["status"] == "conflict")
	batch.complete()

	device.touch(synced=True)

	summary = _batch_summary(batch)
	summary["results"] = results
	return summary


def _apply(record: dict, user: str, device, batch, resolved: dict) -> dict:
	doctype = record.get("doctype")
	client_uuid = record.get("client_uuid")

	base = {"client_uuid": client_uuid, "doctype": doctype}

	if not doctype or not client_uuid:
		return {**base, "status": "rejected", "code": "BAD_RECORD",
		        "message": "Record is missing doctype or client_uuid."}

	entry = registry.get(doctype)
	if not entry or not entry.push:
		return {**base, "status": "rejected", "code": "NOT_SYNCABLE",
		        "message": f"{doctype} cannot be created from the field app."}

	# Idempotency: already here means already done.
	existing = frappe.db.get_value(doctype, {entry.uuid_field: client_uuid}, "name")
	if existing:
		return {**base, "status": "duplicate", "name": existing}

	data = dict(record.get("data") or {})

	# Dependencies must already exist, either from an earlier batch or earlier in this one.
	for link_field in entry.depends_on:
		ref = data.get(link_field)
		if not ref:
			continue
		if ref in resolved:
			data[link_field] = resolved[ref]
		elif not frappe.db.exists(doctype_of(entry, link_field), ref):
			# Held, not failed. The client retries once the parent lands.
			return {**base, "status": "held", "code": "MISSING_PARENT",
			        "message": f"Waiting for {link_field} to sync first."}

	# The device never sets evidence. Whatever it sent for these is discarded.
	for owned in entry.server_owned:
		data.pop(owned, None)

	data.update({"doctype": doctype, entry.uuid_field: client_uuid})

	# One record per savepoint. A bad record must undo only itself — a bare rollback would
	# discard the batch, the device touch, and every record already accepted in this push,
	# which is the opposite of what a partial batch is for.
	save_point = "fm_" + frappe.generate_hash(length=8)
	frappe.db.savepoint(save_point)

	try:
		doc = frappe.get_doc(data)
		doc.insert()
		resolved[client_uuid] = doc.name
		return {**base, "status": "created", "name": doc.name}

	except frappe.DuplicateEntryError:
		# Lost a race with a concurrent replay of the same record. Still idempotent.
		frappe.db.rollback(save_point=save_point)
		name = frappe.db.get_value(doctype, {entry.uuid_field: client_uuid}, "name")
		return {**base, "status": "duplicate", "name": name}

	except frappe.PermissionError as e:
		frappe.db.rollback(save_point=save_point)
		conflict = record_conflict(batch, device, user, doctype, client_uuid,
		                          "Permission Denied", data, str(e))
		return {**base, "status": "conflict", "conflict": conflict, "code": "PERMISSION_DENIED",
		        "message": "You do not have access to create this."}

	except Exception as e:
		frappe.db.rollback(save_point=save_point)
		conflict = record_conflict(batch, device, user, doctype, client_uuid,
		                          "Validation Failed", data, str(e))
		return {**base, "status": "conflict", "conflict": conflict, "code": "VALIDATION_FAILED",
		        "message": str(e)[:200]}


def doctype_of(entry, link_field: str) -> str:
	"""Target DocType of a dependency link field."""
	return frappe.get_meta(entry.doctype).get_field(link_field).options


# --------------------------------------------------------------------------------------
# conflicts
# --------------------------------------------------------------------------------------


def record_conflict(batch, device, user, doctype, client_uuid, conflict_type, payload, error) -> str:
	"""Capture a clash for a human. Never auto-resolved, never silently dropped.

	What the rep captured in the field is kept verbatim in `client_payload` so nothing is lost
	even when we cannot apply it.
	"""
	conflict = frappe.get_doc({
		"doctype": "FieldMate Sync Conflict",
		"batch": batch.name if batch else None,
		"device": device.name if device else None,
		"user": user,
		"reference_doctype": doctype,
		"client_uuid": client_uuid,
		"conflict_type": conflict_type,
		"status": "Open",
		"client_payload": json.dumps(payload, indent=2, default=str),
		"resolution_notes": error[:500] if error else None,
	})
	conflict.insert(ignore_permissions=True)
	return conflict.name


def resolve_conflict(name: str, resolution: str, notes: str | None = None) -> dict:
	conflict = frappe.get_doc("FieldMate Sync Conflict", name)
	conflict.resolution = resolution
	conflict.status = "Discarded" if resolution == "Discarded" else "Resolved"
	if notes:
		conflict.resolution_notes = notes
	conflict.save()
	return {"name": conflict.name, "status": conflict.status, "resolution": conflict.resolution}


# --------------------------------------------------------------------------------------
# batch bookkeeping
# --------------------------------------------------------------------------------------


def _open_batch(batch_uuid: str, device, user: str, records: list, app_version: str | None):
	existing = frappe.db.get_value("FieldMate Sync Batch", {"batch_uuid": batch_uuid}, "name")
	if existing:
		batch = frappe.get_doc("FieldMate Sync Batch", existing)
		batch.set("__already_done", batch.status in ("Completed", "Partial", "Failed"))
		return batch

	batch = frappe.get_doc({
		"doctype": "FieldMate Sync Batch",
		"batch_uuid": batch_uuid,
		"device": device.name if device else None,
		"user": user,
		"direction": "Push",
		"status": "Processing",
		"record_count": len(records),
		"app_version": app_version,
		"payload_bytes": len(json.dumps(records, default=str)),
	})
	batch.insert(ignore_permissions=True)
	batch.set("__already_done", False)
	return batch


def _batch_summary(batch, replayed: bool = False) -> dict:
	return {
		"batch_uuid": batch.batch_uuid,
		"status": batch.status,
		"replayed": replayed,
		"record_count": cint(batch.record_count),
		"accepted": cint(batch.accepted_count),
		"rejected": cint(batch.rejected_count),
		"conflicts": cint(batch.conflict_count),
		"duration_ms": cint(batch.duration_ms),
	}


def batch_status(batch_uuid: str) -> dict:
	name = frappe.db.get_value("FieldMate Sync Batch", {"batch_uuid": batch_uuid}, "name")
	if not name:
		return {"batch_uuid": batch_uuid, "status": "Unknown"}
	return _batch_summary(frappe.get_doc("FieldMate Sync Batch", name))
