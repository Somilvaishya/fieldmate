"""Shared plumbing for every `fieldmate.api.*` method.

Three jobs: a stable response envelope, stable error codes, and device resolution.

The envelope matters more than it looks. The PWA is the only consumer, it runs on phones we do
not control, and old builds stay in the field for weeks after a deploy. So the shape here is a
contract: additive changes only.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable

import frappe

# Bumped only for a breaking change to the envelope itself, never for adding a field.
API_VERSION = 1


# --------------------------------------------------------------------------------------
# error codes — stable strings the client branches on
# --------------------------------------------------------------------------------------


class Err:
	AUTH_REQUIRED = "AUTH_REQUIRED"
	LOGIN_FAILED = "LOGIN_FAILED"
	DEVICE_UNKNOWN = "DEVICE_UNKNOWN"
	DEVICE_INACTIVE = "DEVICE_INACTIVE"
	DEVICE_MISMATCH = "DEVICE_MISMATCH"
	VALIDATION_FAILED = "VALIDATION_FAILED"
	PERMISSION_DENIED = "PERMISSION_DENIED"
	NOT_SYNCABLE = "NOT_SYNCABLE"
	MISSING_PARENT = "MISSING_PARENT"
	CONFLICT = "CONFLICT"
	BAD_REQUEST = "BAD_REQUEST"
	INTERNAL = "INTERNAL"


class FieldMateError(Exception):
	"""An error we intend the rep to see. Anything else is a bug and gets a generic message."""

	def __init__(self, code: str, message: str, **extra):
		super().__init__(message)
		self.code = code
		self.message = message
		self.extra = extra


# --------------------------------------------------------------------------------------
# envelope
# --------------------------------------------------------------------------------------


def ok(data=None, **extra) -> dict:
	payload = {"ok": True, "v": API_VERSION, "data": data if data is not None else {}}
	payload.update(extra)
	return payload


def fail(code: str, message: str, **extra) -> dict:
	payload = {"ok": False, "v": API_VERSION, "code": code, "message": message}
	payload.update(extra)
	return payload


# --------------------------------------------------------------------------------------
# decorator
# --------------------------------------------------------------------------------------


def endpoint(require_auth: bool = True, require_device: bool = False) -> Callable:
	"""Wrap a controller: authorise, normalise errors, never leak internals.

	A rep reads these messages on a phone, in a market, with no support line available. So a
	failure says what happened in plain words. Stack traces and SQL errors go to the error log,
	never to the client.
	"""

	def decorator(fn: Callable) -> Callable:
		@functools.wraps(fn)
		def wrapper(*args, **kwargs):
			try:
				if require_auth and frappe.session.user == "Guest":
					raise FieldMateError(Err.AUTH_REQUIRED, "Please sign in again.")

				if require_device:
					device = resolve_device(kwargs.get("device_uuid"))
					device.assert_active()
					kwargs["_device"] = device

				return fn(*args, **kwargs)

			except FieldMateError as e:
				frappe.local.response["http_status_code"] = _status_for(e.code)
				return fail(e.code, e.message, **e.extra)

			except frappe.PermissionError as e:
				frappe.local.response["http_status_code"] = 403
				return fail(Err.PERMISSION_DENIED, str(e) or "You do not have access to this.")

			except frappe.ValidationError as e:
				frappe.local.response["http_status_code"] = 400
				return fail(Err.VALIDATION_FAILED, str(e))

			except Exception:
				frappe.log_error(title=f"fieldmate.api.{fn.__name__}")
				frappe.local.response["http_status_code"] = 500
				return fail(
					Err.INTERNAL,
					"Something went wrong on our side. Your work is saved on this device "
					"and will sync automatically.",
				)

		return wrapper

	return decorator


def _status_for(code: str) -> int:
	return {
		Err.AUTH_REQUIRED: 401,
		Err.LOGIN_FAILED: 401,
		Err.PERMISSION_DENIED: 403,
		Err.DEVICE_UNKNOWN: 404,
		Err.DEVICE_INACTIVE: 403,
		Err.DEVICE_MISMATCH: 403,
		Err.CONFLICT: 409,
		Err.INTERNAL: 500,
	}.get(code, 400)


# --------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------


def resolve_device(device_uuid: str | None):
	"""Load a device and confirm it belongs to the caller."""
	if not device_uuid:
		raise FieldMateError(Err.BAD_REQUEST, "This device is not registered yet.")

	name = frappe.db.get_value("FieldMate Device Registry", {"device_uuid": device_uuid}, "name")
	if not name:
		raise FieldMateError(Err.DEVICE_UNKNOWN, "This device is not registered. Sign in again.")

	device = frappe.get_doc("FieldMate Device Registry", name)
	if device.user != frappe.session.user:
		# Someone else's device id arriving on this session is worth refusing loudly.
		raise FieldMateError(Err.DEVICE_MISMATCH, "This device is registered to another user.")
	return device


def parse_json(value, field: str):
	"""Accept either a JSON string or an already-decoded value.

	Frappe hands us strings for complex args over HTTP but real objects from a direct call, and
	tests take the direct path. Handling both keeps tests honest.
	"""
	if value is None or isinstance(value, (list, dict)):
		return value
	try:
		return json.loads(value)
	except (TypeError, ValueError) as e:
		raise FieldMateError(Err.BAD_REQUEST, f"{field} was not valid JSON.") from e
