"""What a rep sees when the order screen opens at a shop.

Two reads, and between them they are the whole screen: the list of things this shop may be sold,
and what this shop ordered last time. Nothing here writes anything and nothing here commits the
company to anything. A FieldMate Order taken at a retail outlet is a secondary sale, terminal in
our books, routed to the distributor's queue and posting nothing (ADR-023) - so this module reads
prices and masters and stops there.

Three constraints shape every line of it.

**An item with no price is not an item priced at zero.** A Currency column is NOT NULL DEFAULT 0,
`flt(None)` is `0.0`, and every convenience in the framework wants to collapse the two. A rate of
0.00 on this screen lets a rep book a pallet of soap for nothing, and nobody finds out until the
distributor reads his own invoice weeks later. So an unpriced item comes back with `rate: None`
and `unpriceable: True`, loudly enough that the screen can grey it out rather than sell it.

**The screen asks for hundreds of SKUs on a 2G uplink.** Every price, every conversion factor and
every item name for the whole catalogue arrives in one call to `compat.get_item_details`. A loop
calling `get_item_price` per row would be correct and unusable - a rep watching a spinner in a
market closes the app and writes the order in a notebook.

**Scoping is the security boundary.** Reads go through `frappe.get_list(user=...)`, never
`frappe.get_all`, which forces `ignore_permissions=True` and would hand every rep the catalogue,
the prices and the order history of every shop on the site.
"""

from __future__ import annotations

import math

import frappe
from frappe.utils import cint, flt, getdate, today

from fieldmate import compat
from fieldmate.services import credit as credit_service
from fieldmate.services import pricing
from fieldmate.services import scope
from fieldmate.services import settings as settings_service
from fieldmate.services import tax as tax_service

# --------------------------------------------------------------------------------------
# the sellable list
# --------------------------------------------------------------------------------------


def for_outlet(outlet, field_user: str | None = None, price_list: str | None = None,
                party_type: str | None = None) -> dict:
	"""Everything this shop may be sold today, priced, in one payload.

	`price_list` is for our own callers - the order estimate re-prices against the list the
	order was written on. It is never taken from a device: a phone that could name its own
	price list could quote the cart off whichever one is cheapest.
	"""
	doc = readable_party(outlet, party_type)
	on = getdate(today())
	price_list = price_list or resolve_price_list(doc, field_user)
	company = resolve_company(field_user)
	channel = credit_service.billing_party(doc, field_user, party_type)
	party = channel["party"]

	catalogues = matching_masters("FieldMate Product Catalogue", doc, on)
	rows = catalogue_rows(catalogues)
	must_sell = must_sell_rows(matching_masters("FieldMate Must Sell List", doc, on))

	# One call, whatever the length of the list. This is the line the whole module is built
	# around; see the note at the top about what a per-item read costs a rep in a market.
	details = {
		row["item_code"]: row
		for row in compat.get_item_details(
			list(rows), price_list=price_list, company=company, customer=party
		)
	}

	# The rate per item, not the tax amount. The phone computes the amount itself as quantities
	# change - it has the same `round_half_up_div` the server uses - so what travels is one
	# number per item rather than a figure that goes stale on the next tap.
	tax_rates = tax_service.rates_for(
		list(details), company=company, party=party,
		net_rates={code: d["price_list_rate"] for code, d in details.items()},
		item_groups={code: d["item_group"] for code, d in details.items()},
	)

	items = []
	for item_code, (row, catalogue) in rows.items():
		detail = details.get(item_code)
		if not detail or detail["disabled"]:
			# A catalogue naming an item that has since been deleted or disabled is a master
			# nobody tidied, not something to put in front of a shopkeeper.
			continue
		items.append(item_payload(item_code, row, catalogue, detail, must_sell.get(item_code),
		                          tax_bps=tax_rates.get(item_code, 0)))

	items.sort(key=lambda row: (row["sort_order"], row["item_name"] or row["item_code"]))

	return {
		"outlet": doc.name,
		"outlet_name": doc.outlet_name,
		"as_of": str(on),
		"price_list": price_list,
		"currency": next((i["currency"] for i in items if i["currency"]), None),
		"company": company,
		"billing_party": party,
		"catalogues": [c.name for c in catalogues],
		"item_count": len(items),
		# Counted rather than left to the screen, because this is the number a manager should be
		# asked about: a catalogue of 400 lines with 90 of them unpriceable is a pricing job
		# nobody has done, and it is invisible unless somebody says it out loud.
		"unpriceable_count": sum(1 for i in items if i["unpriceable"]),
		"items": items,
	}


def item_payload(item_code: str, row, catalogue: str, detail: dict, must_sell,
                 tax_bps: int = 0) -> dict:
	"""One catalogue line as the phone receives it."""
	order_uom, conversion_factor, fell_back = order_unit(row, detail)
	rate = detail["price_list_rate"]

	return {
		"item_code": item_code,
		"item_name": detail["item_name"] or row.item_name,
		"item_group": detail["item_group"],
		"brand": detail["brand"],

		"stock_uom": detail["stock_uom"],
		"sales_uom": detail["sales_uom"],
		# What the rep types a number against. Usually the sales UOM, overridden where the
		# catalogue insists on cases, and forced back to the base unit when the item carries no
		# conversion for it - see order_unit for why that is the safe way to fail.
		"order_uom": order_uom,
		"conversion_factor": conversion_factor,
		"order_uom_fallback": fell_back,

		# Per base unit, which is the unit every other number here agrees with, and the unit the
		# scheme engine measures in. None means nobody has priced it - never 0.00.
		"rate": rate,
		"order_uom_rate": None if rate is None else flt(rate * conversion_factor, 2),
		"currency": detail["currency"],
		"mrp": detail["mrp"],
		"unpriceable": rate is None,
		# A price list that quotes above the printed price on the pack. Flagged on the catalogue
		# screen so a rep sees it before building a cart, and refused at the order. Both figures
		# are per stock UOM - see `pricing.is_above_mrp` for why `order_uom_rate` is not the one
		# to compare.
		"above_mrp": pricing.is_above_mrp(rate, detail["mrp"]),

		# The distributor's tax rate on this item, in basis points - 1800 is 18%. Zero means no
		# tax template covers it, which is most items on most ERPNext sites. The phone applies it
		# to the line's share of the net; `services/tax` holds the rule and the reason.
		"tax_bps": int(tax_bps or 0),

		"is_focus": bool(cint(row.is_focus)),
		"is_must_sell": bool(must_sell),
		"must_sell_min_qty": (flt(must_sell.min_qty) or None) if must_sell else None,
		# A Float column is NOT NULL DEFAULT 0, so zero here is a limit nobody typed rather than
		# a limit of nothing. None says "no limit", which is what the screen has to show.
		"min_order_qty": flt(row.min_order_qty) or None,
		"max_order_qty": flt(row.max_order_qty) or None,

		"catalogue": catalogue,
		"sort_order": cint(row.sort_order),
		"notes": row.notes or None,
	}


def order_unit(row, detail: dict) -> tuple[str, float, bool]:
	"""The unit the rep books in, and how many base units one of them is.

	A catalogue may ask for orders in cases while the price list quotes pieces, which is ordinary
	and fine as long as the item carries the conversion. Where it does not, we drop back to the
	base unit rather than guess at one: booking "2 Case" against a per-piece rate would bill a
	twelfth of what was sold, and unlike a missing price it would look entirely normal on the
	screen. Ordering in pieces is an inconvenience; a case sold at a piece price is a loss.
	"""
	base = detail["stock_uom"]
	wanted = row.uom or detail["sales_uom"] or base
	if wanted == base:
		return base, 1.0, False

	factor = flt(detail["uom_conversions"].get(wanted))
	if not factor:
		return base, 1.0, True
	return wanted, factor, False


# --------------------------------------------------------------------------------------
# the repeat order
# --------------------------------------------------------------------------------------


def last_order_for(outlet, field_user: str | None = None) -> dict:
	"""The previous order at this shop, keyed by item code, for the repeat-order prefill.

	DESIGN.md asks for a repeat order in two taps rather than forty, and this is the half of it
	the server owes: the quantities the phone drops straight into the cart.

	Every item that appeared on that order carries `has_order_history: True`, **including the
	ones ordered at zero**. A Float cannot tell a SKU this shop has never stocked from one the
	shopkeeper looked at last month and waved away, and those are opposite instructions to a
	rep: the first is a line to pitch, the second is a line to stop pitching. An item absent
	from this map has no history at all.

	What comes back is what *this rep* booked here. A FieldMate Field Rep reads FieldMate Order
	only as its owner, so `get_list` returns a colleague's order to nobody - a relief rep
	covering the route sees an empty prefill rather than somebody else's.
	"""
	doc = readable_outlet(outlet)
	user = frappe.session.user

	orders = frappe.get_list(
		"FieldMate Order",
		filters={"outlet": doc.name, "docstatus": 1},
		fields=["name", "order_date"],
		order_by="order_date desc, creation desc",
		limit_page_length=1,
		ignore_permissions=False,
		user=user,
	)

	payload = {
		"outlet": doc.name,
		"order": None,
		"order_date": None,
		"has_order_history": False,
		"items": {},
	}
	if not orders:
		return payload

	order = orders[0]
	payload["order"] = order.name
	payload["order_date"] = str(order.order_date) if order.order_date else None
	payload["has_order_history"] = True

	# A child table carries no permissions of its own; the parent was just proved readable above,
	# which is the check that matters.
	lines = frappe.get_all(
		"FieldMate Order Item",
		filters={"parent": order.name, "parenttype": "FieldMate Order"},
		fields=["item_code", "item_name", "qty", "qty_display", "display_uom",
		        "conversion_factor", "is_free_item"],
		order_by="idx asc",
	)

	merged = {}
	for line in lines:
		if cint(line.is_free_item):
			# Free goods were granted by a scheme, not asked for. Prefilling them would have the
			# rep re-ordering what the last scheme gave away, and paying for it this time.
			continue

		factor = flt(line.conversion_factor) or 1.0
		base_qty = flt(line.qty) or flt(line.qty_display) * factor

		entry = merged.get(line.item_code)
		if entry is None:
			merged[line.item_code] = {
				"item_name": line.item_name,
				"last_ordered_uom": line.display_uom,
				"last_ordered_on": payload["order_date"],
				"has_order_history": True,
				"_factor": factor,
				"_base_qty": base_qty,
			}
			continue

		# A rep can add the same SKU twice, and the two rows need not share a unit. Summing in
		# base units and restating in the first row's unit is the only arithmetic that survives
		# a cart holding both "1 Case" and "6 Nos" of the same soap.
		entry["_base_qty"] = entry["_base_qty"] + base_qty

	for item_code, entry in merged.items():
		factor = entry.pop("_factor")
		base_qty = entry.pop("_base_qty")
		entry["last_ordered_qty"] = flt(base_qty / factor, 3)
		entry["last_ordered_base_qty"] = flt(base_qty, 3)
		payload["items"][item_code] = entry

	return payload


# --------------------------------------------------------------------------------------
# re-pricing a cart that already exists
# --------------------------------------------------------------------------------------


def prices_for(outlet, lines, field_user: str | None = None) -> dict:
	"""Fresh rates for a cart the rep already built, and nothing else.

	The phone holds prices from whenever it last synced, which may have been yesterday morning
	in a different market. This is the call it makes before the rep reads a total out loud.

	Each line is `{"item_code": ..., "qty": ...}` with the quantity in **base units**, because
	that is what a quantity break on Item Price is measured in and the phone already holds the
	conversion factor from `for_outlet`. A bare item code is accepted too.

	Only items this shop's own catalogue holds are priced. An endpoint that priced anything on
	the site would be a way to read the whole price book one item at a time from a phone.
	"""
	doc = readable_outlet(outlet)
	on = getdate(today())
	price_list = resolve_price_list(doc, field_user)
	company = resolve_company(field_user)
	party = credit_service.billing_party(doc, field_user)["party"]

	wanted = {}
	for line in lines or []:
		if isinstance(line, str):
			wanted.setdefault(line, 0.0)
			continue
		code = line.get("item_code") or line.get("item")
		if code:
			wanted[code] = flt(wanted.get(code)) + flt(line.get("qty"))

	sellable = catalogue_rows(matching_masters("FieldMate Product Catalogue", doc, on))
	off_catalogue = sorted(code for code in wanted if code not in sellable)
	codes = [code for code in wanted if code in sellable]

	details = {
		row["item_code"]: row
		for row in compat.get_item_details(
			codes,
			price_list=price_list,
			company=company,
			customer=party,
			quantities={code: qty for code, qty in wanted.items() if qty},
		)
	}

	priced = {}
	for code in codes:
		detail = details.get(code)
		if not detail:
			continue
		row = sellable[code][0]
		order_uom, conversion_factor, _ = order_unit(row, detail)
		rate = detail["price_list_rate"]
		priced[code] = {
			"rate": rate,
			"order_uom": order_uom,
			"conversion_factor": conversion_factor,
			"order_uom_rate": None if rate is None else flt(rate * conversion_factor, 2),
			"currency": detail["currency"],
			"mrp": detail["mrp"],
			"unpriceable": rate is None,
			# Per stock UOM on both sides, never `order_uom_rate` - see `pricing.is_above_mrp`.
			"above_mrp": pricing.is_above_mrp(rate, detail["mrp"]),
		}

	return {
		"outlet": doc.name,
		"as_of": str(on),
		"price_list": price_list,
		"currency": next((p["currency"] for p in priced.values() if p["currency"]), None),
		"items": priced,
		"unpriceable": sorted(code for code, p in priced.items() if p["unpriceable"]),
		"above_mrp": sorted(code for code, p in priced.items() if p["above_mrp"]),
		# Named rather than dropped in silence. A cart holding a line this shop may not be sold
		# is a bug somewhere upstream, and the rep is the last person who should discover it.
		"not_in_catalogue": off_catalogue,
	}


def cart_for(outlet, lines, field_user: str | None = None, price_list: str | None = None,
             party_type: str | None = None) -> dict:
	"""A rep's cart restated as the scheme engine's input: base units and integer paise.

	The engine is a pure function and reads no price, no UOM and no clock (ADR-021), so this is
	where a cart of "2 Case of SE-1000" becomes `{"item": "SE-1000", "qty": 24,
	"rate_paise": 12200}`. The rates are the server's own, not the phone's - the phone's figure
	is kept beside the order as what the rep said out loud, and checked, never trusted.

	An item nobody has priced stops the whole cart. There is no safe number to put in its place:
	zero books it free and a guess is a guess, and either way the rep has already read a total
	to a shopkeeper. Throwing here is the only outcome that ends with somebody fixing the price.
	"""
	doc = readable_party(outlet, party_type)
	price_list = price_list or resolve_price_list(doc, field_user)
	company = resolve_company(field_user)
	channel = credit_service.billing_party(doc, field_user, party_type)
	party = channel["party"]

	wanted = {}
	for line in lines or []:
		code = line.get("item_code") or line.get("item")
		if not code:
			continue
		entry = wanted.setdefault(code, {"qty": 0.0, "uom": line.get("uom")})
		entry["qty"] = entry["qty"] + flt(line.get("qty"))

	details = {
		row["item_code"]: row
		for row in compat.get_item_details(
			list(wanted), price_list=price_list, company=company, customer=party
		)
	}

	cart_lines = []
	unpriceable = []
	over_mrp = []
	unknown = []
	unconvertible = []
	for code, entry in wanted.items():
		detail = details.get(code)
		if not detail:
			unknown.append(code)
			continue

		uom = entry["uom"] or detail["sales_uom"] or detail["stock_uom"]
		factor = 1.0 if uom == detail["stock_uom"] else flt(detail["uom_conversions"].get(uom))
		if not factor:
			unconvertible.append(f"{code} ({uom})")
			continue

		rate = detail["price_list_rate"]
		if rate is None:
			unpriceable.append(code)
			continue

		# Collected here because this is where the base-unit rate and the item's MRP are both in
		# hand. Named rather than thrown, like `unpriceable`, and not carried on the line below:
		# those lines are the scheme engine's input and ADR-021 keeps that to units and paise.
		if pricing.is_above_mrp(rate, detail["mrp"]):
			over_mrp.append(code)

		cart_lines.append({
			"item": code,
			# The engine counts whole base units, so a fractional case is rounded once, here,
			# rather than drifting through every slab comparison downstream.
			"qty": int(flt(entry["qty"]) * factor + 0.5),
			"rate_paise": to_paise(rate),
		})

	if unknown:
		frappe.throw(
			frappe._("These items are not on file any more: {0}. Refresh the catalogue and try "
			         "again.").format(", ".join(sorted(unknown)))
		)
	if unconvertible:
		# There is no way to say how much stock a unit nobody has defined means. Stopping is the
		# smaller failure: billing a case at a piece price looks entirely normal on the screen.
		frappe.throw(
			frappe._("These items have no pack size set for the unit the order is in: {0}. Book "
			         "them in the base unit, or ask your manager to set the conversion.")
			.format(", ".join(sorted(unconvertible)))
		)
	# Named, not thrown. A rep with forty lines and one unpriced SKU should see the other
	# thirty-nine price up and be told which one is the problem - throwing kills the whole cart
	# and leaves them nothing to sell. Committing is where it has to be refused, because silently
	# dropping a line from an order the rep believes they booked is worse than either.
	return {
		"outlet": doc.name,
		"price_list": price_list,
		"company": company,
		# The party as a name, which is what every caller has always read, and the whole answer
		# beside it. `channel` carries the kind of sale and whether this company makes that kind
		# at all - `order.create` refuses on it, and reading `.get()` off the bare string was a
		# crash waiting for the first order whose company was not already set.
		"billing_party": party,
		"channel": channel,
		"unpriced_items": sorted(unpriceable),
		"above_mrp_items": sorted(over_mrp),
		# The rate per item, not the tax. What is taxable depends on the cart's discount, which
		# the scheme engine has not run yet - so `scheme_compile.evaluate_for` does the
		# arithmetic once it has a discount to apportion.
		"tax_rates": tax_service.rates_for(
			[l["item"] for l in cart_lines],
			company=company,
			party=party,
			net_rates={code: details[code]["price_list_rate"] for code in details},
			item_groups={code: details[code]["item_group"] for code in details},
		),
		"lines": cart_lines,
	}


def to_paise(rupees) -> int:
	"""The one float in the money path, and it runs here on the server (ADR-022).

	`floor(rupees * 100 + 0.5)` exactly as the specification writes it, so that the number the
	compiler turns into paise and the number a cart line turns into paise are the same
	arithmetic. The evaluator on either side of the wire is handed paise and never calls this.
	"""
	return math.floor(flt(rupees) * 100 + 0.5)


# --------------------------------------------------------------------------------------
# masters, scope and the shop itself
# --------------------------------------------------------------------------------------


def readable_party(party, party_type: str | None = None, user: str | None = None):
	"""The party this order is for, shaped so that everything downstream can read it.

	A primary order is on a Customer; a retailer order is on a FieldMate Outlet. Rather than
	teaching `scope`, `pricing`, `matching_masters` and the catalogue readers about two kinds of
	party, a Customer is presented here in the shape they already understand - a name, a
	territory, a price list, and the two fields it genuinely does not have.

	**Blank channel and blank outlet class are the whole scoping rule.** `scope.applies_to_outlet`
	excludes a master that names a channel the party does not match, so a Customer matches only
	those catalogues that name no channel and no class - which reads exactly right: a catalogue
	scoped to General Trade is a shop catalogue, and a distributor is not a shop.

	`customer` is set to the party itself, so `channel.resolve` reads this as a sale we make
	rather than one the distributor makes, which is what a primary sale is.
	"""
	if (party_type or "Outlet") != "Customer":
		return readable_outlet(party, user)

	name = party if isinstance(party, str) else party.name
	row = frappe.db.get_value(
		"Customer", name,
		["name", "customer_name", "territory", "default_price_list", "disabled"], as_dict=True)
	if not row:
		raise frappe.DoesNotExistError(frappe._("That party no longer exists."))
	if row.disabled:
		frappe.throw(frappe._("{0} is disabled, so nothing can be ordered on them.")
		             .format(row.customer_name or name))

	return frappe._dict(
		doctype="Customer",
		name=row.name,
		outlet_name=row.customer_name or row.name,
		territory=row.territory,
		# Not "unset" but "does not exist for this kind of party" - see the scoping note above.
		channel=None,
		outlet_class=None,
		# What we bill them from. `pricing.price_list_for` reads this first, which is right: a
		# party's own list is the most specific thing anybody has said about what they pay.
		price_list=row.default_price_list,
		distributor=None,
		customer=row.name,
	)


def readable_outlet(outlet, user: str | None = None):
	"""The shop, but only if the signed-in login may see it.

	`frappe.get_doc` applies no user permission of its own, so a service that took a name and
	loaded it would let any device read any shop on the site by guessing a number out of a
	naming series. The permitted list is asked first, by the session user rather than by
	anything the caller passed, because permission is a property of who is signed in and not of
	an argument a caller is free to choose.
	"""
	user = user or frappe.session.user
	name = outlet if isinstance(outlet, str) else outlet.name

	if not frappe.db.exists("FieldMate Outlet", name):
		raise frappe.DoesNotExistError(frappe._("That shop no longer exists."))

	permitted = frappe.get_list(
		"FieldMate Outlet",
		filters={"name": name},
		fields=["name"],
		limit_page_length=1,
		ignore_permissions=False,
		user=user,
	)
	if not permitted:
		raise frappe.PermissionError(frappe._("This shop is not in your territory."))

	return frappe.get_cached_doc("FieldMate Outlet", name)


def matching_masters(doctype: str, outlet_doc, on) -> list:
	"""The live, in-scope masters of one kind for this shop, narrowest first.

	Read with `get_all` on purpose: these are company masters that every FieldMate role holds
	read on, and what decides whether one reaches this shop is not the reader's permissions but
	`services.scope` - the territory tree, the channel and the class, with blank meaning
	everywhere. The outlet itself was permission-checked on the way in.
	"""
	names = frappe.get_all(doctype, filters={"is_active": 1}, pluck="name")

	matched = []
	for name in names:
		doc = frappe.get_cached_doc(doctype, name)
		if not scope.is_effective_on(doc, on):
			continue
		if not scope.applies_to_outlet(doc, outlet_doc):
			continue
		matched.append(doc)

	matched.sort(key=lambda doc: (-specificity(doc), doc.name))
	return matched


def specificity(scoped) -> int:
	"""How narrowly a master was written, so the narrower one wins where two cover a shop.

	A national catalogue and a regional one both reaching the same shop is the ordinary case,
	not a mistake: the regional one is the exception somebody wrote on purpose, so it takes the
	line. A territory that is only the root counts for nothing here, for the reason
	`scope.narrows_territory` sets out - it is what Frappe fills in when nobody chose.
	"""
	return sum((
		1 if scope.narrows_territory(scoped.get("territory")) else 0,
		1 if scoped.get("channel") else 0,
		1 if scoped.get("outlet_class") else 0,
	))


def catalogue_rows(catalogues: list) -> dict:
	"""Every sellable item across the matching catalogues, mapped to its row and its catalogue.

	Unioned rather than picked from one list, because a shop is usually served by a national
	range plus whatever its region added. Where the same item is in both, the narrower
	catalogue's row wins - `matching_masters` has already put it first - so a region that made
	an item a focus SKU or raised its minimum order is the one that decides.
	"""
	rows = {}
	for catalogue in catalogues:
		for row in catalogue.items or []:
			if row.item_code and row.item_code not in rows:
				rows[row.item_code] = (row, catalogue.name)
	return rows


def must_sell_rows(lists: list) -> dict:
	"""The items this shop is expected to keep in stock, from the narrowest list naming each."""
	rows = {}
	for must_sell in lists:
		for row in must_sell.items or []:
			if row.item_code and row.item_code not in rows:
				rows[row.item_code] = row
	return rows


def resolve_price_list(outlet_doc, field_user: str | None = None) -> str | None:
	"""Which list this shop is quoted from.

	The chain itself is `pricing.price_list_for`, which is also what `channel.resolve` reads, so
	the catalogue, the cart and the channel answer cannot drift apart. The name is kept because
	it is what every caller in this module and the scheme compiler already say.
	"""
	return pricing.price_list_for(outlet_doc, field_user)


def resolve_company(field_user: str | None = None) -> str | None:
	"""Whose books the prices are read against. Same rule, and the same reason, as credit."""
	if field_user:
		company = frappe.db.get_value("FieldMate Field User", field_user, "company")
		if company:
			return company
	return settings_service.value("default_company")
