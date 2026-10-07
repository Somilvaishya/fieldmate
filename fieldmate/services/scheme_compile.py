"""Turning a scheme as a manager wrote it into a spec an engine can run.

`docs/SCHEME_SPEC.md` splits the scheme path in two, and this is the half that exists once. A
manager writes rupees, cases, item groups and territories. The evaluator - `scheme_engine.py` and
its JavaScript twin - reads none of those: it is a pure function over a flat compiled spec with
no lookups left in it, no clock, no price list and no database (ADR-021). Everything ambiguous is
decided here instead, on the server, in one place, which is what makes the duplicated evaluator
auditable rather than a second implementation.

So this module resolves the scope against the shop, expands item groups and brands to item codes,
turns cases into base units and rupees into integer paise (ADR-022), and emits the spec the phone
caches. It also runs the specs, because the compiled spec is the only thing worth running and the
server's answer is the figure of record - the phone's number is what the rep said out loud, and
the two agreeing is something to be checked rather than trusted.

**A scheme this module cannot compile without guessing is dropped, with a reason.** A half-read
scheme would quote one number at the counter and print another on the invoice, which is exactly
the divergence a rep never recovers from once a shopkeeper has caught it. Every drop is reported
back so somebody can fix the master rather than wonder why an offer stopped firing.
"""

from __future__ import annotations

import math

import frappe
from frappe.utils import cint, flt, getdate, today

from fieldmate import compat
from fieldmate.services import catalogue as catalogue_service
from fieldmate.services import scheme_engine
from fieldmate.services import tax as tax_service
from fieldmate.services.scheme_engine import round_half_up_div

# Why a scheme did not make it into the payload. Stable strings, because the distributor portal
# and the Desk report both branch on them rather than on a sentence.
AMBIGUOUS_CASE_SIZE = "AMBIGUOUS_CASE_SIZE"
NO_QUALIFYING_ITEMS = "NO_QUALIFYING_ITEMS"
NO_SLABS = "NO_SLABS"
UNIT_BENEFIT_ON_VALUE_BASIS = "UNIT_BENEFIT_ON_VALUE_BASIS"
COLLAPSED_SLABS = "COLLAPSED_SLABS"


# --------------------------------------------------------------------------------------
# what applies here
# --------------------------------------------------------------------------------------


def for_outlet(outlet, field_user: str | None = None, on_date=None, price_list: str | None = None,
               party_type: str | None = None, kind: str | None = None) -> dict:
	"""Every live scheme that reaches this party today, compiled.

	This is what the phone caches and evaluates against offline. A scheme edited in Desk does not
	reach a rep until the next pull, which is correct - the rep quoted what they were holding -
	but it means the payload has to say when it was compiled, so the app can show its own age
	rather than imply it is current.

	`kind` is the kind of sale, from `channel.resolve`, and a scheme has to be written for it.
	Not the party type: a shop the company invoices direct is an Outlet and a primary sale.
	"""
	doc = catalogue_service.readable_party(outlet, party_type)
	on = getdate(on_date or today())
	price_list = price_list or catalogue_service.resolve_price_list(doc, field_user)
	company = catalogue_service.resolve_company(field_user)

	live = []
	for name in frappe.get_all(
		"FieldMate Scheme", filters={"is_active": 1, "docstatus": 1}, pluck="name"
	):
		scheme = frappe.get_cached_doc("FieldMate Scheme", name)
		if not scheme.is_live_on(on):
			continue
		if not scheme.covers_sale(kind):
			continue
		if not scheme.covers_outlet(doc):
			continue
		live.append(scheme)

	# Free goods are valued for the budget out of the same price list the cart is priced from,
	# and every free item across every scheme is fetched in one call. A scheme with a free-goods
	# tier per slab would otherwise be a read per tier per scheme per shop.
	free_items = sorted({
		row.free_item for scheme in live for row in scheme.slabs or [] if row.free_item
	})
	free_details = {
		row["item_code"]: row
		for row in compat.get_item_details(free_items, price_list=price_list, company=company)
	}

	specs = []
	skipped = []
	for scheme in live:
		spec, reason = compile_scheme(scheme, free_details)
		if spec:
			specs.append(spec)
		else:
			skipped.append({"scheme": scheme.name, "scheme_name": scheme.scheme_name,
			                "reason": reason})

	specs.sort(key=lambda spec: (spec["priority"], spec["scheme"]))

	return {
		"outlet": doc.name,
		"as_of": str(on),
		"price_list": price_list,
		"compiled_on": str(frappe.utils.now_datetime()),
		"specs": specs,
		"skipped": skipped,
	}


# --------------------------------------------------------------------------------------
# the compiler
# --------------------------------------------------------------------------------------


def compile_scheme(scheme, free_details: dict) -> tuple[dict | None, str | None]:
	"""One scheme as the engine will read it, or nothing and the reason why."""
	qualifying = qualifying_items(scheme)
	if not qualifying and scheme.measured_over != "Order":
		# A scheme measuring an item set that expands to no item at all cannot fire, and a spec
		# that cannot fire is worse than an absent one: it shows up in the app as an offer.
		return None, NO_QUALIFYING_ITEMS

	factor, ambiguous = case_factor(scheme)
	if ambiguous:
		return None, AMBIGUOUS_CASE_SIZE

	slabs, reason = compile_slabs(scheme, factor, free_details)
	if reason:
		return None, reason
	if not slabs:
		return None, NO_SLABS

	return {
		"scheme": scheme.name,
		"scheme_name": scheme.scheme_name,
		"priority": cint(scheme.priority),
		"stacking": scheme.stacking,
		"stack_group": scheme.stack_group or None,

		"basis": scheme.basis,
		"measured_over": scheme.measured_over,
		"qualifying_items": qualifying,

		"slabs": slabs,

		# A Currency column is NOT NULL DEFAULT 0, so a budget of zero is one nobody typed
		# rather than a pot with nothing in it. Reading it as a ceiling would switch off every
		# scheme on the site the day it was written; a manager switches a scheme off by
		# clearing Active, which is a decision somebody can see.
		"budget_paise": to_paise(scheme.budget_amount) if flt(scheme.budget_amount) else None,
		"consumed_paise": to_paise(scheme.consumed_amount),
		"on_exhaust": scheme.on_exhaust,

		# Everything below is carried for the app rather than for the engine, which reads only
		# the keys above. The evaluator ignores what it does not know, on both sides of the
		# wire, so this stays additive.
		"spec_version": cint(scheme.spec_version),
		"currency": scheme.currency,
		# What one case held when this was compiled. The engine never reads it - its slabs are
		# already in base units - but the app needs it to say "2 cases" where the spec says 24,
		# and a support call about a wrong slab is unanswerable without it.
		"base_units_per_case": factor,
		"rep_pitch": scheme.rep_pitch or None,
		# So a phone that has not synced for three days can retire an offer itself instead of
		# quoting one that ended on Sunday. Advisory: the engine never reads a clock.
		"valid_from": str(scheme.valid_from) if scheme.valid_from else None,
		"valid_to": str(scheme.valid_to) if scheme.valid_to else None,
	}, None


def qualifying_items(scheme) -> list[str]:
	"""The base item codes a cart qualifies on, with groups and brands already expanded.

	Sorted, because the spec travels to a phone and comes back into a parity run, and two
	orderings of the same list are two different bytes for no reason.
	"""
	codes: set[str] = set()
	groups = []
	brands = []
	for row in scheme.items or []:
		if row.item_code:
			codes.add(row.item_code)
		elif row.item_group:
			groups.append(row.item_group)
		elif row.brand:
			brands.append(row.brand)

	if groups:
		codes.update(items_in_groups(groups))
	if brands:
		codes.update(frappe.get_all(
			"Item", filters={"brand": ["in", brands], "disabled": 0}, pluck="name"
		))
	return sorted(codes)


def items_in_groups(groups: list[str]) -> list[str]:
	"""Every sellable item in these groups and everything beneath them.

	Item Group is a tree for the same reason Territory is, and a manager writing "Detergents"
	means the whole branch. Matching the name alone would expand to the handful of items pinned
	to that exact node, which is usually none of them.
	"""
	bounds = frappe.get_all(
		"Item Group", filters={"name": ["in", groups]}, fields=["lft", "rgt"]
	)
	if not bounds:
		return []

	wanted = set()
	for bound in bounds:
		wanted.update(frappe.get_all(
			"Item Group",
			filters={"lft": [">=", bound.lft], "rgt": ["<=", bound.rgt]},
			pluck="name",
		))
	if not wanted:
		return []

	return frappe.get_all(
		"Item", filters={"item_group": ["in", sorted(wanted)], "disabled": 0}, pluck="name"
	)


def case_factor(scheme) -> tuple[int, bool]:
	"""How many base units one slab unit is, and whether the scheme says so unambiguously.

	A slab typed as "2 cases" has to reach the engine as a count of base units, because the
	engine never divides by a conversion factor - it is handed numbers that already agree. Which
	means the whole scheme has to have one case size: a volume slab measured in cases over a
	soap in twelves and a shampoo in twenty-fours has no single meaning at all, and picking one
	of the two would silently under-reward half the range. Better to drop it and say so.
	"""
	if scheme.basis != "Qty" or scheme.basis_uom != "Case":
		return 1, False

	factors = {cint(row.conversion_factor) for row in scheme.items or []
	           if cint(row.conversion_factor) > 0}
	if len(factors) > 1:
		return 1, True
	if not factors:
		# Cases asked for and no pack size given anywhere. One case is one unit is the only
		# reading left, and it is the reading that under-rewards rather than over-rewards.
		return 1, False
	return factors.pop(), False


def compile_slabs(scheme, factor: int, free_details: dict) -> tuple[list[dict], str | None]:
	"""The slab table flattened into bands, each carrying every benefit written against it.

	Rows sharing a slab number are one slab granting a combo - the DocType already refuses rows
	that share a number while covering different ranges, so the band can be taken from the first
	row of each group.
	"""
	bands: dict[int, dict] = {}
	for row in scheme.slabs or []:
		number = cint(row.slab_idx)
		band = bands.get(number)
		if band is None:
			band = bands[number] = {
				"idx": number,
				"from": measure_value(scheme, row.from_value, factor),
				"to": None if cint(row.is_open_ended) else measure_value(scheme, row.to_value, factor),
				"benefits": [],
			}

		benefit, reason = compile_benefit(scheme, row, factor, free_details)
		if reason:
			return [], reason
		if benefit:
			band["benefits"].append(benefit)

	ordered = [bands[number] for number in sorted(bands)]
	return (ordered, None) if slabs_hold_apart(ordered) else ([], COLLAPSED_SLABS)


def slabs_hold_apart(bands: list[dict]) -> bool:
	"""Do the bands still sit apart once the case size has been multiplied through?

	The DocType refuses overlapping slabs as the manager typed them, but it checked cases and
	these are base units: 1 to 1.55 cases and 1.6 cases upward are clearly separate bands until
	a pack of ten turns them into 10-to-16 and 16-upward, and then a cart of sixteen matches
	both. SCHEME_SPEC.md S5 lets the engine take the highest match as a safety net, not as a
	policy, so the ambiguity has to die here - a malformed spec on a phone cannot be fixed from
	the server, and the rep would quote whichever answer their build happened to pick.
	"""
	previous = None
	for band in bands:
		if band["to"] is not None and band["from"] > band["to"]:
			return False
		if previous is not None:
			# Only the highest band may be open-topped; an open band with anything above it
			# swallows every slab after it.
			if previous["to"] is None or band["from"] <= previous["to"]:
				return False
		previous = band
	return True


def measure_value(scheme, value, factor: int) -> int:
	"""A slab edge in the units the engine measures in: base units, or paise."""
	if scheme.basis == "Value":
		return to_paise(value)
	return int(flt(value) * factor + 0.5)


def compile_benefit(scheme, row, factor: int, free_details: dict) -> tuple[dict | None, str | None]:
	"""One benefit row, with the rupees and the cases already taken out of it."""
	per = row.per

	if per == "Unit" and scheme.basis == "Value":
		# A per-unit benefit multiplies by the measure, and on a value basis the measure is a
		# count of paise. Fifty rupees times eight hundred thousand is not an offer anybody
		# wrote; it is a row that was never going to mean what it reads as.
		return None, UNIT_BENEFIT_ON_VALUE_BASIS

	benefit = {"kind": row.benefit_kind, "per": per, "note": row.benefit_note or None}

	if row.benefit_kind == "Free Goods":
		detail = free_details.get(row.free_item) or {}
		free_factor = uom_factor(detail, row.free_uom)
		benefit["item"] = row.free_item
		benefit["qty"] = int(flt(row.free_qty) * free_factor + 0.5)
		rate = detail.get("price_list_rate")
		if rate is not None:
			# What a free unit costs the budget. Supplied only when the price list actually
			# holds a rate: the engine charges nothing when the compiler supplied none, which
			# is the honest answer when nobody has priced the giveaway.
			benefit["value_paise"] = to_paise(rate)
		return benefit, None

	if row.benefit_kind == "Percent Discount":
		benefit["pct_bp"] = to_bp(row.discount_pct)
		return benefit, None

	amount = {
		"Value Discount": row.discount_amount,
		"Rate Off": row.rate_off,
		"Incentive": row.incentive_amount,
	}.get(row.benefit_kind)
	if amount is None:
		return None, None

	benefit["amount_paise"] = per_unit_paise(scheme, amount, per, factor)
	return benefit, None


def per_unit_paise(scheme, amount, per: str, factor: int) -> int:
	"""An amount restated in the unit the engine will multiply it by.

	"₹50 per case" and "₹50 per piece" are the same three characters in the form and different
	offers by a factor of twelve. The engine's `Unit` multiplier counts base units, so a figure
	a manager typed against cases is divided down here, in the compiler, using the engine's own
	rounding primitive - dividing it on the phone instead would be one more place for the two
	runtimes to disagree about a half paisa.
	"""
	paise = to_paise(amount)
	if per != "Unit" or factor <= 1:
		return paise
	return round_half_up_div(paise, factor)


def uom_factor(detail: dict, uom: str | None) -> float:
	"""How many base units one of this UOM is. Unknown units read as the base unit.

	A free quantity is a giveaway rather than a charge, so an unknown pack size here costs the
	shopkeeper nothing and the company a smaller gift than intended. That is the direction to
	fail in; the opposite would have a rep handing over a case where a piece was meant.
	"""
	if not uom or uom == detail.get("stock_uom"):
		return 1.0
	return flt((detail.get("uom_conversions") or {}).get(uom)) or 1.0


def to_paise(rupees) -> int:
	"""ADR-022's single float boundary, and it runs here rather than in either evaluator."""
	return math.floor(flt(rupees) * 100 + 0.5)


def to_bp(percent) -> int:
	"""A percentage as an integer count of basis points: 5% is 500, 12.5% is 1250."""
	return math.floor(flt(percent) * 100 + 0.5)


# --------------------------------------------------------------------------------------
# the figure of record
# --------------------------------------------------------------------------------------


def evaluate_for(outlet, field_user: str | None, lines, party_type: str | None = None) -> dict:
	"""What this cart actually comes to, computed on the server against server prices.

	The phone works the same schemes out at the counter because the rep has to say a number out
	loud before there is any signal to ask with, and `docs/SCHEME_SPEC.md` allows the two no
	divergence at all. This is the one of the two that the business acts on.

	Rupee mirrors of every total are added beside the paise. Everything downstream of here -
	the order document, Desk, the reports a manager reads - works in rupees, and converting in
	four places is how three of them end up rounding differently.
	"""
	cart = catalogue_service.cart_for(outlet, lines, field_user, party_type=party_type)
	# Schemes for the kind of sale this is. Step 5c compiled none at all for a primary order,
	# because a scheme scoped to everywhere would have fired on one silently; `applies_to` is
	# what makes it safe to compile them now.
	# The kind comes from `channel.resolve`, not from the party type: a shop the company invoices
	# direct is an Outlet and a *primary* sale, and reading the type would put a retailer scheme
	# on it.
	compiled = for_outlet(cart["outlet"], field_user, price_list=cart["price_list"],
	                      party_type=party_type,
	                      kind=(cart.get("channel") or {}).get("kind"))

	result = scheme_engine.evaluate({"outlet": cart["outlet"], "lines": cart["lines"]},
	                                compiled["specs"])

	result["outlet"] = cart["outlet"]
	result["price_list"] = cart["price_list"]
	result["billing_party"] = cart["billing_party"]
	result["channel"] = cart.get("channel") or {}
	result["lines"] = cart["lines"]
	result["skipped_schemes"] = compiled["skipped"]
	# Carried through rather than swallowed: the screen has to name the SKU whose price
	# is missing, and the order service has to refuse to commit one. Same for a SKU priced above
	# its MRP, which is a price nobody may legally sell at.
	result["unpriced_items"] = cart.get("unpriced_items") or []
	result["above_mrp_items"] = cart.get("above_mrp_items") or []

	# Tax last, because what is taxable is the net and the net is what the engine just decided.
	# This is the distributor's tax on the distributor's sale and FieldMate posts none of it -
	# see `services/tax`. It is here so the rep quotes the figure the shop will actually be
	# billed rather than one short by the whole of the GST.
	taxed = tax_service.for_lines(
		result["lines"], cart.get("tax_rates") or {}, discount_paise=result["discount_paise"])
	result["tax_paise"] = taxed["tax_paise"]
	result["tax_lines"] = taxed["lines"]
	result["grand_paise"] = result["net_paise"] + taxed["tax_paise"]

	result["totals"] = {
		"gross": in_rupees(result["cart_gross_paise"]),
		"discount": in_rupees(result["discount_paise"]),
		"net": in_rupees(result["net_paise"]),
		"incentive": in_rupees(result["incentive_paise"]),
		"tax": in_rupees(result["tax_paise"]),
		"grand": in_rupees(result["grand_paise"]),
	}
	return result


def in_rupees(paise: int) -> float:
	"""Paise back to the rupees Desk and every report downstream work in."""
	return flt(cint(paise) / 100.0, 2)

