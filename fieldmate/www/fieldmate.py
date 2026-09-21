import frappe

no_cache = 1


def get_context(context):
	"""Serve the built PWA shell. All routing under /fieldmate is handled client-side."""
	context.csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()
	return context
