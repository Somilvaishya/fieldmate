"""The sync contract. Thin controllers over `fieldmate.services.sync`."""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok, parse_json
from fieldmate.services import sync as sync_service


@frappe.whitelist()
@endpoint()
def register_device(device_uuid: str | None = None, **kwargs):
	"""Register or re-activate this device for the signed-in user."""
	if not device_uuid:
		raise FieldMateError(Err.BAD_REQUEST, "Device id missing.")
	device = _register(device_uuid, **kwargs)
	return ok(
		{
			"device_uuid": device.device_uuid,
			"status": device.status,
			"registered_on": str(device.registered_on) if device.registered_on else None,
		}
	)


def _register(device_uuid: str, **kwargs):
	"""Idempotent device upsert. Shared with auth.login."""
	name = frappe.db.get_value("FieldMate Device Registry", {"device_uuid": device_uuid}, "name")

	if name:
		device = frappe.get_doc("FieldMate Device Registry", name)
		if device.user != frappe.session.user:
			# A handset changing hands is a real event; re-point it rather than refuse.
			device.user = frappe.session.user
		if device.status == "Deregistered":
			device.status = "Active"
	else:
		device = frappe.new_doc("FieldMate Device Registry")
		device.device_uuid = device_uuid
		device.user = frappe.session.user

	for key in ("device_name", "platform", "os_version", "app_version", "push_subscription"):
		if kwargs.get(key):
			device.set(key, kwargs[key])

	device.save(ignore_permissions=True)
	return device


@frappe.whitelist()
@endpoint(require_device=True)
def pull(device_uuid: str | None = None, since: str | None = None, doctypes: str | None = None, _device=None, **kwargs):
	"""Delta of everything this user may read, changed since the watermark."""
	_device.touch()
	result = sync_service.pull(
		user=frappe.session.user,
		since=since,
		doctypes=parse_json(doctypes, "doctypes"),
	)
	return ok(result)


@frappe.whitelist(methods=["POST"])
@endpoint(require_device=True)
def push(device_uuid: str | None = None, batch_uuid: str | None = None, records: str | None = None,
         app_version: str | None = None, _device=None, **kwargs):
	"""Apply a batch of device-created records. Idempotent on client_uuid."""
	parsed = parse_json(records, "records") or []
	if not isinstance(parsed, list):
		raise FieldMateError(Err.BAD_REQUEST, "records must be a list.")

	try:
		result = sync_service.push(
			user=frappe.session.user,
			device=_device,
			batch_uuid=batch_uuid,
			records=parsed,
			app_version=app_version,
		)
	except ValueError as e:
		raise FieldMateError(Err.BAD_REQUEST, str(e)) from e

	return ok(result)


@frappe.whitelist()
@endpoint()
def status(batch_uuid: str | None = None, **kwargs):
	"""Server's view of a batch, for a client unsure whether its push landed."""
	if not batch_uuid:
		raise FieldMateError(Err.BAD_REQUEST, "batch_uuid is required.")
	return ok(sync_service.batch_status(batch_uuid))


@frappe.whitelist(methods=["POST"])
@endpoint()
def resolve_conflict(name: str | None = None, resolution: str | None = None, notes: str | None = None, **kwargs):
	"""Apply a human decision to a conflict. Never called automatically."""
	valid = ("Keep Client", "Keep Server", "Merged", "Discarded")
	if not name:
		raise FieldMateError(Err.BAD_REQUEST, "Conflict id is required.")
	if resolution not in valid:
		raise FieldMateError(Err.BAD_REQUEST, f"Resolution must be one of: {', '.join(valid)}")

	if not frappe.has_permission("FieldMate Sync Conflict", "write"):
		raise FieldMateError(Err.PERMISSION_DENIED, "You cannot resolve conflicts.")

	return ok(sync_service.resolve_conflict(name, resolution, notes))
