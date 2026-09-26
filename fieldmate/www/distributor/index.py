"""/distributor lands on the order queue.

That is what a depot opens the portal for; claims are a monthly errand and orders are a morning
one. A bare index page listing two links would be a page nobody wanted to be on.
"""

import frappe


def get_context(context):
	frappe.local.flags.redirect_location = "/distributor/orders"
	raise frappe.Redirect
