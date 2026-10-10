"""Authentication and the boot payload. Thin — logic lives in services and compat."""

from __future__ import annotations

import frappe
from frappe.rate_limiter import rate_limit

from fieldmate import compat
from fieldmate.api._base import API_VERSION, Err, FieldMateError, endpoint, ok
from fieldmate.services import field_user as field_user_service
from fieldmate.services import party as party_service
from fieldmate.services import settings as settings_service

FIELDMATE_ROLES = (
	"FieldMate Field Rep",
	"FieldMate Area Manager",
	"FieldMate Regional Manager",
	"FieldMate Sales Head",
	"FieldMate Admin",
	"FieldMate Distributor",
)


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=20, seconds=60 * 60, methods=["POST"])
@endpoint(require_auth=False)
def login(usr: str | None = None, pwd: str | None = None, device_uuid: str | None = None, **kwargs):
	"""Sign in and bind the session to a device.

	The only guest-accessible method in the app, which is why it is the one that carries a rate
	limit. Twenty attempts an hour from one address: a rep who has forgotten which of two
	passwords it was can try all morning, and somebody working through a list cannot.

	Counted per IP rather than per username, deliberately. Limiting by username lets anybody lock
	a named rep out of their own phone by failing their login twenty times, and a rep standing in
	a market cannot wait an hour for that to expire.
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
			# What the phone sends back on every POST as `X-Frappe-CSRF-Token`.
			#
			# Frappe skips CSRF validation entirely for a session that has no token saved
			# (`auth.validate_csrf_token`, the `not saved_token` arm), and an API login leaves
			# one unset - so until now every write this app accepted was unprotected by it. The
			# session cookie is `SameSite=Lax`, which stops the simplest cross-site POST, but a
			# cookie is not a decision to perform an action and should not be read as one.
			"csrf_token": _csrf_token(),
			"device": device.device_uuid if device else None,
			**_profile(),
		}
	)


def _csrf_token() -> str | None:
	"""This session's CSRF token, generating one if the session has none.

	A session created through the API has no token, and Frappe reads "no token" as "do not
	check" - so asking for one here is what turns the check on for this app at all. Generated
	once and kept on the session, so every later call in the same session agrees about it.
	"""
	session = getattr(frappe.local, "session", None)
	data = getattr(session, "data", None) if session else None
	# `is None`, not falsiness. A fresh session carries an **empty** dict, which is falsy - so
	# the first version of this answered None for exactly the sessions it existed to give a
	# token to, and CSRF stayed switched off while appearing to be on.
	if data is None:
		return None

	token = data.get("csrf_token")
	if not token:
		token = frappe.generate_hash()
		data.csrf_token = token
		# Written through, or the token lives only in this request and the next call rejects
		# what the phone sends back. Absent outside a web request - a patch, a scheduled job, a
		# test - where there is no session row to update and nothing to write through to.
		session_obj = getattr(frappe.local, "session_obj", None)
		if session_obj is not None:
			try:
				session_obj.update(force=True)
			except Exception:
				# A session Frappe will not let us write is still a session this request can
				# use. Refusing here would fail a login over a guard.
				pass

	return token


@frappe.whitelist(methods=["POST"])
@endpoint()
def logout():
	"""End this session on the server, properly.

	Signing out used to be a route change and nothing else: the session cookie stayed valid for
	its full three days, and every byte the phone had pulled - the territory's whole outlet list,
	the catalogue, the day's visits - stayed in IndexedDB for whoever picked the handset up next.
	A rep handing a phone back, or losing one, had not actually signed out of anything.

	The device is deliberately **not** deregistered here. A rep signing out at the end of a day
	and back in tomorrow on the same handset is the ordinary case; deregistering is what somebody
	does to a phone that is gone, and it is theirs to do, not this endpoint's.

	Only **this** session goes. A rep signed in on a second handset, or a manager looking at Desk
	under the same login, is not signed out by somebody tapping this on a phone.
	"""
	from frappe.sessions import delete_session

	user, sid = frappe.session.user, frappe.session.sid

	# `login_manager` only exists inside an HTTP request. It is the better path when it is there,
	# because it clears the cookie as well - but the session row is what actually ends the
	# session, and that has to happen either way.
	manager = getattr(frappe.local, "login_manager", None)
	if manager:
		manager.logout()
	else:
		delete_session(sid, user=user, reason="User Manually Logged Out")

	frappe.db.commit()
	return ok({"signed_out": True})


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
			"settings": settings_service.client_settings(),
			"field_user": field_user_service.profile(),
			# What a rep reads out at a counter about their depots: who the order goes to, when
			# they dispatch, how long the shop has to pay. It rides here rather than in the sync
			# registry because a FieldMate endpoint can choose which Customer fields leave the
			# server, where a sync entry over Customer could not (step 2d-iii). Small - a rep has
			# a handful of depots, and the client stores this payload for offline reads.
			"distributors": party_service.counter_facts(field_user_service.for_user()),
			"sales_mode": settings_service.resolve_sales_mode(
				field_user_service.for_user()
			),
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
