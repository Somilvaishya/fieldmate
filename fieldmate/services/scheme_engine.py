"""The scheme evaluator, in Python. Its twin is `frontend/src/scheme/engine.js`.

A rep standing in a market with no signal tells a shopkeeper what the offer comes to, and an hour
later the server re-runs the same cart to raise the invoice. If the two numbers differ by a single
paisa the shopkeeper stops believing the app, and no amount of correct accounting afterwards buys
that back. So this module and its JavaScript twin are written step for step from
`docs/SCHEME_SPEC.md`, with the same function names and the same `S4 -` step comments, so that a
reviewer can put the two files side by side and read one diff rather than two programs.

**Nothing here touches the world.** There is no `frappe` import, no database, no price list, no UOM
conversion, no clock and no settings lookup, and there must never be one. Every ambiguous decision -
which schemes are in scope today, what an item costs, how many pieces are in a case - has already
been made by the compiler on the server, which exists once and therefore cannot disagree with
itself. What arrives here is a flat compiled spec with no lookups left in it. That is what makes
parity provable rather than hoped for: both engines are handed byte-identical input, so any
difference between them is in these two hundred lines and nowhere else. It is also why this file
imports nothing outside the standard library and runs under a bare `python3` with no bench, no site
and no database behind it.

**Money is integer paise, and percentages are integer basis points.** Not because a double would
lose the value - at these magnitudes it would hold it fine - but because the two runtimes round
differently the moment a half lands on a boundary. Python's `round()` is banker's rounding,
`Math.round(-0.5)` is `-0` in JavaScript and `0` in Python, and Frappe's `flt()` is a third
behaviour again. A trade scheme is exactly the code where halves land on boundaries all day: 5% of
a 12345 paise line is 617.25 paise, and a gate that allows zero divergence across 60 carts will
find every one of them. Integer arithmetic removes the question instead of testing it, so 5%
arrives as `500`, quantities arrive as whole base units, and one primitive - `round_half_up_div` -
performs every division in the money path.

Rupees never appear here at all. The one float in the whole design,
`to_paise(rupees) = floor(rupees * 100 + 0.5)`, lives in the compiler on the server; the evaluator
is handed paise and never calls it.
"""

from __future__ import annotations

from functools import cmp_to_key

# Basis points in 100%. A percentage is carried as an integer count of these - 5% is 500, 12.5% is
# 1250 - so that no percentage is ever a fraction on its way through the money path.
PERCENT_DENOMINATOR = 10000

# The three kinds that come off the shop's bill. `Incentive` is deliberately not among them: it is
# money for the rep, and folding it into the discount overstates what the shopkeeper was actually
# given, which is the kind of number that turns into an argument at month-end claim settlement.
DISCOUNT_KINDS = ("Percent Discount", "Value Discount", "Rate Off")

# The multipliers a benefit may be granted on, and the ways a scheme may stack. A spec written by
# next month's compiler can carry a value neither of these holds, and section 5.1 is explicit about
# what an old phone does with it: nothing at all. A rep who quotes a discount the server then
# refuses has to take it back across a counter, where one who quotes less than the server grants
# hands over a pleasant surprise. So anything not named here is skipped rather than guessed at.
PER_MODES = ("Slab", "Unit", "Multiple")
STACKING_MODES = ("Exclusive", "Stackable", "Best Of Group")


# --------------------------------------------------------------------------------------
# primitives
# --------------------------------------------------------------------------------------


def round_half_up_div(n: int, d: int) -> int:
	"""floor((2n + d) / (2d)) - the only division in the money path, on integers only.

	A half always goes up, in both languages, with nothing left for them to disagree about.
	`2 * n + d` stays well under 2^53 for anything this app can hold - the largest realistic term
	is a paise amount times basis points, around 10^15 - so `//` here and `Math.floor` there are
	the same operation on the same integers rather than two roundings that usually match.
	"""
	return (2 * n + d) // (2 * d)


def as_int(value) -> int:
	"""Any number entering the engine, coerced to a whole one.

	JSON cannot tell 24 from 24.0. A spec that came off the wire carrying 24.0 would have Python
	answer 24.0 where JavaScript answers 24, which fails a parity run with no bug behind it.
	`int()` and `Math.trunc()` both truncate toward zero, so the two stay level. Something that is
	not a number at all becomes zero rather than an exception, because the alternative is one
	engine raising where the other carries on - a rep would see a crash on a spec the server
	priced happily, which is worse than a scheme quietly not firing.
	"""
	if not has_value(value):
		return 0
	try:
		return int(value)
	except (TypeError, ValueError):
		return 0


def has_value(value) -> bool:
	"""Whether an optional field was supplied at all.

	`to: null` is an open-topped slab and `budget_paise: null` is an uncapped scheme, so "missing"
	and "zero" are different answers here and truthiness cannot tell them apart.
	"""
	return value is not None


def as_text(value) -> str | None:
	"""A label on its way into the result, or None when the spec carried none.

	The guard is for JavaScript's sake: a missing key there reads as `undefined`, and
	`JSON.stringify` drops an `undefined` value out of the object altogether, where Python would
	have written `null` and kept the key. Both engines pass every label through this so a spec
	with a field missing produces the same result on both sides instead of two different shapes.
	"""
	if not has_value(value):
		return None
	return str(value)


def compare_number(a: int, b: int) -> int:
	"""Three-way compare, ascending."""
	if a < b:
		return -1
	if a > b:
		return 1
	return 0


def compare_text(a: str, b: str) -> int:
	"""Code-point order, spelled out rather than left to the language.

	Python would sort these correctly on its own; the comparator exists because JavaScript's
	`Array.prototype.sort` with no comparator sorts *stringified values lexicographically*, which
	puts 10 before 9, and because both engines have to be the same shape. Ids are ASCII
	naming-series strings, where UTF-16 code units and code points agree.
	"""
	if a < b:
		return -1
	if a > b:
		return 1
	return 0


def scheme_id(spec: dict) -> str:
	"""The naming-series id, which is the tie-breaker every ordering in here falls back to."""
	return str(spec.get("scheme") or "")


def compare_lines(a: dict, b: dict) -> int:
	"""S1's order: item code ascending."""
	return compare_text(a["item"], b["item"])


def compare_schemes(a: dict, b: dict) -> int:
	"""S3's order: priority ascending, then id ascending.

	Total, not merely stable. Two schemes at the same priority must resolve the same way on a
	phone and on the server, and leaning on sort stability would make that depend on the order the
	specs happened to arrive in.
	"""
	by_priority = compare_number(as_int(a.get("priority")), as_int(b.get("priority")))
	if by_priority:
		return by_priority
	return compare_text(scheme_id(a), scheme_id(b))


def compare_slabs(a: dict, b: dict) -> int:
	"""Slab order: floor ascending, then declared index.

	Slabs are validated non-overlapping at save time, so this only formalises the order they were
	written in - but it means neither engine depends on the array having arrived sorted.
	"""
	by_floor = compare_number(as_int(a.get("from")), as_int(b.get("from")))
	if by_floor:
		return by_floor
	return compare_number(as_int(a.get("idx")), as_int(b.get("idx")))


def compare_best_of_group(a: dict, b: dict) -> int:
	"""S8's order within a stack group: richest benefit first, then S3 order.

	Two schemes in one group are worth the identical rupee more often than it sounds - the same
	5% written twice for two brands that turn out to cost the same - and the winner then falls to
	S3, which is priority before id. A manager who moved one of them to priority 5 has said which
	they want to fire; breaking the tie on the id alone would hand it to whichever was created
	first and quietly ignore them.
	"""
	by_benefit = compare_number(b["benefit_paise"], a["benefit_paise"])
	if by_benefit:
		return by_benefit
	return compare_schemes(a["spec"], b["spec"])


def intersects(claimed: set, items: set) -> bool:
	"""Whether any of these items has already been claimed by an exclusive scheme."""
	for item in items:
		if item in claimed:
			return True
	return False


def free_goods_value(benefit: dict) -> int:
	"""What one free unit costs us, stamped on the benefit by the compiler from the valuation.

	`value_paise` and nothing else. An engine that also accepted a second spelling would price the
	same spec two ways the day a compiler emitted both, and the two engines would pick a different
	spelling first. A benefit that arrives without it is worth zero: the stock still ships, it
	simply charges no budget, which is the direction that under-promises.
	"""
	return as_int(benefit.get("value_paise"))


def benefit_multiplier(per: str, measure: int, slab_from: int) -> int:
	"""How often a benefit is granted: once, once per qualifying unit, or once per slab crossed.

	"Buy 10 get 1 free" has to fire again at 20 without a manager writing a second slab, which is
	what `Multiple` counts. A slab starting at zero has no interval to repeat over, so it grants
	once rather than dividing by nothing.
	"""
	if per == "Unit":
		return measure
	if per == "Multiple":
		if slab_from <= 0:
			return 1
		return measure // slab_from
	return 1


# --------------------------------------------------------------------------------------
# the algorithm, S1 to S10
# --------------------------------------------------------------------------------------


def s1_normalise(cart: dict) -> list[dict]:
	"""S1 - normalise the cart.

	A rep adds the same SKU twice all the time: once at the top of the order and again when the
	shopkeeper remembers the back room. Merging those, dropping anything at or below zero and
	sorting by item is what makes every step after this order-independent - two phones that built
	the same cart by different routes have to produce the same bytes.
	"""
	merged: dict[str, dict] = {}

	for position, raw in enumerate(cart.get("lines") or []):
		item = raw.get("item")
		if not item:
			continue
		rank = as_int(raw.get("idx")) if has_value(raw.get("idx")) else position
		line = merged.get(item)
		if line is None:
			merged[item] = {
				"item": item,
				"qty": as_int(raw.get("qty")),
				"rate_paise": as_int(raw.get("rate_paise")),
				"rank": rank,
			}
			continue
		line["qty"] = line["qty"] + as_int(raw.get("qty"))
		# Both halves of a duplicated SKU carry the same rate, because the compiler resolved one
		# rate per item from the price list before the cart was ever built. Should they somehow
		# differ, the earliest line by its own idx wins - never the one that happened to sit
		# earlier in the array, which is the thing two phones can disagree about.
		if rank < line["rank"]:
			line["rate_paise"] = as_int(raw.get("rate_paise"))
			line["rank"] = rank

	kept = [line for line in merged.values() if line["qty"] > 0]
	kept.sort(key=cmp_to_key(compare_lines))

	return [
		{"idx": position + 1, "item": line["item"], "qty": line["qty"], "rate_paise": line["rate_paise"]}
		for position, line in enumerate(kept)
	]


def s2_line_gross(lines: list[dict]) -> dict:
	"""S2 - line gross.

	`qty * rate_paise` is an exact integer product and the cart total is a sum of them, so nothing
	can drift here even in principle.
	"""
	priced = [{**line, "gross_paise": line["qty"] * line["rate_paise"]} for line in lines]
	cart_gross_paise = 0
	for line in priced:
		cart_gross_paise = cart_gross_paise + line["gross_paise"]
	return {"lines": priced, "cart_gross_paise": cart_gross_paise}


def s3_order_schemes(specs: list[dict]) -> list[dict]:
	"""S3 - order the schemes.

	Priority first, then the naming-series id, which is ASCII and therefore sorts identically in
	both runtimes. Never by name: names are typed by managers, hold non-ASCII the moment someone
	writes a rupee sign or a Hindi word, and that is where UTF-16 and code-point order part ways.
	"""
	return sorted(specs, key=cmp_to_key(compare_schemes))


def s4_measure(spec: dict, lines: list[dict]) -> dict:
	"""S4 - measure each scheme.

	The qualifying gross is kept apart from the cart gross because a percentage comes off the
	qualifying lines and nothing else. A 5% soap scheme must not discount the tea.
	"""
	# An Order scheme means the whole cart and reads nothing else - not the item list, not its
	# length. The compiler is required to emit an empty list beside Order, so a spec carrying both
	# is malformed; a malformed spec still has to come to the same rupee on the phone and on the
	# server, and reading the list as a filter instead is a second, undocumented answer.
	wanted = set(spec.get("qualifying_items") or [])
	whole_cart = spec.get("measured_over") == "Order"

	qualifying = [line for line in lines if whole_cart or line["item"] in wanted]

	qualifying_gross_paise = 0
	qualifying_qty = 0
	for line in qualifying:
		qualifying_gross_paise = qualifying_gross_paise + line["gross_paise"]
		qualifying_qty = qualifying_qty + line["qty"]

	measure = qualifying_gross_paise if spec.get("basis") == "Value" else qualifying_qty

	return {
		"qualifying": qualifying,
		"qualifying_gross_paise": qualifying_gross_paise,
		"measure": measure,
		# Nothing in the cart qualifies, so the scheme cannot apply - but it is still measured at
		# zero, because S10 has to tell the rep what they are one SKU away from.
		"applicable": len(qualifying) > 0,
	}


def s5_pick_slab(spec: dict, measure: int) -> dict | None:
	"""S5 - pick the slab.

	The highest slab whose floor the measure has reached and whose ceiling it has not passed.
	Slabs are validated non-overlapping at save time, so at most one can match and "highest" is a
	safety net rather than a policy - but it is a net both engines have to hold at the same height.
	"""
	chosen = None
	for slab in spec.get("slabs") or []:
		if measure < as_int(slab.get("from")):
			continue
		ceiling = slab.get("to")
		if has_value(ceiling) and measure > as_int(ceiling):
			continue
		if chosen is None or compare_slabs(chosen, slab) < 0:
			chosen = slab
	return chosen


def s6_benefits(spec: dict, slab: dict, measure: int, qualifying_gross_paise: int) -> dict:
	"""S6 - compute benefits.

	In the order the manager wrote them, and every entry carries all six keys whether or not its
	kind has anything to put in them - a result whose shape changes with its contents cannot be
	compared field by field against the other engine's, which is the whole of Gate 4. The rounding
	happens once, on the percentage, before the multiplier is applied: rounding afterwards would
	turn a half-paise into a whole one every time a scheme fired more than once, and the rep would
	quote a figure the invoice never reaches.
	"""
	benefits = []
	free_goods = []
	benefit_paise = 0
	cost_paise = 0

	for raw in slab.get("benefits") or []:
		kind = as_text(raw.get("kind"))
		per = as_text(raw.get("per"))

		if per not in PER_MODES:
			continue
		if per == "Unit" and spec.get("basis") == "Value":
			# On a value basis the measure is already paise, so "50 paise per unit" against a
			# 250-rupee cart would multiply out to 12,500 rupees off. The compiler refuses the
			# combination; an evaluator handed one anyway leaves the benefit alone rather than
			# paying out a number nobody intended.
			continue

		multiplier = benefit_multiplier(per, measure, as_int(slab.get("from")))
		amount_paise = 0
		item = None
		qty = 0

		if kind == "Free Goods":
			# Free goods bill at zero and leave as their own lines. They never re-enter any basis:
			# a free case that helped the cart cross the next slab would have the scheme funding
			# its own escalation. The amount is what the granted stock costs us, which is both
			# what the shop is receiving and what the budget is paying for.
			item = as_text(raw.get("item"))
			qty = as_int(raw.get("qty")) * multiplier
			amount_paise = qty * free_goods_value(raw)
			free_goods.append({
				"item": item,
				"qty": qty,
				"scheme": scheme_id(spec),
				"value_paise": amount_paise,
			})
		elif kind == "Percent Discount":
			amount_paise = round_half_up_div(
				qualifying_gross_paise * as_int(raw.get("pct_bp")), PERCENT_DENOMINATOR
			) * multiplier
		elif kind == "Value Discount" or kind == "Rate Off":
			amount_paise = as_int(raw.get("amount_paise")) * multiplier
		elif kind == "Incentive":
			# The rep's money. It never reaches net_paise and is no part of what the shop
			# receives, because the shopkeeper was never given it - but a budget is a cap on what
			# the scheme pays out, and this leaves the same pocket the discount does.
			amount_paise = as_int(raw.get("amount_paise")) * multiplier
		else:
			# A kind this engine does not know is left out of every total rather than guessed at.
			# A spec from a newer compiler must under-promise on an old phone, never over-promise.
			continue

		benefits.append({
			"kind": kind,
			"per": per,
			"multiplier": multiplier,
			"amount_paise": amount_paise,
			"item": item,
			"qty": qty,
		})
		cost_paise = cost_paise + amount_paise
		if kind != "Incentive":
			benefit_paise = benefit_paise + amount_paise

	return {
		"benefits": benefits,
		"free_goods": free_goods,
		# What the shop receives: the bill reduction plus the value of the free stock. It is the
		# "Benefit Value" the rep reads out at the counter and the figure a stack group is ranked
		# on, so the rep's own incentive is left out of it.
		"benefit_paise": benefit_paise,
		# What the budget is charged, deliberately the wider figure: every paisa the scheme pays
		# out, incentive included.
		"cost_paise": cost_paise,
	}


def s7_budget(spec: dict, cost_paise: int) -> dict:
	"""S7 - budget.

	A scheme that cannot be afforded in full is dropped in full. Paying part of it would leave a
	discount on the invoice reconciling against nothing in the scheme ledger, and somebody in
	accounts would spend a week on it. `Warn` is the configured exception: the scheme still
	applies, and the result says out loud that its pot is empty.
	"""
	budget_paise = spec.get("budget_paise")
	if not has_value(budget_paise):
		return {"drop": False, "warning": False}

	remaining = as_int(budget_paise) - as_int(spec.get("consumed_paise"))
	if cost_paise <= remaining:
		return {"drop": False, "warning": False}
	if spec.get("on_exhaust") == "Warn":
		return {"drop": False, "warning": True}
	return {"drop": True, "warning": False}


def s8_stacking(candidates: list[dict]) -> dict:
	"""S8 - stacking.

	Walked in S3 order holding the set of items already claimed, so an earlier `Exclusive` beats a
	later one: priority is how a manager expresses intent, and the engine honours that rather than
	re-deciding it. Only `Exclusive` claims anything. `Stackable` claims nothing and excludes
	nothing - it applies alongside whatever else survived - but an earlier `Exclusive` can still
	take it away, because that one did the claiming.
	"""
	claimed: set = set()
	survivors = []
	dropped = []

	for candidate in candidates:
		spec = candidate["spec"]
		if intersects(claimed, candidate["items"]):
			dropped.append({"scheme": scheme_id(spec), "reason": "EXCLUSIVE_OVERLAP"})
			continue
		if spec.get("stacking") == "Exclusive":
			claimed.update(candidate["items"])
		survivors.append(candidate)

	# Within one stack group only the richest survives, a tie going to whichever comes first in S3
	# order so that the manager's priority decides it and every device decides it alike. This map
	# is only ever asked about a key it was given and never iterated, so its key order cannot
	# reach the result.
	best: dict[str, dict] = {}
	for candidate in survivors:
		spec = candidate["spec"]
		if spec.get("stacking") != "Best Of Group":
			continue
		group = str(spec.get("stack_group") or "")
		held = best.get(group)
		if held is None or compare_best_of_group(candidate, held) < 0:
			best[group] = candidate

	kept = []
	for candidate in survivors:
		spec = candidate["spec"]
		if spec.get("stacking") == "Best Of Group":
			group = str(spec.get("stack_group") or "")
			if best.get(group) is not candidate:
				dropped.append({"scheme": scheme_id(spec), "reason": "BEST_OF_GROUP"})
				continue
		kept.append(candidate)

	return {"kept": kept, "dropped": dropped}


def s9_total(cart_gross_paise: int, applied: list[dict]) -> dict:
	"""S9 - total.

	Incentive is summed alongside the discount and then left out of the net, which is the whole
	point of counting it apart: it is the rep's earning, not the shop's reduction. A cart that
	tries to go negative is a scheme somebody mis-configured, so it floors at zero and says so
	rather than quietly handing back a credit nobody authorised.
	"""
	discount_paise = 0
	incentive_paise = 0
	errors = []

	for entry in applied:
		for benefit in entry["benefits"]:
			if benefit["kind"] == "Incentive":
				incentive_paise = incentive_paise + benefit["amount_paise"]
			elif benefit["kind"] in DISCOUNT_KINDS:
				discount_paise = discount_paise + benefit["amount_paise"]

	net_paise = cart_gross_paise - discount_paise
	if net_paise < 0:
		errors.append("NEGATIVE_NET")
		net_paise = 0

	return {
		"discount_paise": discount_paise,
		"net_paise": net_paise,
		"incentive_paise": incentive_paise,
		"errors": errors,
	}


def s10_near_misses(measured: list[dict]) -> list[dict]:
	"""S10 - near misses.

	The nudge that turns a 9-case order into a 10-case one: "add 1 more case to unlock Tier 3".
	Always the lowest slab still above the measure, so the gap is a number of units the rep can
	actually add to the cart and is never zero or less. Where nothing sits above the measure -
	the top slab is already matched, or a closed top has nothing beyond it - there is no nudge to
	give and the scheme is left out entirely, because "order 380 fewer units" is worse than
	silence. Advisory always: nothing here may alter a total.
	"""
	near_misses = []

	for entry in measured:
		spec = entry["spec"]
		measure = entry["measure"]

		nxt = None
		for slab in spec.get("slabs") or []:
			if as_int(slab.get("from")) <= measure:
				continue
			if nxt is None or compare_slabs(slab, nxt) < 0:
				nxt = slab
		if nxt is None:
			continue

		near_misses.append({
			"scheme": scheme_id(spec),
			"scheme_name": as_text(spec.get("scheme_name")),
			"slab_idx": as_int(nxt.get("idx")),
			"basis": as_text(spec.get("basis")),
			"measure": measure,
			"gap": as_int(nxt.get("from")) - measure,
		})

	return near_misses


# --------------------------------------------------------------------------------------
# evaluate
# --------------------------------------------------------------------------------------


def evaluate(cart: dict, specs: list[dict]) -> dict:
	"""Run a cart against a set of compiled specs and return what the shopkeeper gets.

	Two money figures come out of every applied scheme and they are deliberately not the same
	number. `benefit_paise` is what the shop receives - the bill reduction plus the value of the
	free stock - and it is what the rep reads out and what a stack group is ranked on. The budget
	in S7 is charged the wider figure, incentive included, because the cap a manager set is on
	what the scheme pays out and the rep's money leaves the same decision. Collapsing the two
	would either promise the shopkeeper the rep's incentive or let a scheme spend past its cap.
	"""
	normalised = s1_normalise(cart or {})
	priced = s2_line_gross(normalised)
	lines = priced["lines"]
	cart_gross_paise = priced["cart_gross_paise"]

	ordered = s3_order_schemes(specs or [])

	measured = []
	candidates = []
	# Keyed by scheme so the output order is S3's rather than the order the drops happened to
	# occur in, which changes as soon as a budget or a stack group changes.
	dropped: dict[str, str] = {}

	for spec in ordered:
		# A stacking mode this build has never heard of is left out of everything - not applied,
		# not dropped, not even hinted at in the near misses. The engine cannot know whether it
		# would have combined with the others or excluded them, so nudging a rep toward it is a
		# promise there is no way to keep.
		if spec.get("stacking") not in STACKING_MODES:
			continue

		reading = s4_measure(spec, lines)
		slab = s5_pick_slab(spec, reading["measure"]) if reading["applicable"] else None
		measured.append({"spec": spec, "measure": reading["measure"]})
		if slab is None:
			continue

		computed = s6_benefits(spec, slab, reading["measure"], reading["qualifying_gross_paise"])

		verdict = s7_budget(spec, computed["cost_paise"])
		if verdict["drop"]:
			dropped[scheme_id(spec)] = "BUDGET_EXHAUSTED"
			continue

		candidates.append({
			"spec": spec,
			"slab": slab,
			"measure": reading["measure"],
			"items": {line["item"] for line in reading["qualifying"]},
			"benefits": computed["benefits"],
			"free_goods": computed["free_goods"],
			"benefit_paise": computed["benefit_paise"],
			"budget_warning": verdict["warning"],
		})

	stacked = s8_stacking(candidates)
	for entry in stacked["dropped"]:
		dropped[entry["scheme"]] = entry["reason"]

	applied = []
	free_goods = []
	for candidate in stacked["kept"]:
		applied.append({
			"scheme": scheme_id(candidate["spec"]),
			"scheme_name": as_text(candidate["spec"].get("scheme_name")),
			"slab_idx": as_int(candidate["slab"].get("idx")),
			"measure": candidate["measure"],
			"benefits": candidate["benefits"],
			"benefit_paise": candidate["benefit_paise"],
			"budget_warning": candidate["budget_warning"],
		})
		for free_line in candidate["free_goods"]:
			free_goods.append(free_line)

	totals = s9_total(cart_gross_paise, applied)

	return {
		"cart_gross_paise": cart_gross_paise,
		"discount_paise": totals["discount_paise"],
		"net_paise": totals["net_paise"],
		"incentive_paise": totals["incentive_paise"],
		"applied": applied,
		"free_goods": free_goods,
		# A scheme that was taken away gets no nudge. Telling a rep they are twenty units from a
		# benefit that has already been dropped for budget or beaten by an exclusive is a lie the
		# app would be telling on our behalf, and they would find out at the counter.
		"near_misses": s10_near_misses(
			[entry for entry in measured if scheme_id(entry["spec"]) not in dropped]
		),
		"dropped": [
			{
				"scheme": scheme_id(spec),
				"scheme_name": as_text(spec.get("scheme_name")),
				"reason": dropped[scheme_id(spec)],
			}
			for spec in ordered
			if scheme_id(spec) in dropped
		],
		"errors": totals["errors"],
	}
