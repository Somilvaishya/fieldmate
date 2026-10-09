"""Share links, from the rep's side.

The public page lives in `fieldmate/www/showcase.py` and answers to anybody. This module is the
other half: the rep who makes a link, sees how it has been received, and switches it off.

**Every call here is about the caller's own links.** The rep comes off the session, never off a
parameter, and a link is read or withdrawn only when it is theirs. A phone that could name a
colleague could read who they had quoted and at what price, and withdraw a live quotation out
from under them - and a stolen handset is the ordinary way that happens rather than the exotic
one.
"""

from __future__ import annotations

import frappe

from fieldmate.api._base import Err, FieldMateError, endpoint, ok
from fieldmate.services import field_user as field_user_service
from fieldmate.services import showcase as showcase_service


def _me() -> str:
	me = field_user_service.for_user()
	if not me:
		raise FieldMateError(Err.PERMISSION_DENIED,
		                     "You are not set up as a field user yet. Ask your manager.")
	return me


def _mine(link: str) -> str:
	"""The link, if it is this rep's. Refused the same way a link that does not exist is.

	One sentence for both cases, deliberately. "That is not yours" confirms the name exists, and
	these names are sequential, so a refusal that told the two apart would let a rep count their
	colleagues' links by trying numbers.
	"""
	if not link:
		raise FieldMateError(Err.BAD_REQUEST, "Which link?")
	if showcase_service.owner_of(link) != _me():
		raise FieldMateError(Err.BAD_REQUEST, "That link is not one of yours.")
	return link


@frappe.whitelist()
@endpoint()
def catalogues(party: str | None = None, party_type: str = "Customer"):
	"""What may be shown to this party.

	Asked per party rather than once per rep, because scoping is per party: a catalogue written
	for one region does not reach a party in another, and a rep covering two should not be
	offered the wrong one.
	"""
	if not party:
		raise FieldMateError(Err.BAD_REQUEST, "Which party?")

	try:
		rows = showcase_service.shareable_for(party, party_type)
	except frappe.DoesNotExistError as e:
		raise FieldMateError(Err.BAD_REQUEST, "That party no longer exists.") from e

	return ok({"catalogues": rows})


@frappe.whitelist(methods=["POST"])
@endpoint()
def share(catalogue: str | None = None, party: str | None = None,
          party_type: str = "Customer", valid_to: str | None = None,
          max_views: int | None = None):
	"""Make a link for one party and hand back the address to send them.

	`valid_to` and `max_views` are the rep's, because they are the two things somebody standing
	in front of the buyer knows: how long the quotation should stand and whether this is for one
	person or a market. Everything else - the token, the price list, the season - is the
	server's, and a phone that could choose any of those could choose a cheaper one.
	"""
	if not catalogue:
		raise FieldMateError(Err.BAD_REQUEST, "Which catalogue?")
	if not party:
		raise FieldMateError(Err.BAD_REQUEST, "Which party?")

	extra = {}
	if valid_to:
		extra["valid_to"] = valid_to
	if max_views:
		extra["max_views"] = int(max_views)

	try:
		name = showcase_service.make_link(catalogue, party, _me(), party_type, **extra)
	except frappe.ValidationError as e:
		# The master's own refusals, which are the rep's to read: a catalogue that is not a
		# showcase, a window that closes before it opens.
		raise FieldMateError(Err.BAD_REQUEST, str(e)) from e

	token = frappe.db.get_value("FieldMate Share Link", name, "token")
	return ok({"link": name, "token": token, "url": showcase_service.url_for(token)})


@frappe.whitelist()
@endpoint()
def links(limit: int = 50):
	"""This rep's links, newest first, with how each has been received."""
	return ok({"links": showcase_service.links_of(_me(), int(limit or 50))})


@frappe.whitelist(methods=["POST"])
@endpoint()
def withdraw(link: str | None = None):
	"""Switch one off. The only way a URL is ever taken back."""
	showcase_service.withdraw(_mine(link))
	return ok({"link": link, "live": False})
