"""Server context for the depot's order queue.

The guard is here rather than in the template because a template that renders and then hides
things is a template that has already sent them. `portal.me()` throws for anybody who is not an
active portal user, and a PermissionError on a website page is a 403, which is the right answer.
"""

import frappe

from fieldmate.services import portal as portal_service

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/distributor/orders"
		raise frappe.Redirect

	row = portal_service.me()
	portal_service.touch(row)

	context.no_cache = 1
	context.portal_user = row
	context.page = "orders"
	context.distributor = row.distributor
	context.depot_name = _depot_name(row.distributor)
	context.full_name = frappe.db.get_value("User", row.user, "full_name") or row.user
	context.designation = row.designation
	context.can_act = bool(row.can_accept_orders)
	return context


def _depot_name(distributor: str) -> str:
	customer = frappe.db.get_value("FieldMate Distributor Profile", distributor, "customer")
	return frappe.db.get_value("Customer", customer, "customer_name") or distributor
