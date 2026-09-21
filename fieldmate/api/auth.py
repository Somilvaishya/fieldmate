"""Authentication and the boot payload. Thin — logic lives in services and compat."""

from __future__ import annotations

import frappe

from fieldmate import compat
from fieldmate.api._base import API_VERSION, Err, FieldMateError, endpoint, ok

FIELDMATE_ROLES = (
	"FieldMate Field Rep",
	"FieldMate Area Manager",
	"FieldMate Regional Manager",
	"FieldMate Sales Head",
	"FieldMate Admin",
	"FieldMate Distributor",
)


@frappe.whitelist(allow_guest=True)
@endpoint(require_auth=False)
def login(usr: str | None = None, pwd: str | None = None, device_uuid: str | None = None, **kwargs):
	"""Sign in and bind the session to a device.

	The only guest-accessible method in the app.
	"""
	if not usr or not pwd:
		raise FieldMateError(Err.BAD_REQUEST, "Enter your username and password.")

	try:
		login_manager = frappe.auth.LoginManager()
		login_manager.authenticate(user=usr, pwd=pwd)
		login_manager.post_login()
	except frappe.AuthenticationError as e:
		raise FieldMateError(Err.LOGIN_FAILED, "Wrong username or password.") from e

	user_roles = set(frappe.get_roles(frappe.session.user))
	if not user_roles.intersection(FIELDMATE_ROLES):
		frappe.local.login_manager.logout()
		raise FieldMateError(
			Err.PERMISSION_DENIED,
			"This account is not set up for the field app. Ask your manager.",
		)

	device = None
	if device_uuid:
		from fieldmate.api.sync import _register  # local import avoids a cycle

		device = _register(device_uuid, **kwargs)

	return ok(
		{
			"user": frappe.session.user,
			"sid": frappe.session.sid,
			"device": device.device_uuid if device else None,
			**_profile(),
		}
	)


@frappe.whitelist()
@endpoint()
def bootstrap(**kwargs):
	"""Everything the app needs on open: who you are, what the host supports, server time.

	Called on every cold start, so it stays small and does no heavy queries.
	"""
	return ok(
		{
			**_profile(),
			"api_version": API_VERSION,
			"server_time": str(frappe.utils.now_datetime()),
			"capabilities": compat.capabilities(),
			"versions": compat.version_report(),
			"syncable": _syncable_manifest(),
		}
	)


def _profile() -> dict:
	user = frappe.get_cached_doc("User", frappe.session.user)
	roles = frappe.get_roles(frappe.session.user)
	return {
		"user": user.name,
		"full_name": user.full_name,
		"email": user.email,
		"language": user.language or "en",
		"time_zone": user.time_zone or frappe.utils.get_system_timezone(),
		"roles": [r for r in roles if r in FIELDMATE_ROLES],
		"is_field_rep": "FieldMate Field Rep" in roles,
	}


def _syncable_manifest() -> list[dict]:
	"""What this build of the server will accept and send.

	The client reads this instead of hard-coding a list, so an old app build never pushes a
	DocType a newer server has stopped accepting.
	"""
	from fieldmate.services import registry

	return [
		{
			"doctype": e.doctype,
			"uuid_field": e.uuid_field,
			"push": e.push,
			"pull": e.pull,
			"depends_on": list(e.depends_on),
		}
		for e in registry.all_entries()
	]
