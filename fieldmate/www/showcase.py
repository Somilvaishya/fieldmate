"""The one page in this app a stranger can open.

Everything else — the PWA, the distributor portal, Desk — is behind a session. This is a URL in a
WhatsApp message, so whoever holds it is whoever it was forwarded to.

The page is built entirely from the **link**, never from anything the visitor sends. The only
thing taken from them is quantities, and even those are checked against what the link actually
shows before anything is written.
"""

import frappe

from fieldmate.services import showcase as showcase_service

no_cache = 1


def get_context(context):
	# `context.template` is Frappe's own - it reads that key as the path of the Jinja file to
	# render - so nothing here may be called `template`, `doc`, `route` or `path`. A page that
	# writes one of those does not fail where it was written; it fails inside Jinja, in a
	# traceback with nothing of ours in it. `/distributor/sales` answered 500 that way for weeks.
	token = (frappe.form_dict.get("t") or "").strip()
	answer = showcase_service.page(token, ip=frappe.local.request_ip)

	context.no_cache = 1
	context.ok = answer.get("ok")
	context.closed_message = answer.get("message")

	if not answer.get("ok"):
		# Nothing else is set. A page that half-populates a closed link is a page that leaks
		# whatever the half was.
		return context

	for key in ("title", "blurb", "cover_image", "season", "party_name", "shared_by",
	            "valid_to", "currency", "items", "token"):
		context[key] = answer.get(key)

	return context


@frappe.whitelist(allow_guest=True, methods=["POST"])
def ask(token: str | None = None, lines: str | None = None, note: str | None = None):
	"""A party asks for what they have been looking at.

	Guest-accessible by necessity, which is why it takes one thing - a token - and reads nothing
	else about the caller. What comes back is a draft for the rep, never an order.
	"""
	return showcase_service.self_order(
		(token or "").strip(), frappe.parse_json(lines or "[]"), note)
