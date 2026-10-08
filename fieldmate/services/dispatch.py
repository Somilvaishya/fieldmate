"""Getting a season's allocation out of the warehouse.

Allocation (step 5) decided who gets what and asked ERPNext to hold it. This turns that holding
into goods on a vehicle and a bill behind them: a Delivery Note per booking, a Sales Invoice per
note, and a Delivery Trip grouping the notes that travel together.

**There is no dispatch document either.** Same reason as the allocation: the Delivery Note is the
record of what left, the Sales Invoice is the record of what was billed, and a FieldMate table
summarising them would be a third opinion that goes stale the first time somebody amends one.
What this module keeps is nothing; what it answers, it reads back.

**It does not build a Pick List, and the plan says it should.** ERPNext refuses: a Sales Order
carrying reserved stock cannot have one, because reserving and picking are two alternative ways of
promising stock rather than two steps of the same one. The reserved path goes straight to a
Delivery Note built from the reservations. Picking instead would mean giving the allocation back
first, which is the one thing a dispatch must not do. See `compat.make_delivery_note`.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

from fieldmate import compat
from fieldmate.services import allocation as allocation_service


def ready(season: str) -> list[dict]:
	"""The bookings of a season with stock held against them, and what is held.

	Read from ERPNext's reservations rather than from anything of ours: what is dispatchable is
	what the warehouse is actually holding, and a booking somebody reverted overnight is not
	dispatchable however it looked when the page was opened.

	A booking that has already shipped is **not** here, and that is the point: ERPNext consumes
	the reservation when the goods go out. Use `notes_for` to ask what has gone.
	"""
	out = []
	for booking in allocation_service.bookings_of(season):
		held = compat.reserved_for_sales_order(booking["sales_order"])
		if not held:
			continue
		out.append({
			"order": booking["name"],
			"customer": booking["customer"],
			"sales_order": booking["sales_order"],
			"lines": len(held),
			"qty": flt(sum(flt(row.get("reserved_qty")) for row in held), 3),
		})
	return out


def _note_key(order: str) -> str:
	"""One Delivery Note per booking, keyed on the booking.

	Dispatching a season is a button somebody presses twice while a long run is still going, and
	a second note would take the same stock out of the warehouse again - a discrepancy found
	weeks later by somebody counting shelves.
	"""
	return f"{order}:DN"


def _invoice_key(delivery_note: str) -> str:
	return f"{delivery_note}:SI"


def _trip_key(season: str, on: str) -> str:
	"""One trip per season per day. A second run on the same day joins the same trip rather than
	sending a second van for the same load."""
	return f"{season}:{on}:TRIP"


def deliver(season: str, orders: list[str] | None = None, posting_date=None) -> dict:
	"""Ship what is held. One Delivery Note per booking, submitted.

	`orders` narrows it to named bookings, for a dispatch that goes out in waves. Left out, the
	whole season goes.

	Reports what it could not do rather than throwing on the first failure. A run over forty
	bookings that stops on the ninth leaves thirty-one undispatched and nobody told which - and
	the warehouse still has to load the vans this morning.
	"""
	wanted = set(orders or [])
	notes, skipped = [], []

	for row in ready(season):
		if wanted and row["order"] not in wanted:
			continue
		try:
			name = compat.make_delivery_note(
				row["sales_order"], _note_key(row["order"]), posting_date=posting_date)
		except Exception as e:
			frappe.log_error(title=f"fieldmate: dispatching {row['order']}")
			skipped.append({"order": row["order"], "reason": str(e)[:200]})
			continue

		if name:
			notes.append({"order": row["order"], "customer": row["customer"],
			              "delivery_note": name})
		else:
			skipped.append({"order": row["order"],
			                "reason": frappe._("Nothing left to ship against it.")})

	return {"season": season, "delivered": notes, "skipped": skipped}


def notes_for(season: str) -> list[str]:
	"""The Delivery Notes this season has posted, looked up by their keys.

	**Not from `ready`.** ERPNext consumes a reservation when the goods go out and stops
	reporting it, so a booking that has shipped disappears from `ready` - which is correct for
	"what can still be dispatched" and exactly wrong for "what has been". The first version of
	`invoice` read `ready` and would have found nothing to bill the moment the delivery
	succeeded.
	"""
	notes = []
	for booking in allocation_service.bookings_of(season):
		name = compat.posted_for_key("Delivery Note", _note_key(booking["name"]))
		if name:
			notes.append(name)
	return notes


def invoice(season: str, delivery_notes: list[str] | None = None) -> dict:
	"""Bill what has shipped. One Sales Invoice per Delivery Note, submitted.

	A note already invoiced is returned as it is rather than billed again - the key is on the
	note, so a run restarted after a timeout finds the invoices it already made.
	"""
	notes = delivery_notes or notes_for(season)

	invoices, skipped = [], []
	for note in notes:
		try:
			name = compat.make_sales_invoice(note, _invoice_key(note))
		except Exception as e:
			frappe.log_error(title=f"fieldmate: invoicing {note}")
			skipped.append({"delivery_note": note, "reason": str(e)[:200]})
			continue

		if name:
			invoices.append({"delivery_note": note, "sales_invoice": name})
		else:
			skipped.append({"delivery_note": note,
			                "reason": frappe._("Nothing on it left to bill.")})

	return {"season": season, "invoiced": invoices, "skipped": skipped}


def trip(season: str, on: str, vehicle: str, departure_time,
         delivery_notes: list[str] | None = None, **fields) -> dict:
	"""Group a day's Delivery Notes into one Delivery Trip, as a draft.

	`vehicle` and `departure_time` are ERPNext's requirement and a sensible one: a trip is a
	specific van leaving at a specific time, and one without either is a list of addresses.

	Left a draft on purpose. The route is still being planned and the driver may not be
	assigned; submitting it says the trip is happening when nobody has agreed to drive it.
	"""
	notes = delivery_notes or notes_for(season)
	if not notes:
		return {"season": season, "trip": None,
		        "reason": frappe._("Nothing has been delivered for this season yet.")}

	name = compat.make_delivery_trip(notes, _trip_key(season, str(on)), vehicle=vehicle,
	                                 departure_time=departure_time, **fields)
	return {"season": season, "trip": name, "stops": len(notes)}


def position(season: str) -> dict:
	"""Where a season's dispatch has got to, read back from ERPNext.

	Four numbers a planner actually asks for: booked, held, shipped, billed. Every one of them
	comes from the documents themselves - a figure we kept would be a claim, and this page exists
	to answer "what has actually gone out".
	"""
	bookings = allocation_service.bookings_of(season)
	held = shipped = billed = 0

	for booking in bookings:
		if compat.reserved_for_sales_order(booking["sales_order"]):
			held += 1
		note = compat.posted_for_key("Delivery Note", _note_key(booking["name"]))
		if note:
			shipped += 1
			if compat.posted_for_key("Sales Invoice", _invoice_key(note)):
				billed += 1

	return {
		"season": season,
		"season_name": frappe.db.get_value("FieldMate Season", season, "season_name"),
		"booked": len(bookings),
		"held": held,
		"shipped": shipped,
		"billed": billed,
	}
