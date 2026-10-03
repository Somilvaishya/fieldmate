"""Server context for the depot's scheme claims."""

import frappe

from fieldmate.services import portal as portal_service

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/distributor/claims"
		raise frappe.Redirect

	row = portal_service.me()
	portal_service.touch(row)

	context.no_cache = 1
	context.page = "claims"
	context.distributor = row.distributor
	context.depot_name = frappe.db.get_value("Customer", row.distributor, "customer_name") \
		or row.distributor
	context.full_name = frappe.db.get_value("User", row.user, "full_name") or row.user
	context.designation = row.designation
	context.can_claim = bool(row.can_raise_claims)
	return context
