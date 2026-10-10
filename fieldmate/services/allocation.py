"""Who gets the stock when a season is short of it.

**There is no allocation document, deliberately.** The decision is FieldMate's; the record of it
is ERPNext's Stock Reservation Entry. A second table of who-gets-what would be a second answer to
a question the warehouse already answers, and the two would disagree the first time somebody
delivered something. Applying creates reservations, reverting cancels them, and a figure nobody
can tie back to a reservation is not an allocation - it is a spreadsheet.

So this module is arithmetic and one seam. It reads what was booked, asks `compat` what is
actually available, splits the difference by one of three rules, and asks `compat` to hold it.

**Preview, then apply, is the whole shape.** A short season is somebody's commercial decision -
which distributor is told they are getting two thirds of what they asked for - and nobody should
make it by pressing a button and seeing what happened. The preview is the same arithmetic as the
apply, run against the same figures, so what is shown is what will be reserved.
"""

from __future__ import annotations

import frappe
from frappe.utils import flt

from fieldmate import compat
from fieldmate.services import collection as collection_service

# How short stock is divided. Named as the people arguing about it name them.
ADVANCE_FIRST = "Advance First"
FIRST_BOOKED = "First Booked"
PRO_RATA = "Pro Rata"
RULES = (ADVANCE_FIRST, FIRST_BOOKED, PRO_RATA)


def bookings_of(season: str) -> list[dict]:
	"""The released bookings of a season, with the Sales Order each one posted.

	Only released ones. A booking still waiting for its advance has no Sales Order, so there is
	no line to reserve against - and reserving stock for an order nobody has paid for is the
	thing the advance hold exists to prevent.
	"""
	rows = frappe.get_all(
		"FieldMate Order",
		filters={"season": season, "docstatus": 1, "sales_order": ["is", "set"],
		         "order_status": ["not in", ["Cancelled", "Rejected"]]},
		fields=["name", "customer", "order_date", "creation", "sales_order", "net_total"],
		order_by="order_date asc, creation asc",
	)
	if not rows:
		return []

	paid = collection_service.in_hand_by_order([row.name for row in rows])
	for row in rows:
		row["in_hand"] = flt(paid.get(row.name) or 0)
		# As a share of the booking, not as a figure: "paid more" between two bookings of
		# different sizes is a comparison of proportions, and the rule is named Advance First
		# because it is about who committed hardest, not who is biggest.
		row["advance_share"] = flt(row["in_hand"] / row["net_total"]) if row["net_total"] else 0.0
	return rows


def demand(bookings: list[dict]) -> list[dict]:
	"""What every booking asks for, per Sales Order line, in stock units.

	Read off the Sales Order rather than the FieldMate Order: the Sales Order is the commitment,
	it is what carries the warehouse ERPNext will reserve from, and `sales_order_item` is what
	the reservation points at. Reading our own line and hoping the two agree is how an allocation
	reserves against the wrong warehouse.
	"""
	if not bookings:
		return []

	by_so = {row["sales_order"]: row for row in bookings}
	lines = frappe.get_all(
		"Sales Order Item",
		filters={"parent": ["in", list(by_so)], "parenttype": "Sales Order"},
		fields=["name", "parent", "item_code", "warehouse", "stock_qty", "stock_uom", "idx"],
		order_by="parent asc, idx asc",
	)

	out = []
	for line in lines:
		booking = by_so[line.parent]
		out.append({
			"order": booking["name"],
			"customer": booking["customer"],
			"order_date": booking["order_date"],
			"advance_share": booking["advance_share"],
			"sales_order": line.parent,
			"sales_order_item": line.name,
			"item_code": line.item_code,
			"warehouse": line.warehouse,
			"uom": line.stock_uom,
			"asked": flt(line.stock_qty),
		})
	return out


def split(rows: list[dict], available: float, rule: str) -> None:
	"""Divide `available` across `rows`, writing `allocated` on each. One item, one warehouse.

	Mutates rather than returns, because the caller is building a table a person will read and
	the rows carry everything else about the booking already.

	The three rules are the three arguments people actually have:

	- **Advance First** — whoever committed hardest is served first, by the share of their own
	  booking they have paid. Ties fall back to who booked first, so the order is total and two
	  previews of the same figures cannot differ.
	- **First Booked** — the queue, in the order the orders were taken.
	- **Pro Rata** — everybody is cut by the same proportion.

	Pro rata floors each share and hands the remainder to the largest ask, ties broken by order
	name. The same rule, and the same reason, as apportioning a cart discount in `services/tax`:
	a stray unit has to land somewhere, and it has to land in the same place on every machine
	that computes it.
	"""
	for row in rows:
		row["allocated"] = 0.0

	asked_total = sum(flt(row["asked"]) for row in rows)
	if asked_total <= 0 or available <= 0:
		return

	if available >= asked_total:
		for row in rows:
			row["allocated"] = flt(row["asked"])
		return

	if rule == PRO_RATA:
		assigned = 0.0
		for row in rows:
			row["allocated"] = float(int(available * flt(row["asked"]) / asked_total))
			assigned += row["allocated"]
		left = available - assigned
		if left > 0:
			biggest = max(rows, key=lambda r: (flt(r["asked"]), str(r["order"])))
			biggest["allocated"] = flt(biggest["allocated"]) + left
		return

	if rule == ADVANCE_FIRST:
		queue = sorted(rows, key=lambda r: (-flt(r["advance_share"]), str(r["order_date"]),
		                                    str(r["order"])))
	else:
		queue = sorted(rows, key=lambda r: (str(r["order_date"]), str(r["order"])))

	left = available
	for row in queue:
		take = min(flt(row["asked"]), left)
		row["allocated"] = take
		left -= take
		if left <= 0:
			break


def preview(season: str, rule: str = ADVANCE_FIRST) -> dict:
	"""What each booking would get, and what is left short. Changes nothing.

	The availability is read **now**, so a preview run after an apply shows what is left rather
	than what was there to begin with - ERPNext subtracts live reservations from what it calls
	available. Reverting first is what gives a clean slate, which is why revert exists.
	"""
	if rule not in RULES:
		frappe.throw(frappe._("{0} is not a way of allocating. Choose one of: {1}.")
		             .format(rule, ", ".join(RULES)))

	if not compat.stock_reservation_enabled():
		# Said plainly rather than returning an empty table. A page that silently allocates
		# nothing on a site where the feature is off is a page nobody can debug.
		frappe.throw(frappe._(
			"Stock reservation is switched off for this site, so nothing can be allocated. "
			"Switch on Enable Stock Reservation in Stock Settings."))

	rows = demand(bookings_of(season))
	groups: dict[tuple, list] = {}
	for row in rows:
		groups.setdefault((row["item_code"], row["warehouse"]), []).append(row)

	items = []
	for (item_code, warehouse), lines in sorted(groups.items(), key=lambda kv: str(kv[0])):
		available = compat.available_to_reserve(item_code, warehouse)
		split(lines, available, rule)
		asked = sum(flt(line["asked"]) for line in lines)
		given = sum(flt(line["allocated"]) for line in lines)
		items.append({
			"item_code": item_code,
			"warehouse": warehouse,
			"uom": lines[0]["uom"],
			"asked": asked,
			"available": available,
			"allocated": given,
			"short": flt(max(0.0, asked - given), 3),
			"lines": lines,
		})

	return {
		"season": season,
		"season_name": frappe.db.get_value("FieldMate Season", season, "season_name"),
		"rule": rule,
		"bookings": len({row["order"] for row in rows}),
		"items": items,
		# Already held against these bookings, so a person can see whether they are looking at a
		# season that has been allocated before.
		"already_reserved": sum(
			len(compat.reserved_for_sales_order(so))
			for so in {row["sales_order"] for row in rows}
		),
	}


def apply(season: str, rule: str = ADVANCE_FIRST) -> dict:
	"""Reserve what the preview says. The reservations are the record of the allocation."""
	plan = preview(season, rule)

	by_order: dict[str, list] = {}
	for item in plan["items"]:
		for line in item["lines"]:
			if flt(line["allocated"]) > 0:
				by_order.setdefault(line["sales_order"], []).append({
					"sales_order_item": line["sales_order_item"],
					"warehouse": line["warehouse"],
					"qty": line["allocated"],
				})

	reserved = 0
	for sales_order, lines in by_order.items():
		reserved += compat.reserve_for_sales_order(sales_order, lines)

	plan["reserved_entries"] = reserved
	return plan


def revert(season: str) -> dict:
	"""Give back everything this season is holding, so it can be allocated again.

	Anything already delivered stays where it is - ERPNext will not cancel a delivered
	reservation, and stock that has left the building is not something a rule can redistribute.
	"""
	orders = {row["sales_order"] for row in bookings_of(season)}
	released = sum(compat.release_reservations(so) for so in orders)
	return {"season": season, "sales_orders": len(orders), "released": released}


def held_by(season: str) -> list[dict]:
	"""What this season is actually holding right now, read back from ERPNext.

	The answer to "what did we allocate" is this, and never a stored figure of our own. A number
	we kept would be a claim; this is the warehouse's own record.
	"""
	out = []
	for booking in bookings_of(season):
		for entry in compat.reserved_for_sales_order(booking["sales_order"]):
			out.append({
				"order": booking["name"],
				"customer": booking["customer"],
				"sales_order": booking["sales_order"],
				"item_code": entry.get("item_code"),
				"warehouse": entry.get("warehouse"),
				"reserved": flt(entry.get("reserved_qty")),
			})
	return out


def seasons_worth_allocating() -> list[dict]:
	"""Seasons with released bookings against them, for the page's own picker."""
	rows = frappe.get_all(
		"FieldMate Season",
		filters={"is_active": 1},
		fields=["name", "season_name", "company", "festival_date"],
		order_by="festival_date asc",
	)
	for row in rows:
		row["bookings"] = frappe.db.count("FieldMate Order", {
			"season": row.name, "docstatus": 1, "sales_order": ["is", "set"],
			"order_status": ["not in", ["Cancelled", "Rejected"]],
		})
	return [row for row in rows if row["bookings"]]
