"""The distributor's end of ADR-023's pipe.

A retailer order is terminal in our books and routes to the distributor's queue. Until now that
queue was a Desk list view, which meant giving a depot a Desk login to work an order - and a Desk
login is scoped by roles, not by whose depot it is. This module is the scoping.

Everything here funnels through `me()`. One function resolves a session to a distributor, every
read narrows to what it returns, and every write asserts against it before touching anything.
That is deliberate: one place that decides whose documents a session may see can be audited, and
six places cannot.

The same posture as the rep's side (ADR-004): a portal user holds `read` and nothing else on any
DocType. Each move below is server-elevated after the scope check, never permitted directly.
"""

from __future__ import annotations

import frappe
from frappe.utils import cint, now_datetime

PORTAL_ROLE = "FieldMate Distributor"

# What the depot may do to an order, and from where. A transition missing from this table is not
# refused by an `if` somewhere downstream - it is simply not reachable, which is the difference
# between a rule and a habit.
TRANSITIONS = {
	"Accepted": {"from": ("Sent To Distributor", "Rejected"), "to": "Accepted"},
	"Rejected": {"from": ("Sent To Distributor", "Accepted"), "to": "Rejected"},
	"Invoiced": {"from": ("Accepted",), "to": "Invoiced"},
	"Delivered": {"from": ("Invoiced", "Accepted"), "to": "Delivered"},
	"Reopened": {"from": ("Rejected",), "to": "Sent To Distributor"},
}

# Which moves each check box on the portal user governs.
ORDER_ACTIONS = tuple(TRANSITIONS)


# --------------------------------------------------------------------------------------
# who is asking
# --------------------------------------------------------------------------------------


def me(user: str | None = None) -> frappe._dict:
	"""The portal row behind this session, or a refusal.

	Refusing rather than returning None matters: a caller that forgot to check would otherwise
	fall through to an unscoped query, and an unscoped query on this module hands one depot
	another depot's order book.
	"""
	user = user or frappe.session.user
	if user == "Guest":
		frappe.throw(frappe._("Please sign in."), frappe.PermissionError)

	row = frappe.db.get_value(
		"FieldMate Portal User", {"user": user},
		# Every right this row carries. A field left out here reads as zero in `may()` - not as
		# "not asked for" - so a login would be refused something it had been granted, and the
		# only clue would be a refusal message about a permission the depot can see is ticked.
		["name", "user", "distributor", "designation", "is_active",
		 "can_accept_orders", "can_raise_claims", "can_upload_sales"],
		as_dict=True,
	)
	if not row:
		frappe.throw(
			frappe._("This login is not attached to a distributor."), frappe.PermissionError)
	if not cint(row.is_active):
		frappe.throw(
			frappe._("This login has been deactivated. Ask your depot to contact us."),
			frappe.PermissionError)
	return row


def distributor_of(user: str | None = None) -> str | None:
	"""The distributor behind a session, or None for anyone who is not a portal user.

	Used by the permission hooks, which run for every session on the site and must stay quiet
	for the ones this module has nothing to say about.
	"""
	user = user or frappe.session.user
	if user in ("Guest", "Administrator"):
		return None
	if PORTAL_ROLE not in frappe.get_roles(user):
		return None
	return frappe.db.get_value(
		"FieldMate Portal User", {"user": user, "is_active": 1}, "distributor")


def touch(row) -> None:
	frappe.db.set_value("FieldMate Portal User", row.name, "last_seen_on", now_datetime(),
	                    update_modified=False)


def assert_scope(doctype: str, name: str, row=None) -> frappe._dict:
	"""Load a document and refuse it if it belongs to another depot.

	Gate 9 criterion 1 is this function. The message says the document was not found rather than
	that it belongs to somebody else, because the second phrasing confirms to whoever is probing
	that the name they guessed is real.
	"""
	row = row or me()
	owner = frappe.db.get_value(doctype, name, "distributor")
	if not owner or owner != row.distributor:
		frappe.throw(
			frappe._("{0} {1} was not found.").format(frappe._(doctype), name),
			frappe.PermissionError)
	return row


def may(row, action: str) -> None:
	if action in ORDER_ACTIONS and not cint(row.can_accept_orders):
		frappe.throw(
			frappe._("Your login can read the order queue but not work it. Ask whoever set it "
			         "up at your depot."),
			frappe.PermissionError)
	if action == "claim" and not cint(row.can_raise_claims):
		frappe.throw(
			frappe._("Your login cannot raise claims."), frappe.PermissionError)
	if action == "secondary_sales" and not cint(row.can_upload_sales):
		frappe.throw(
			frappe._("Your login cannot send sales files. Ask whoever set it up at your depot."),
			frappe.PermissionError)


# --------------------------------------------------------------------------------------
# permission hooks — the same refusal, applied by the framework
# --------------------------------------------------------------------------------------


def order_query(user: str | None = None) -> str:
	"""Narrow an order list to whoever is asking.

	Two scopes, because two kinds of session read orders. A depot sees its own queue. A **rep
	sees their own orders and nobody else's** - which this did not do at all: `_scope_query`
	returns an empty string for anyone who is not a portal user, and an empty string is no
	condition, so one rep could list every other rep's book.

	A manager matches neither and sees everything, which is the job.
	"""
	depot = _scope_query("FieldMate Order", user)
	if depot:
		return depot

	from fieldmate.services import field_user as field_user_service

	return field_user_service.own_rows_query("FieldMate Order", user)


def claim_query(user: str | None = None) -> str:
	return _scope_query("FieldMate Claim", user)


def _scope_query(doctype: str, user: str | None) -> str:
	"""A WHERE fragment narrowing a list to this session's depot.

	This is belt and braces over `assert_scope`. The service layer is what the portal calls, but
	a report, a Desk list or a plain `frappe.get_list` elsewhere in the app would not go through
	it - and a portal session reaching any of those must still see only its own depot.
	"""
	distributor = distributor_of(user)
	if not distributor:
		return ""
	table = f"`tab{doctype}`"
	return f"{table}.distributor = {frappe.db.escape(distributor)}"


def order_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
	"""The same two scopes as `order_query`, for an order opened by name rather than listed."""
	if distributor_of(user):
		return _scope_doc(doc, user)

	from fieldmate.services import field_user as field_user_service

	return field_user_service.own_row(doc, user)


def claim_permission(doc, user: str | None = None, permission_type: str | None = None) -> bool:
	return _scope_doc(doc, user)


def _scope_doc(doc, user: str | None) -> bool:
	distributor = distributor_of(user)
	if not distributor:
		return True
	return getattr(doc, "distributor", None) == distributor


# --------------------------------------------------------------------------------------
# the order queue
# --------------------------------------------------------------------------------------


def _queue_filters(status: str | None, search: str | None, row) -> tuple[dict, dict | None]:
	"""What this depot may see, and what they asked for.

	The search used to be applied in Python **after** the page came back, which meant it only
	ever searched the first hundred orders: a depot looking for an order further down their own
	queue was told it did not exist. It is part of the query now, which is also the only way a
	page and a search can both be true at once.
	"""
	filters = {"distributor": row.distributor, "docstatus": 1}
	if status:
		filters["order_status"] = status
	else:
		# A depot works the tail of the pipe. Everything before Sent To Distributor is ours and
		# none of their business, and showing it would invite questions we do not want asked at
		# a depot about an order a manager has not approved yet.
		filters["order_status"] = ["in", ["Sent To Distributor", "Accepted", "Invoiced",
		                                  "Delivered", "Rejected"]]

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = {"name": ["like", like], "outlet": ["like", like],
		              "field_user": ["like", like]}
	return filters, or_filters


def count_orders(status: str | None = None, search: str | None = None, row=None) -> int:
	"""How many orders match, so the queue can say what it is a page of.

	`frappe.db.count` rather than the permission-aware helper in `services.paging`: a depot login
	is a Website User with no desk permissions at all, so a permission-filtered count would answer
	zero. The security boundary here is the `distributor` filter above - the same one the page
	itself is read through - and it is applied to both.
	"""
	row = row or me()
	filters, or_filters = _queue_filters(status, search, row)
	if not or_filters:
		return frappe.db.count("FieldMate Order", filters)
	# `db.count` takes no or_filters, so the aggregate goes through get_all - which is already
	# how the page itself is read.
	got = frappe.get_all("FieldMate Order", filters=filters, or_filters=or_filters,
	                     fields=["count(name) as total"])
	return cint(got[0].total) if got else 0


def orders(status: str | None = None, search: str | None = None, limit: int = 100,
           row=None, start: int = 0) -> list[dict]:
	row = row or me()
	filters, or_filters = _queue_filters(status, search, row)

	rows = frappe.get_all(
		"FieldMate Order",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "order_date", "outlet", "field_user", "net_total", "gross_total",
		        "discount_total", "total_qty", "total_lines", "order_status", "payment_term",
		        "credit_days", "expected_delivery_date", "sent_to_distributor_on",
		        "distributor_reference", "credit_status", "remarks", "delivery_instructions"],
		order_by="sent_to_distributor_on asc, creation asc",
		limit_start=start,
		limit_page_length=limit,
	)
	_decorate(rows)
	return rows


def _decorate(rows: list) -> None:
	"""Put names on the links, in two queries rather than two per row.

	A depot reads shop names and rep names, not FM-OUT-05153. Fetching them one row at a time is
	the sort of thing that reads fine on a queue of five and times out on a queue of four hundred.
	"""
	outlets = {r.outlet for r in rows if r.outlet}
	users = {r.field_user for r in rows if r.field_user}

	shops = {
		row.name: row for row in frappe.get_all(
			"FieldMate Outlet", filters={"name": ["in", list(outlets)]},
			fields=["name", "outlet_name", "territory"], limit_page_length=0)
	} if outlets else {}
	reps = dict(frappe.get_all(
		"FieldMate Field User", filters={"name": ["in", list(users)]},
		fields=["name", "full_name"], as_list=True, limit_page_length=0)) if users else {}

	for r in rows:
		shop = shops.get(r.outlet)
		r.outlet_name = (shop.outlet_name if shop else None) or r.outlet
		r.outlet_territory = shop.territory if shop else None
		r.rep_name = reps.get(r.field_user) or r.field_user


def order_detail(order: str, row=None) -> dict:
	row = assert_scope("FieldMate Order", order, row)
	doc = frappe.get_doc("FieldMate Order", order)
	return {
		"name": doc.name,
		"order_date": str(doc.order_date) if doc.order_date else None,
		"outlet": doc.outlet,
		"outlet_name": frappe.db.get_value("FieldMate Outlet", doc.outlet, "outlet_name"),
		"field_user": doc.field_user,
		"rep_name": frappe.db.get_value("FieldMate Field User", doc.field_user, "full_name"),
		"order_status": doc.order_status,
		"payment_term": doc.payment_term,
		"credit_days": doc.credit_days,
		"credit_status": doc.credit_status,
		"expected_delivery_date": str(doc.expected_delivery_date) if doc.expected_delivery_date else None,
		"delivery_instructions": doc.delivery_instructions,
		"distributor_reference": doc.distributor_reference,
		"sent_to_distributor_on": str(doc.sent_to_distributor_on) if doc.sent_to_distributor_on else None,
		"remarks": doc.remarks,
		"total_qty": doc.total_qty,
		"total_lines": doc.total_lines,
		"gross_total": doc.gross_total,
		"discount_total": doc.discount_total,
		"net_total": doc.net_total,
		"items": [
			# qty_display and display_uom travel with qty because the depot picks in the unit
			# the rep sold in. A picklist reading 24 pcs for an order taken as 2 cases is a
			# picklist somebody converts by hand at six in the morning.
			{"item_code": r.item_code, "item_name": r.item_name,
			 "qty_display": r.qty_display, "display_uom": r.display_uom,
			 "qty": r.qty, "uom": r.uom, "stock_uom": r.stock_uom,
			 "rate": r.rate, "price_list_rate": r.price_list_rate, "amount": r.amount,
			 "discount_amount": r.discount_amount, "gross_amount": r.gross_amount,
			 "scheme": r.scheme, "scheme_name": r.scheme_name}
			for r in (doc.items or [])
		],
		"free_goods": [
			{"item_code": r.item_code, "item_name": r.item_name, "qty": r.qty, "uom": r.uom,
			 "scheme": r.scheme, "valuation_amount": r.valuation_amount,
			 "is_posm": cint(r.is_posm)}
			for r in (doc.free_goods or [])
		],
		"schemes": [
			{"scheme": r.scheme, "scheme_name": r.scheme_name,
			 "benefit_amount": r.benefit_amount, "description": r.benefit_description}
			for r in (doc.schemes_applied or [])
		],
		"history": history(doc.name),
	}


def act(order: str, action: str, reference: str | None = None, remarks: str | None = None,
        row=None) -> dict:
	"""Move one order through the queue, and write down that it was moved.

	The log row and the status change happen in the same call because a status nobody can trace
	back to a person and a time is exactly as useful as no status at all a week later, when
	somebody is asking why a shop never got its stock.
	"""
	row = assert_scope("FieldMate Order", order, row)
	may(row, action)

	rule = TRANSITIONS.get(action)
	if not rule:
		frappe.throw(frappe._("{0} is not something that can be done to an order.").format(action))

	doc = frappe.get_doc("FieldMate Order", order)
	if doc.order_status == rule["to"]:
		# The depot tapped twice on a bad connection. The answer is the answer, not a second log
		# row claiming the order was accepted again a minute later.
		return {"order": doc.name, "order_status": doc.order_status, "repeated": True}

	if doc.order_status not in rule["from"]:
		frappe.throw(
			frappe._("This order is {0}. It cannot be marked {1} from there.")
			.format(doc.order_status.lower(), rule["to"].lower()))

	if action == "Rejected" and not remarks:
		frappe.throw(
			frappe._("Say why you are rejecting it. The rep has to tell the shop something."))
	if action == "Invoiced" and not reference:
		frappe.throw(
			frappe._("Enter your invoice number. It is the only thread from this order to the "
			         "bill you raised, and nobody can reconstruct it later."))

	was = doc.order_status
	changes = {"order_status": rule["to"]}
	if reference:
		changes["distributor_reference"] = reference

	# `modified` is bumped, and that is the whole point rather than an oversight. The rep's delta
	# pull is `modified > watermark`, so a depot move written with `update_modified=False` would
	# change the order in the database and stay invisible on the phone for ever - which is Gate 9
	# criterion 4 failing silently. Everywhere else in this app writes a server-side status with
	# update_modified off; this is the one place that must not.
	frappe.db.set_value("FieldMate Order", doc.name, changes, update_modified=True)

	log(doc, action, was, rule["to"], row=row, reference=reference, remarks=remarks)
	return {"order": doc.name, "order_status": rule["to"], "from_status": was, "repeated": False}


def log(doc, action: str, was: str, now: str, row=None, reference: str | None = None,
        remarks: str | None = None, source: str = "Portal") -> str | None:
	key = f"{doc.name}:{action}:{now}"
	existing = frappe.db.get_value("FieldMate Order Ingest Log", {"request_key": key}, "name")
	if existing:
		return existing

	entry = frappe.get_doc({
		"doctype": "FieldMate Order Ingest Log",
		"logged_on": now_datetime(),
		"order": doc.name,
		"distributor": doc.distributor,
		"portal_user": row.name if row else None,
		"acted_by": frappe.session.user,
		"action": action,
		"from_status": was,
		"to_status": now,
		"source": source,
		"distributor_reference": reference,
		"remarks": remarks,
		"request_key": key,
	})
	entry.flags.ignore_permissions = True
	entry.insert(ignore_permissions=True)
	return entry.name


def history(order: str) -> list[dict]:
	return frappe.get_all(
		"FieldMate Order Ingest Log",
		filters={"order": order},
		fields=["action", "from_status", "to_status", "acted_by", "logged_on",
		        "distributor_reference", "remarks", "source"],
		order_by="logged_on asc",
		limit_page_length=0,
	)


def queue_totals(row=None) -> dict:
	"""The four tiles across the top of the queue.

	One grouped query rather than four counts: a depot refreshes this screen all day.
	"""
	row = row or me()
	tiles = {s: {"count": 0, "value": 0.0} for s in
	         ("Sent To Distributor", "Accepted", "Invoiced", "Delivered", "Rejected")}
	for entry in frappe.get_all(
		"FieldMate Order",
		filters={"distributor": row.distributor, "docstatus": 1},
		fields=["order_status", "count(name) as count", "sum(net_total) as value"],
		group_by="order_status",
		limit_page_length=0,
	):
		if entry.order_status in tiles:
			tiles[entry.order_status] = {"count": cint(entry.count),
			                             "value": float(entry.value or 0)}

	total_count = sum(t["count"] for t in tiles.values())
	return {
		"tiles": tiles,
		"total": {"count": total_count,
		          "value": sum(t["value"] for t in tiles.values())},
	}
