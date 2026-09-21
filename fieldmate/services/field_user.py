"""Field users, and the row-level access that follows from them.

Territory scoping is the security boundary of the whole app: it is what stops a rep in one
district reading another district's outlets, prices and customers. It is enforced with Frappe's
own `User Permission` rather than custom permission code, so it applies uniformly to the API,
the Desk, reports and exports — anywhere a query runs — instead of only where we remembered to
add a filter.
"""

from __future__ import annotations

import frappe

MARKER = "FieldMate territory scope"


def for_user(user: str | None = None) -> str | None:
	"""The FieldMate Field User record for a login, if there is one."""
	user = user or frappe.session.user
	return frappe.db.get_value("FieldMate Field User", {"user": user}, "name")


def get(user: str | None = None):
	name = for_user(user)
	return frappe.get_doc("FieldMate Field User", name) if name else None


def territory_of(user: str | None = None) -> str | None:
	name = for_user(user)
	return frappe.db.get_value("FieldMate Field User", name, "territory") if name else None


def sync_territory_permission(doc) -> None:
	"""Make the User Permission match the record, whatever state it was in before.

	Rewritten rather than patched: a stale permission is a rep quietly reading a territory they
	were moved out of months ago.
	"""
	clear_territory_permission(doc.user)

	# Inactive staff keep their history but lose their access.
	if doc.status != "Active":
		return

	frappe.get_doc({
		"doctype": "User Permission",
		"user": doc.user,
		"allow": "Territory",
		"for_value": doc.territory,
		# Territory is a tree. Leaving descendants visible is what lets a manager sit on a parent
		# node and see every area beneath it without a row per area.
		"hide_descendants": 0,
		"apply_to_all_doctypes": 1,
		"is_default": 1,
	}).insert(ignore_permissions=True)


def clear_territory_permission(user: str) -> None:
	for name in frappe.get_all(
		"User Permission", filters={"user": user, "allow": "Territory"}, pluck="name"
	):
		frappe.delete_doc("User Permission", name, force=True, ignore_permissions=True)


def touch(user: str | None = None) -> None:
	"""Record that this rep did something, without a full save."""
	name = for_user(user)
	if name:
		frappe.db.set_value(
			"FieldMate Field User", name, "last_active_on", frappe.utils.now_datetime(),
			update_modified=False,
		)


def profile(user: str | None = None) -> dict:
	"""What the app needs to know about who is signed in. Plain dict, no document leaks."""
	doc = get(user)
	if not doc:
		return {}
	from fieldmate.services import settings as settings_service

	return {
		"field_user": doc.name,
		"designation": doc.designation,
		"status": doc.status,
		"territory": doc.territory,
		"distributor": doc.distributor,
		"company": doc.company,
		"price_list": doc.default_price_list or settings_service.value("default_price_list"),
		"sales_mode": settings_service.resolve_sales_mode(doc.name),
		"vehicle_warehouse": doc.vehicle_warehouse,
		"can_create_outlet": bool(doc.can_create_outlet),
		"can_collect_payment": bool(doc.can_collect_payment),
		"daily_target_calls": doc.daily_target_calls,
	}
