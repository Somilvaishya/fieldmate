"""Server context for the depot's own sales file.

The reader behind this page has existed since Phase 5 and was reachable only from Desk, so the
file travelled by email and somebody at this end imported it - a step that gets skipped in a busy
week, and the secondary sales that depend on it simply stop arriving.
"""

import frappe

from fieldmate.services import portal as portal_service
from fieldmate.services import secondary_sales as secondary_sales_service

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/distributor/sales"
		raise frappe.Redirect

	row = portal_service.me()
	portal_service.touch(row)

	context.no_cache = 1
	context.page = "sales"
	context.distributor = row.distributor
	context.depot_name = frappe.db.get_value("Customer", row.distributor, "customer_name") \
		or row.distributor
	context.full_name = frappe.db.get_value("User", row.user, "full_name") or row.user
	context.designation = row.designation
	context.can_upload = bool(row.can_upload_sales)

	# The headers this reader already understands, shown on the page rather than hidden behind a
	# download. A depot looking at its own export wants to know whether it is already accepted;
	# handing them a format to convert to is how a file stops being sent.
	#
	# NOT `context.template`. That key belongs to Frappe: `template_page.get_raw_template` reads
	# it as the path of the Jinja file to render, so setting it to a dict made every load of this
	# page a 500 before a line of it was drawn - `AttributeError: 'dict' object has no attribute
	# 'split'`, thrown inside Jinja's loader, nowhere near here. The page had never once
	# rendered.
	context.file_format = secondary_sales_service.template()

	context.recent = frappe.get_all(
		"FieldMate Secondary Sales",
		filters={"distributor": row.distributor, "docstatus": 1},
		fields=["name", "from_date", "to_date", "file_name", "total_lines", "total_qty",
		        "total_amount", "rows_rejected", "matched_outlets", "creation"],
		order_by="creation desc",
		limit=10,
	)
	return context
