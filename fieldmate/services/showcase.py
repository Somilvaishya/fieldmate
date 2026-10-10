"""The range, shown to a party at their own prices, behind a link with no login.

**Everything here runs for a stranger.** A share link is a URL in a WhatsApp message, so whoever
holds it is whoever it was forwarded to. That shapes every decision below:

- the page is built from the link, never from anything the visitor sends;
- it answers with the smallest thing that does the job - item, picture, price, and nothing else;
- it never says who else was sent one, what anybody has ordered, or what anybody owes;
- a refusal says "not available" rather than why, because the reason is a fact about somebody
  else's conversation.

A self-order off it is **not an order**. It is a draft FieldMate Order belonging to the rep who
sent the link, for them to look at, price properly and submit - a party typing quantities into a
web page has not been through credit, scheme or MRP checks, and should not be able to commit the
company by filling in a form.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, flt, getdate, nowdate

from fieldmate import compat
from fieldmate.services import catalogue as catalogue_service

# What a visitor is told when a link will not open. One sentence, no detail: who it was for, when
# it expired and how often it has been opened are all facts about a conversation they may not
# have been part of.
CLOSED = "This link is not available."


def make_link(catalogue: str, party: str, field_user: str, party_type: str = "Customer",
              **fields) -> str:
	"""Create a share link for one party. Returns its name; the token is on the document."""
	doc = frappe.get_doc({
		"doctype": "FieldMate Share Link",
		"catalogue": catalogue,
		"party_type": party_type,
		"customer": party if party_type == "Customer" else None,
		"outlet": party if party_type == "Outlet" else None,
		"field_user": field_user,
		**fields,
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def link_for(token: str):
	"""The live link behind a token, or None. Never says which of the two it was.

	One read by token, and the token is indexed and unique. A page that looked a link up by any
	other field would be a page somebody could enumerate.
	"""
	if not token:
		return None

	name = frappe.db.get_value("FieldMate Share Link", {"token": token}, "name")
	if not name:
		return None

	doc = frappe.get_cached_doc("FieldMate Share Link", name)
	live, _ = doc.is_live()
	return doc if live else None


def page(token: str, ip: str | None = None) -> dict:
	"""Everything the public page draws, or a refusal.

	The count is recorded here rather than in the page, so a link opened through any route is
	counted the same - and so a cap on opens cannot be walked round by asking for the data
	another way.
	"""
	link = link_for(token)
	if not link:
		return {"ok": False, "message": frappe._(CLOSED)}

	link.note_an_open(ip)

	party = link.customer if link.party_type == "Customer" else link.outlet
	catalogue = frappe.get_cached_doc("FieldMate Product Catalogue", link.catalogue)

	return {
		"ok": True,
		"title": catalogue.catalogue_name,
		"blurb": catalogue.get("blurb"),
		"cover_image": catalogue.get("cover_image"),
		"season": _season_words(link.season),
		# Named, because a party wants to know whose prices these are and a rep wants them to
		# see that it was personal. Nothing else about them travels.
		"party_name": _party_name(link.party_type, party),
		"shared_by": frappe.db.get_value("FieldMate Field User", link.field_user, "full_name"),
		"valid_to": str(link.valid_to) if link.valid_to else None,
		"currency": frappe.db.get_value("Price List", link.price_list, "currency"),
		"items": _items(catalogue, link),
		"token": token,
	}


def _season_words(season: str | None) -> str | None:
	return frappe.db.get_value("FieldMate Season", season, "season_name") if season else None


def _party_name(party_type: str, party: str | None) -> str | None:
	if not party:
		return None
	if party_type == "Customer":
		return frappe.db.get_value("Customer", party, "customer_name")
	return frappe.db.get_value("FieldMate Outlet", party, "outlet_name")


def _items(catalogue, link) -> list[dict]:
	"""The range at this link's price list, with each item's own picture.

	Priced off the list the link was fixed at, not re-resolved: a party reading a price on
	Tuesday and being quoted another on Wednesday is the argument that field exists to prevent.

	An unpriced item is **left out** rather than shown at nothing. On a rep's screen an unpriced
	line is named so somebody can fix it; on a customer's screen it is either free or broken, and
	neither is a thing to put in front of a buyer.
	"""
	rows = [row for row in (catalogue.items or []) if row.item_code]
	if not rows:
		return []

	codes = [row.item_code for row in rows]
	details = {
		row["item_code"]: row
		for row in compat.get_item_details(codes, price_list=link.price_list,
		                                   company=catalogue_service.resolve_company(
			                                   link.field_user),
		                                   customer=link.customer)
	}

	items = []
	for row in sorted(rows, key=lambda r: (cint(r.sort_order), r.item_code)):
		detail = details.get(row.item_code)
		if not detail or detail.get("disabled"):
			continue
		rate = flt(detail.get("price_list_rate"))
		if rate <= 0:
			continue

		items.append({
			"item_code": row.item_code,
			"item_name": row.item_name or detail.get("item_name") or row.item_code,
			"uom": row.uom or detail.get("stock_uom"),
			"rate": rate,
			"image": frappe.db.get_value("Item", row.item_code, "image"),
			"min_order_qty": flt(row.min_order_qty) or None,
		})
	return items


def self_order(token: str, lines: list[dict], note: str | None = None) -> dict:
	"""A party asks for what they have been looking at. It becomes the rep's draft.

	**Not an order.** It is a draft FieldMate Order owned by the rep who sent the link, for them
	to check and submit. A party typing quantities into a web page has been through no credit
	check, no scheme engine and no MRP check, and must not be able to commit the company by
	filling in a form.

	Quantities are the only thing taken from the visitor, and even those are re-priced by the
	server as every other order is. Nothing else they send is read.
	"""
	link = link_for(token)
	if not link:
		return {"ok": False, "message": frappe._(CLOSED)}

	allowed = {row["item_code"] for row in _items(
		frappe.get_cached_doc("FieldMate Product Catalogue", link.catalogue), link)}

	wanted = []
	for row in lines or []:
		code = (row or {}).get("item")
		qty = flt((row or {}).get("qty"))
		# Only what this link actually shows, and only a positive quantity. An item code the
		# visitor supplied that is not on the page is somebody trying it on.
		if code in allowed and qty > 0:
			wanted.append({"item": code, "qty": qty})

	if not wanted:
		return {"ok": False, "message": frappe._("Choose how much of something you would like.")}

	from fieldmate.services import order as order_service

	party = link.customer if link.party_type == "Customer" else link.outlet
	payload = {
		"party_type": link.party_type,
		"customer": party if link.party_type == "Customer" else None,
		"outlet": party if link.party_type == "Outlet" else None,
		"lines": wanted,
		"client_uuid": f"SHARE-{link.token}-{frappe.generate_hash(length=10)}",
		"remarks": _remarks(link, note),
	}

	# As the server, not as the visitor. There is no session here at all, and the rep who sent
	# the link is the one the draft belongs to.
	was = frappe.session.user
	try:
		frappe.set_user("Administrator")
		created = order_service.create(payload, link.field_user)
	finally:
		frappe.set_user(was)

	return {"ok": True, "order": created["name"],
	        "message": frappe._("Thank you. {0} has it and will be in touch.").format(
		        frappe.db.get_value("FieldMate Field User", link.field_user, "full_name")
		        or frappe._("Your representative"))}


def _remarks(link, note: str | None) -> str:
	"""Say on the order where it came from. A draft nobody can explain is a draft nobody acts on."""
	words = frappe._("Asked for through the shared catalogue on {0}.").format(
		frappe.utils.formatdate(nowdate()))
	return f"{words}\n{note.strip()}" if (note or "").strip() else words


def url_for(token: str) -> str:
	"""The address that goes in the WhatsApp message.

	Built from the site's own URL rather than assembled on the phone: a handset that composed
	this would compose it from whatever host it happened to be served on, and a link pasted into
	a chat has to work for somebody who has never opened our app.
	"""
	return frappe.utils.get_url(f"/showcase?t={token}")


def shareable_for(party: str, party_type: str = "Customer") -> list[dict]:
	"""The catalogues that may be shown to this party, which is not all of them.

	Two filters, and both matter. `matching_masters` is the ordinary scoping - territory,
	channel, class - so a party is never offered a catalogue written for somebody else's region.
	`is_showcase` is the one this module adds: an ordinary catalogue carries focus flags, minimum
	order quantities and notes written for the person selling, and putting one in front of a
	buyer is not a feature, it is a leak.
	"""
	doc = catalogue_service.readable_party(party, party_type)
	matched = catalogue_service.matching_masters(
		"FieldMate Product Catalogue", doc, getdate(nowdate()))

	return [
		{
			"name": c.name,
			"catalogue_name": c.catalogue_name,
			"blurb": c.get("blurb"),
			"line_count": len(c.get("items") or []),
		}
		for c in matched
		if cint(c.get("is_showcase"))
	]


def links_of(field_user: str, limit: int = 50) -> list[dict]:
	"""What this rep has shared, newest first, with how it has been received.

	Enriched here rather than on the screen. A row needs the catalogue's name, the party's name
	and the address itself before it is worth drawing, and none of the three is on the link - so
	a phone assembling them would make three calls a row, or print ids at a rep.

	`live` is the document's own verdict, not a date comparison repeated here. A link can be
	closed four ways - switched off, not open yet, expired, or opened more times than allowed -
	and a list that re-derived any of them would one day disagree with the page itself.
	"""
	rows = frappe.get_all(
		"FieldMate Share Link",
		filters={"field_user": field_user},
		fields=["name", "token", "catalogue", "party_type", "customer", "outlet",
		        "valid_from", "valid_to", "max_views", "is_active", "view_count",
		        "first_opened", "last_opened", "season"],
		order_by="creation desc",
		limit_page_length=cint(limit),
	)

	for row in rows:
		doc = frappe.get_cached_doc("FieldMate Share Link", row["name"])
		live, why = doc.is_live()
		row["live"] = bool(live)
		# The same sentence a visitor would get. The rep needs more than that - which is why
		# `valid_to` and `max_views` are in the row, for the screen to say "expired on the 3rd"
		# out of fields the rep is entitled to and a stranger is not.
		row["closed_because"] = "" if live else why
		row["url"] = url_for(row["token"])
		row["catalogue_name"] = frappe.get_cached_value(
			"FieldMate Product Catalogue", row["catalogue"], "catalogue_name")
		row["party"] = row["customer"] if row["party_type"] == "Customer" else row["outlet"]
		row["party_name"] = _party_name(row["party_type"], row["party"])

	return rows


def owner_of(name: str) -> str | None:
	"""Which rep made a link. Asked before anything is done to one."""
	return frappe.db.get_value("FieldMate Share Link", name, "field_user")


def withdraw(name: str) -> None:
	"""Switch a link off. The only way a URL is ever taken back."""
	frappe.db.set_value("FieldMate Share Link", name, "is_active", 0, update_modified=False)
	frappe.clear_document_cache("FieldMate Share Link", name)


def expired_links(on=None) -> list[str]:
	"""Links whose window has closed, for whoever wants to tidy up."""
	return frappe.get_all(
		"FieldMate Share Link",
		filters={"is_active": 1, "valid_to": ["<", getdate(on or nowdate())]},
		pluck="name",
	)
