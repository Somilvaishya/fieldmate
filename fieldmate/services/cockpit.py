"""Where a season has got to — booked, allocated, delivered, paid.

The four numbers everybody asks about a season, cut three ways: **by state**, so somebody can see
the shape of it at a glance; **by party**, because the next question is always "and which
distributor is that"; and **by SKU**, because the one after that is "what are we short of".

**Nothing here is stored.** Every figure is read from the documents that hold it: the booking, the
reservations ERPNext is holding, the Delivery Notes that went out, the Sales Invoices behind them
and the collections against the order. A cockpit that kept its own numbers would be a fifth
opinion to reconcile, and it would be the one nobody trusts the morning it disagrees.

That makes this module a reader with no state and no writes, which is also why it is safe to
refresh as often as a page likes.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate, nowdate

from fieldmate import compat
from fieldmate.services import collection as collection_service
from fieldmate.services import dispatch as dispatch_service

# The states a booking passes through, in the order it passes through them. Named as somebody
# looking at the page would name them rather than as the documents are named.
STATES = ("Awaiting advance", "Booked", "Allocated", "Delivered", "Billed")


def _state_of(booking: dict, held: bool, note: str | None, invoice: str | None) -> str:
	"""One booking's furthest point. Read backwards, because the last thing to happen wins."""
	if invoice:
		return "Billed"
	if note:
		return "Delivered"
	if held:
		return "Allocated"
	if booking.get("order_status") == "Awaiting Advance":
		return "Awaiting advance"
	return "Booked"


def _rows(season: str) -> list[dict]:
	"""Every booking of the season with where it has got to and what it is worth.

	The one place that walks the documents. Both views below are built from this, so they cannot
	disagree about a booking the way two queries would.
	"""
	bookings = frappe.get_all(
		"FieldMate Order",
		filters={"season": season, "docstatus": 1,
		         "order_status": ["not in", ["Cancelled", "Rejected"]]},
		fields=["name", "customer", "order_date", "order_status", "sales_order",
		        "net_total", "tax_total", "grand_total"],
		order_by="order_date asc, creation asc",
	)
	if not bookings:
		return []

	in_hand = collection_service.in_hand_by_order([b.name for b in bookings])

	rows = []
	for booking in bookings:
		held = compat.reserved_for_sales_order(booking.sales_order) if booking.sales_order else []
		note = dispatch_service_note(booking.name)
		invoice = (compat.posted_for_key("Sales Invoice", f"{note}:SI") if note else None)

		rows.append({
			"order": booking.name,
			"customer": booking.customer,
			"order_date": booking.order_date,
			"booked_value": flt(booking.grand_total) or flt(booking.net_total),
			"paid": flt(in_hand.get(booking.name) or 0),
			"reserved_qty": flt(sum(flt(r.get("reserved_qty")) for r in held), 3),
			"delivery_note": note,
			"sales_invoice": invoice,
			"state": _state_of(booking, bool(held), note, invoice),
		})
	return rows


def dispatch_service_note(order: str) -> str | None:
	"""The Delivery Note this booking shipped on, by the key dispatch gave it.

	A thin wrapper so this module does not reach into `dispatch`'s private key format - if that
	ever changes, it changes in one place.
	"""
	return compat.posted_for_key("Delivery Note", dispatch_service._note_key(order))


def by_state(season: str) -> list[dict]:
	"""How many bookings are at each point, and what they are worth.

	Every state is listed even where it holds nothing. A row missing from a summary reads as a
	state that does not exist, and "nothing has been delivered yet" is an answer somebody needs.
	"""
	rows = _rows(season)
	tally = {state: {"state": state, "bookings": 0, "value": 0.0, "paid": 0.0}
	         for state in STATES}

	for row in rows:
		bucket = tally[row["state"]]
		bucket["bookings"] += 1
		bucket["value"] = flt(bucket["value"] + row["booked_value"], 2)
		bucket["paid"] = flt(bucket["paid"] + row["paid"], 2)

	return [tally[state] for state in STATES]


def by_party(season: str) -> list[dict]:
	"""One line per distributor: what they booked, what they have paid, where they have got to.

	Sorted by what they owe, largest first. A cockpit is opened to find out who to telephone.
	"""
	rows = _rows(season)
	parties: dict[str, dict] = {}

	for row in rows:
		party = parties.setdefault(row["customer"], {
			"customer": row["customer"],
			"customer_name": frappe.db.get_value("Customer", row["customer"], "customer_name"),
			"bookings": 0, "value": 0.0, "paid": 0.0, "owing": 0.0,
			"states": [],
		})
		party["bookings"] += 1
		party["value"] = flt(party["value"] + row["booked_value"], 2)
		party["paid"] = flt(party["paid"] + row["paid"], 2)
		party["states"].append(row["state"])

	for party in parties.values():
		party["owing"] = flt(max(0.0, party["value"] - party["paid"]), 2)
		# The furthest-back booking they have, because that is the one holding them up.
		party["state"] = min(party["states"], key=lambda s: STATES.index(s))
		del party["states"]

	return sorted(parties.values(), key=lambda p: (-p["owing"], p["customer"]))


def by_sku(season: str) -> list[dict]:
	"""One line per item: booked, reserved, delivered. The "what are we short of" view.

	Quantities in stock units throughout, because that is what the warehouse counts in and what
	a reservation is held in. Mixing an order's own UOM into this is how two people reading the
	same screen disagree about whether there is enough.
	"""
	rows = _rows(season)
	if not rows:
		return []

	orders = [row["order"] for row in rows]
	booked = frappe.get_all(
		"FieldMate Order Item",
		filters={"parent": ["in", orders], "parenttype": "FieldMate Order"},
		fields=["item_code", "qty", "stock_uom"],
	)

	items: dict[str, dict] = {}
	for line in booked:
		item = items.setdefault(line.item_code, {
			"item_code": line.item_code,
			"item_name": frappe.db.get_value("Item", line.item_code, "item_name"),
			"uom": line.stock_uom,
			"booked_qty": 0.0, "reserved_qty": 0.0, "delivered_qty": 0.0,
		})
		item["booked_qty"] = flt(item["booked_qty"] + flt(line.qty), 3)

	for row in rows:
		sales_order = frappe.db.get_value("FieldMate Order", row["order"], "sales_order")
		for entry in (compat.reserved_for_sales_order(sales_order) if sales_order else []):
			item = items.get(entry.get("item_code"))
			if item:
				item["reserved_qty"] = flt(item["reserved_qty"] + flt(entry.get("reserved_qty")), 3)

		if not row["delivery_note"]:
			continue
		for line in frappe.get_all(
			"Delivery Note Item",
			filters={"parent": row["delivery_note"], "parenttype": "Delivery Note"},
			fields=["item_code", "stock_qty"],
		):
			item = items.get(line.item_code)
			if item:
				item["delivered_qty"] = flt(item["delivered_qty"] + flt(line.stock_qty), 3)

	for item in items.values():
		item["short"] = flt(max(0.0, item["booked_qty"] - item["reserved_qty"]
		                        - item["delivered_qty"]), 3)

	return sorted(items.values(), key=lambda i: (-i["short"], i["item_code"]))


def summary(season: str) -> dict:
	"""The whole cockpit in one call, so a page makes one request rather than four."""
	doc = frappe.db.get_value(
		"FieldMate Season", season,
		["season_name", "company", "festival_date", "booking_from", "booking_to",
		 "change_cutoff", "delivery_from", "delivery_to", "advance_pct", "is_active"],
		as_dict=True,
	)
	if not doc:
		frappe.throw(frappe._("{0} is not a season.").format(season))

	rows = _rows(season)
	value = flt(sum(row["booked_value"] for row in rows), 2)
	paid = flt(sum(row["paid"] for row in rows), 2)

	return {
		"season": season,
		**doc,
		"locked": is_locked(season),
		"bookings": len(rows),
		"parties": len({row["customer"] for row in rows}),
		"value": value,
		"paid": paid,
		"owing": flt(max(0.0, value - paid), 2),
		"by_state": by_state(season),
		"by_party": by_party(season),
		"by_sku": by_sku(season),
	}


def is_locked(season: str, on=None) -> bool:
	"""Has this season's book stopped moving?

	The cutoff is what locks it, not the booking window: a season routinely allows changes for a
	little while after the book shuts, and that gap is the whole reason `change_cutoff` is its
	own field.
	"""
	doc = frappe.get_cached_doc("FieldMate Season", season)
	return not doc.may_change_on(on or nowdate())


def seasons(company: str | None = None) -> list[dict]:
	"""Seasons worth opening a cockpit on, newest festival first."""
	filters = {}
	if company:
		filters["company"] = company

	rows = frappe.get_all(
		"FieldMate Season", filters=filters,
		fields=["name", "season_name", "company", "festival_date", "is_active"],
		order_by="festival_date desc",
	)
	for row in rows:
		row["bookings"] = frappe.db.count("FieldMate Order", {
			"season": row.name, "docstatus": 1,
			"order_status": ["not in", ["Cancelled", "Rejected"]],
		})
		row["locked"] = is_locked(row.name)
	return rows


def overdue_payments(on=None) -> list[dict]:
	"""Bookings whose payment schedule has a date in the past and money still owing.

	Read off the **Sales Order's** payment schedule, which ERPNext built from the season's
	Payment Terms Template, rather than from a copy of our own. The schedule finance maintains is
	the one that decides when money is late.

	Returned rather than acted on, so the daily reminder and a screen can both use it.
	"""
	on = getdate(on or nowdate())

	bookings = frappe.get_all(
		"FieldMate Order",
		filters={"order_kind": "Booking", "docstatus": 1, "sales_order": ["is", "set"],
		         "order_status": ["not in", ["Cancelled", "Rejected"]]},
		fields=["name", "customer", "season", "field_user", "sales_order", "grand_total"],
	)
	if not bookings:
		return []

	in_hand = collection_service.in_hand_by_order([b.name for b in bookings])

	late = []
	for booking in bookings:
		due = frappe.get_all(
			"Payment Schedule",
			filters={"parent": booking.sales_order, "parenttype": "Sales Order",
			         "due_date": ["<", on]},
			fields=["due_date", "payment_amount", "outstanding"],
			order_by="due_date asc",
		)
		if not due:
			continue

		owed = flt(sum(flt(row.payment_amount) for row in due))
		paid = flt(in_hand.get(booking.name) or 0)
		short = flt(owed - paid, 2)
		if short <= 0:
			continue

		late.append({
			"order": booking.name,
			"customer": booking.customer,
			"customer_name": frappe.db.get_value("Customer", booking.customer, "customer_name"),
			"season": booking.season,
			"field_user": booking.field_user,
			"due_on": due[0].due_date,
			"days_late": (on - getdate(due[0].due_date)).days,
			"due": owed,
			"paid": paid,
			"short": short,
		})

	return sorted(late, key=lambda row: (-row["days_late"], row["order"]))


def remind_overdue(on=None) -> dict:
	"""Tell whoever can do something about a late booking payment. Once a day, once a booking.

	The rep who booked it, because they are the one who collects, and their manager, because
	they are the one who asks. Not the party: this app has never sent anything to a customer and
	starting here, through a channel nobody has configured, would be a surprise.

	A Notification Log rather than an email, for the reason `alerts._notify` gives: an email
	nobody set up goes nowhere and reports success, and a manager reading this is already inside
	Desk.

	Cooled down per booking per day, so a job that runs twice does not tell anybody twice.
	"""
	late = overdue_payments(on)
	if not late:
		return {"overdue": 0, "told": 0}

	today = str(getdate(on or nowdate()))
	told = 0

	for row in late:
		recipients = _who_to_tell(row["field_user"])
		if not recipients:
			continue

		subject = frappe._("{0} is {1} day(s) late on {2}").format(
			row["customer_name"] or row["customer"], row["days_late"], row["season"])
		body = frappe._(
			"{0} owes {1} on booking {2}, due {3}. {4} has been received."
		).format(row["customer_name"] or row["customer"], row["short"], row["order"],
		         frappe.utils.formatdate(row["due_on"]), row["paid"])

		for user in recipients:
			if _already_told(user, row["order"], today):
				continue
			try:
				frappe.get_doc({
					"doctype": "Notification Log",
					"for_user": user,
					"type": "Alert",
					"document_type": "FieldMate Order",
					"document_name": row["order"],
					"subject": subject,
					"email_content": body,
				}).insert(ignore_permissions=True)
				told += 1
			except Exception:
				# One bad recipient must not swallow the rest, and must not stop the run.
				frappe.log_error(title=f"fieldmate: reminding {user} about {row['order']}")

	return {"overdue": len(late), "told": told}


def _who_to_tell(field_user: str | None) -> list[str]:
	"""The rep who booked it and their manager, as user ids, enabled only."""
	if not field_user:
		return []

	people = []
	rep = frappe.db.get_value("FieldMate Field User", field_user, ["user", "reports_to"],
	                          as_dict=True)
	if rep and rep.user:
		people.append(rep.user)
	if rep and rep.reports_to:
		manager = frappe.db.get_value("FieldMate Field User", rep.reports_to, "user")
		if manager:
			people.append(manager)

	return [u for u in dict.fromkeys(people)
	        if u not in ("Administrator", "Guest") and frappe.db.get_value("User", u, "enabled")]


def _already_told(user: str, order: str, on: str) -> bool:
	"""Has this person already been told about this booking today?

	Read off the Notification Log itself rather than kept in a table of our own. A reminder that
	needed its own ledger to avoid repeating itself would be a second thing to keep in step.
	"""
	return bool(frappe.db.exists("Notification Log", {
		"for_user": user,
		"document_type": "FieldMate Order",
		"document_name": order,
		"creation": [">=", f"{on} 00:00:00"],
	}))
