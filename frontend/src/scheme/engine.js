/**
 * The scheme evaluator, in JavaScript. Its twin is `fieldmate/services/scheme_engine.py`.
 *
 * A rep standing in a market with no signal tells a shopkeeper what the offer comes to, and an hour
 * later the server re-runs the same cart to raise the invoice. If the two numbers differ by a
 * single paisa the shopkeeper stops believing the app, and no amount of correct accounting
 * afterwards buys that back. So this module and its Python twin are written step for step from
 * `docs/SCHEME_SPEC.md`, with the same function names - snake_case here, deliberately, so the
 * identifiers line up - and the same `S4 -` step comments, so that a reviewer can put the two files
 * side by side and read one diff rather than two programs.
 *
 * **Nothing here touches the world.** No Vue, no store, no `fetch`, no Dexie, no DOM, no
 * `Date.now()`, and there must never be one. Every ambiguous decision - which schemes are in scope
 * today, what an item costs, how many pieces are in a case - has already been made by the compiler
 * on the server, which exists once and therefore cannot disagree with itself. What arrives here is
 * a flat compiled spec, cached from `sync.pull`, with no lookups left in it. That is what makes
 * parity provable rather than hoped for: both engines are handed byte-identical input, so any
 * difference between them is in these two hundred lines and nowhere else. It is also why this file
 * imports nothing and runs under a bare `node` with no bundler and no browser behind it.
 *
 * **Money is integer paise, and percentages are integer basis points.** Not because a double would
 * lose the value - at these magnitudes it would hold it fine - but because the two runtimes round
 * differently the moment a half lands on a boundary. Python's `round()` is banker's rounding,
 * `Math.round(-0.5)` is `-0` here and `0` there, and Frappe's `flt()` is a third behaviour again. A
 * trade scheme is exactly the code where halves land on boundaries all day: 5% of a 12345 paise
 * line is 617.25 paise, and a gate that allows zero divergence across 60 carts will find every one
 * of them. Integer arithmetic removes the question instead of testing it, so 5% arrives as `500`,
 * quantities arrive as whole base units, and one primitive - `round_half_up_div` - performs every
 * division in the money path. Integer division is `Math.floor(a / b)` and never `(a / b) | 0`,
 * which silently wraps past 2^31 and would turn a large distributor's cart into a negative one.
 *
 * Rupees never appear here at all. The one float in the whole design,
 * `to_paise(rupees) = floor(rupees * 100 + 0.5)`, lives in the compiler on the server; the
 * evaluator is handed paise and never calls it.
 */

// Basis points in 100%. A percentage is carried as an integer count of these - 5% is 500, 12.5% is
// 1250 - so that no percentage is ever a fraction on its way through the money path.
export const PERCENT_DENOMINATOR = 10000

// The three kinds that come off the shop's bill. `Incentive` is deliberately not among them: it is
// money for the rep, and folding it into the discount overstates what the shopkeeper was actually
// given, which is the kind of number that turns into an argument at month-end claim settlement.
export const DISCOUNT_KINDS = ['Percent Discount', 'Value Discount', 'Rate Off']

// The multipliers a benefit may be granted on, and the ways a scheme may stack. A spec written by
// next month's compiler can carry a value neither of these holds, and section 5.1 is explicit about
// what an old phone does with it: nothing at all. A rep who quotes a discount the server then
// refuses has to take it back across a counter, where one who quotes less than the server grants
// hands over a pleasant surprise. So anything not named here is skipped rather than guessed at.
export const PER_MODES = ['Slab', 'Unit', 'Multiple']
export const STACKING_MODES = ['Exclusive', 'Stackable', 'Best Of Group']

// --------------------------------------------------------------------------------------
// primitives
// --------------------------------------------------------------------------------------

/**
 * floor((2n + d) / (2d)) - the only division in the money path, on integers only.
 *
 * A half always goes up, in both languages, with nothing left for them to disagree about.
 * `2 * n + d` stays well under 2^53 for anything this app can hold - the largest realistic term is
 * a paise amount times basis points, around 10^15 - so `Math.floor` here and `//` there are the
 * same operation on the same integers rather than two roundings that usually match.
 */
export function round_half_up_div(n, d) {
  return Math.floor((2 * n + d) / (2 * d))
}

/**
 * Any number entering the engine, coerced to a whole one.
 *
 * JSON cannot tell 24 from 24.0. A spec that came off the wire carrying 24.0 would have Python
 * answer 24.0 where JavaScript answers 24, which fails a parity run with no bug behind it.
 * `Math.trunc()` and `int()` both truncate toward zero, so the two stay level.
 */
export function as_int(value) {
  if (!has_value(value)) return 0
  const whole = Math.trunc(Number(value))
  return Number.isNaN(whole) ? 0 : whole
}

/**
 * Whether an optional field was supplied at all.
 *
 * `to: null` is an open-topped slab and `budget_paise: null` is an uncapped scheme, so "missing"
 * and "zero" are different answers here and truthiness cannot tell them apart. A key absent from
 * the object reads as `undefined` rather than `null`, and both mean the same thing: not supplied.
 */
export function has_value(value) {
  return value !== null && value !== undefined
}

/**
 * A label on its way into the result, or null when the spec carried none.
 *
 * The guard is for JavaScript's sake: a missing key here reads as `undefined`, and
 * `JSON.stringify` drops an `undefined` value out of the object altogether, where Python would
 * have written `null` and kept the key. Both engines pass every label through this so a spec with
 * a field missing produces the same result on both sides instead of two different shapes.
 */
export function as_text(value) {
  if (!has_value(value)) return null
  return String(value)
}

/** Three-way compare, ascending. */
export function compare_number(a, b) {
  if (a < b) return -1
  if (a > b) return 1
  return 0
}

/**
 * Code-point order, spelled out rather than left to the language.
 *
 * Python would sort these correctly on its own; the comparator exists because JavaScript's
 * `Array.prototype.sort` with no comparator sorts *stringified values lexicographically*, which
 * puts 10 before 9, and because both engines have to be the same shape. Ids are ASCII
 * naming-series strings, where UTF-16 code units and code points agree.
 */
export function compare_text(a, b) {
  if (a < b) return -1
  if (a > b) return 1
  return 0
}

/** The naming-series id, which is the tie-breaker every ordering in here falls back to. */
export function scheme_id(spec) {
  return String(spec.scheme || '')
}

/** S1's order: item code ascending. */
export function compare_lines(a, b) {
  return compare_text(a.item, b.item)
}

/**
 * S3's order: priority ascending, then id ascending.
 *
 * Total, not merely stable. Two schemes at the same priority must resolve the same way on a phone
 * and on the server, and leaning on sort stability would make that depend on the order the specs
 * happened to arrive in.
 */
export function compare_schemes(a, b) {
  const by_priority = compare_number(as_int(a.priority), as_int(b.priority))
  if (by_priority) return by_priority
  return compare_text(scheme_id(a), scheme_id(b))
}

/**
 * Slab order: floor ascending, then declared index.
 *
 * Slabs are validated non-overlapping at save time, so this only formalises the order they were
 * written in - but it means neither engine depends on the array having arrived sorted.
 */
export function compare_slabs(a, b) {
  const by_floor = compare_number(as_int(a.from), as_int(b.from))
  if (by_floor) return by_floor
  return compare_number(as_int(a.idx), as_int(b.idx))
}

/**
 * S8's order within a stack group: richest benefit first, then S3 order.
 *
 * Two schemes in one group are worth the identical rupee more often than it sounds - the same 5%
 * written twice for two brands that turn out to cost the same - and the winner then falls to S3,
 * which is priority before id. A manager who moved one of them to priority 5 has said which they
 * want to fire; breaking the tie on the id alone would hand it to whichever was created first and
 * quietly ignore them.
 */
export function compare_best_of_group(a, b) {
  const by_benefit = compare_number(b.benefit_paise, a.benefit_paise)
  if (by_benefit) return by_benefit
  return compare_schemes(a.spec, b.spec)
}

/** Whether any of these items has already been claimed by an exclusive scheme. */
export function intersects(claimed, items) {
  for (const item of items) {
    if (claimed.has(item)) return true
  }
  return false
}

/**
 * What one free unit costs us, stamped on the benefit by the compiler from the valuation.
 *
 * `value_paise` and nothing else. An engine that also accepted a second spelling would price the
 * same spec two ways the day a compiler emitted both, and the two engines would pick a different
 * spelling first. A benefit that arrives without it is worth zero: the stock still ships, it
 * simply charges no budget, which is the direction that under-promises.
 */
export function free_goods_value(benefit) {
  return as_int(benefit.value_paise)
}

/**
 * How often a benefit is granted: once, once per qualifying unit, or once per slab crossed.
 *
 * "Buy 10 get 1 free" has to fire again at 20 without a manager writing a second slab, which is
 * what `Multiple` counts. A slab starting at zero has no interval to repeat over, so it grants
 * once rather than dividing by nothing.
 */
export function benefit_multiplier(per, measure, slab_from) {
  if (per === 'Unit') return measure
  if (per === 'Multiple') {
    if (slab_from <= 0) return 1
    return Math.floor(measure / slab_from)
  }
  return 1
}

// --------------------------------------------------------------------------------------
// the algorithm, S1 to S10
// --------------------------------------------------------------------------------------

/**
 * S1 - normalise the cart.
 *
 * A rep adds the same SKU twice all the time: once at the top of the order and again when the
 * shopkeeper remembers the back room. Merging those, dropping anything at or below zero and
 * sorting by item is what makes every step after this order-independent - two phones that built
 * the same cart by different routes have to produce the same bytes.
 *
 * The merge holds a Map rather than a plain object on purpose: object keys that look like integers
 * are iterated in numeric order whatever order they went in, and plenty of SKU codes look like
 * integers.
 */
export function s1_normalise(cart) {
  const merged = new Map()
  const raw_lines = cart.lines || []

  for (let position = 0; position < raw_lines.length; position++) {
    const raw = raw_lines[position]
    const item = raw.item
    if (!item) continue
    const rank = has_value(raw.idx) ? as_int(raw.idx) : position
    const line = merged.get(item)
    if (line === undefined) {
      merged.set(item, {
        item: item,
        qty: as_int(raw.qty),
        rate_paise: as_int(raw.rate_paise),
        rank: rank,
      })
      continue
    }
    line.qty = line.qty + as_int(raw.qty)
    // Both halves of a duplicated SKU carry the same rate, because the compiler resolved one rate
    // per item from the price list before the cart was ever built. Should they somehow differ,
    // the earliest line by its own idx wins - never the one that happened to sit earlier in the
    // array, which is the thing two phones can disagree about.
    if (rank < line.rank) {
      line.rate_paise = as_int(raw.rate_paise)
      line.rank = rank
    }
  }

  const kept = [...merged.values()].filter((line) => line.qty > 0)
  kept.sort(compare_lines)

  return kept.map((line, position) => ({
    idx: position + 1,
    item: line.item,
    qty: line.qty,
    rate_paise: line.rate_paise,
  }))
}

/**
 * S2 - line gross.
 *
 * `qty * rate_paise` is an exact integer product and the cart total is a sum of them, so nothing
 * can drift here even in principle.
 */
export function s2_line_gross(lines) {
  const priced = lines.map((line) => ({ ...line, gross_paise: line.qty * line.rate_paise }))
  let cart_gross_paise = 0
  for (const line of priced) {
    cart_gross_paise = cart_gross_paise + line.gross_paise
  }
  return { lines: priced, cart_gross_paise: cart_gross_paise }
}

/**
 * S3 - order the schemes.
 *
 * Priority first, then the naming-series id, which is ASCII and therefore sorts identically in
 * both runtimes. Never by name: names are typed by managers, hold non-ASCII the moment someone
 * writes a rupee sign or a Hindi word, and that is where UTF-16 and code-point order part ways.
 * The copy is not decoration - `sort` mutates in place, and the caller's array of cached specs is
 * not this function's to reorder.
 */
export function s3_order_schemes(specs) {
  return specs.slice().sort(compare_schemes)
}

/**
 * S4 - measure each scheme.
 *
 * The qualifying gross is kept apart from the cart gross because a percentage comes off the
 * qualifying lines and nothing else. A 5% soap scheme must not discount the tea.
 */
export function s4_measure(spec, lines) {
  // An Order scheme means the whole cart and reads nothing else - not the item list, not its
  // length. The compiler is required to emit an empty list beside Order, so a spec carrying both
  // is malformed; a malformed spec still has to come to the same rupee on the phone and on the
  // server, and reading the list as a filter instead is a second, undocumented answer.
  const wanted = new Set(spec.qualifying_items || [])
  const whole_cart = spec.measured_over === 'Order'

  const qualifying = lines.filter((line) => whole_cart || wanted.has(line.item))

  let qualifying_gross_paise = 0
  let qualifying_qty = 0
  for (const line of qualifying) {
    qualifying_gross_paise = qualifying_gross_paise + line.gross_paise
    qualifying_qty = qualifying_qty + line.qty
  }

  const measure = spec.basis === 'Value' ? qualifying_gross_paise : qualifying_qty

  return {
    qualifying: qualifying,
    qualifying_gross_paise: qualifying_gross_paise,
    measure: measure,
    // Nothing in the cart qualifies, so the scheme cannot apply - but it is still measured at
    // zero, because S10 has to tell the rep what they are one SKU away from.
    applicable: qualifying.length > 0,
  }
}

/**
 * S5 - pick the slab.
 *
 * The highest slab whose floor the measure has reached and whose ceiling it has not passed. Slabs
 * are validated non-overlapping at save time, so at most one can match and "highest" is a safety
 * net rather than a policy - but it is a net both engines have to hold at the same height.
 */
export function s5_pick_slab(spec, measure) {
  let chosen = null
  for (const slab of spec.slabs || []) {
    if (measure < as_int(slab.from)) continue
    const ceiling = slab.to
    if (has_value(ceiling) && measure > as_int(ceiling)) continue
    if (chosen === null || compare_slabs(chosen, slab) < 0) chosen = slab
  }
  return chosen
}

/**
 * S6 - compute benefits.
 *
 * In the order the manager wrote them, and every entry carries all six keys whether or not its kind
 * has anything to put in them - a result whose shape changes with its contents cannot be compared
 * field by field against the other engine's, which is the whole of Gate 4. The rounding happens
 * once, on the percentage, before the multiplier is applied: rounding afterwards would turn a
 * half-paise into a whole one every time a scheme fired more than once, and the rep would quote a
 * figure the invoice never reaches.
 */
export function s6_benefits(spec, slab, measure, qualifying_gross_paise) {
  const benefits = []
  const free_goods = []
  let benefit_paise = 0
  let cost_paise = 0

  for (const raw of slab.benefits || []) {
    const kind = as_text(raw.kind)
    const per = as_text(raw.per)

    if (!PER_MODES.includes(per)) continue
    if (per === 'Unit' && spec.basis === 'Value') {
      // On a value basis the measure is already paise, so "50 paise per unit" against a 250-rupee
      // cart would multiply out to 12,500 rupees off. The compiler refuses the combination; an
      // evaluator handed one anyway leaves the benefit alone rather than paying out a number
      // nobody intended.
      continue
    }

    const multiplier = benefit_multiplier(per, measure, as_int(slab.from))
    let amount_paise = 0
    let item = null
    let qty = 0

    if (kind === 'Free Goods') {
      // Free goods bill at zero and leave as their own lines. They never re-enter any basis: a
      // free case that helped the cart cross the next slab would have the scheme funding its own
      // escalation. The amount is what the granted stock costs us, which is both what the shop is
      // receiving and what the budget is paying for.
      item = as_text(raw.item)
      qty = as_int(raw.qty) * multiplier
      amount_paise = qty * free_goods_value(raw)
      free_goods.push({
        item: item,
        qty: qty,
        scheme: scheme_id(spec),
        value_paise: amount_paise,
      })
    } else if (kind === 'Percent Discount') {
      amount_paise =
        round_half_up_div(qualifying_gross_paise * as_int(raw.pct_bp), PERCENT_DENOMINATOR) *
        multiplier
    } else if (kind === 'Value Discount' || kind === 'Rate Off') {
      amount_paise = as_int(raw.amount_paise) * multiplier
    } else if (kind === 'Incentive') {
      // The rep's money. It never reaches net_paise and is no part of what the shop receives,
      // because the shopkeeper was never given it - but a budget is a cap on what the scheme pays
      // out, and this leaves the same pocket the discount does.
      amount_paise = as_int(raw.amount_paise) * multiplier
    } else {
      // A kind this engine does not know is left out of every total rather than guessed at. A
      // spec from a newer compiler must under-promise on an old phone, never over-promise.
      continue
    }

    benefits.push({
      kind: kind,
      per: per,
      multiplier: multiplier,
      amount_paise: amount_paise,
      item: item,
      qty: qty,
    })
    cost_paise = cost_paise + amount_paise
    if (kind !== 'Incentive') benefit_paise = benefit_paise + amount_paise
  }

  return {
    benefits: benefits,
    free_goods: free_goods,
    // What the shop receives: the bill reduction plus the value of the free stock. It is the
    // "Benefit Value" the rep reads out at the counter and the figure a stack group is ranked on,
    // so the rep's own incentive is left out of it.
    benefit_paise: benefit_paise,
    // What the budget is charged, deliberately the wider figure: every paisa the scheme pays out,
    // incentive included.
    cost_paise: cost_paise,
  }
}

/**
 * S7 - budget.
 *
 * A scheme that cannot be afforded in full is dropped in full. Paying part of it would leave a
 * discount on the invoice reconciling against nothing in the scheme ledger, and somebody in
 * accounts would spend a week on it. `Warn` is the configured exception: the scheme still applies,
 * and the result says out loud that its pot is empty.
 */
export function s7_budget(spec, cost_paise) {
  const budget_paise = spec.budget_paise
  if (!has_value(budget_paise)) return { drop: false, warning: false }

  const remaining = as_int(budget_paise) - as_int(spec.consumed_paise)
  if (cost_paise <= remaining) return { drop: false, warning: false }
  if (spec.on_exhaust === 'Warn') return { drop: false, warning: true }
  return { drop: true, warning: false }
}

/**
 * S8 - stacking.
 *
 * Walked in S3 order holding the set of items already claimed, so an earlier `Exclusive` beats a
 * later one: priority is how a manager expresses intent, and the engine honours that rather than
 * re-deciding it. Only `Exclusive` claims anything. `Stackable` claims nothing and excludes
 * nothing - it applies alongside whatever else survived - but an earlier `Exclusive` can still
 * take it away, because that one did the claiming.
 */
export function s8_stacking(candidates) {
  const claimed = new Set()
  const survivors = []
  const dropped = []

  for (const candidate of candidates) {
    const spec = candidate.spec
    if (intersects(claimed, candidate.items)) {
      dropped.push({ scheme: scheme_id(spec), reason: 'EXCLUSIVE_OVERLAP' })
      continue
    }
    if (spec.stacking === 'Exclusive') {
      for (const item of candidate.items) claimed.add(item)
    }
    survivors.push(candidate)
  }

  // Within one stack group only the richest survives, a tie going to whichever comes first in S3
  // order so that the manager's priority decides it and every device decides it alike. This map is
  // only ever asked about a key it was given and never iterated, so its key order cannot reach the
  // result.
  const best = new Map()
  for (const candidate of survivors) {
    const spec = candidate.spec
    if (spec.stacking !== 'Best Of Group') continue
    const group = String(spec.stack_group || '')
    const held = best.get(group)
    if (held === undefined || compare_best_of_group(candidate, held) < 0) best.set(group, candidate)
  }

  const kept = []
  for (const candidate of survivors) {
    const spec = candidate.spec
    if (spec.stacking === 'Best Of Group') {
      const group = String(spec.stack_group || '')
      if (best.get(group) !== candidate) {
        dropped.push({ scheme: scheme_id(spec), reason: 'BEST_OF_GROUP' })
        continue
      }
    }
    kept.push(candidate)
  }

  return { kept: kept, dropped: dropped }
}

/**
 * S9 - total.
 *
 * Incentive is summed alongside the discount and then left out of the net, which is the whole
 * point of counting it apart: it is the rep's earning, not the shop's reduction. A cart that tries
 * to go negative is a scheme somebody mis-configured, so it floors at zero and says so rather than
 * quietly handing back a credit nobody authorised.
 */
export function s9_total(cart_gross_paise, applied) {
  let discount_paise = 0
  let incentive_paise = 0
  const errors = []

  for (const entry of applied) {
    for (const benefit of entry.benefits) {
      if (benefit.kind === 'Incentive') {
        incentive_paise = incentive_paise + benefit.amount_paise
      } else if (DISCOUNT_KINDS.includes(benefit.kind)) {
        discount_paise = discount_paise + benefit.amount_paise
      }
    }
  }

  let net_paise = cart_gross_paise - discount_paise
  if (net_paise < 0) {
    errors.push('NEGATIVE_NET')
    net_paise = 0
  }

  return {
    discount_paise: discount_paise,
    net_paise: net_paise,
    incentive_paise: incentive_paise,
    errors: errors,
  }
}

/**
 * S10 - near misses.
 *
 * The nudge that turns a 9-case order into a 10-case one: "add 1 more case to unlock Tier 3".
 * Always the lowest slab still above the measure, so the gap is a number of units the rep can
 * actually add to the cart and is never zero or less. Where nothing sits above the measure - the
 * top slab is already matched, or a closed top has nothing beyond it - there is no nudge to give
 * and the scheme is left out entirely, because "order 380 fewer units" is worse than silence.
 * Advisory always: nothing here may alter a total.
 */
export function s10_near_misses(measured) {
  const near_misses = []

  for (const entry of measured) {
    const spec = entry.spec
    const measure = entry.measure

    let nxt = null
    for (const slab of spec.slabs || []) {
      if (as_int(slab.from) <= measure) continue
      if (nxt === null || compare_slabs(slab, nxt) < 0) nxt = slab
    }
    if (nxt === null) continue

    near_misses.push({
      scheme: scheme_id(spec),
      scheme_name: as_text(spec.scheme_name),
      slab_idx: as_int(nxt.idx),
      basis: as_text(spec.basis),
      measure: measure,
      gap: as_int(nxt.from) - measure,
    })
  }

  return near_misses
}

// --------------------------------------------------------------------------------------
// evaluate
// --------------------------------------------------------------------------------------

/**
 * Run a cart against a set of compiled specs and return what the shopkeeper gets.
 *
 * Two money figures come out of every applied scheme and they are deliberately not the same number.
 * `benefit_paise` is what the shop receives - the bill reduction plus the value of the free stock -
 * and it is what the rep reads out and what a stack group is ranked on. The budget in S7 is charged
 * the wider figure, incentive included, because the cap a manager set is on what the scheme pays
 * out and the rep's money leaves the same decision. Collapsing the two would either promise the
 * shopkeeper the rep's incentive or let a scheme spend past its cap.
 */
export function evaluate(cart, specs) {
  const normalised = s1_normalise(cart || {})
  const priced = s2_line_gross(normalised)
  const lines = priced.lines
  const cart_gross_paise = priced.cart_gross_paise

  const ordered = s3_order_schemes(specs || [])

  const measured = []
  const candidates = []
  // Keyed by scheme so the output order is S3's rather than the order the drops happened to occur
  // in, which changes as soon as a budget or a stack group changes.
  const dropped = new Map()

  for (const spec of ordered) {
    // A stacking mode this build has never heard of is left out of everything - not applied, not
    // dropped, not even hinted at in the near misses. The engine cannot know whether it would have
    // combined with the others or excluded them, so nudging a rep toward it is a promise there is
    // no way to keep.
    if (!STACKING_MODES.includes(spec.stacking)) continue

    const reading = s4_measure(spec, lines)
    const slab = reading.applicable ? s5_pick_slab(spec, reading.measure) : null
    measured.push({ spec: spec, measure: reading.measure })
    if (slab === null) continue

    const computed = s6_benefits(spec, slab, reading.measure, reading.qualifying_gross_paise)

    const verdict = s7_budget(spec, computed.cost_paise)
    if (verdict.drop) {
      dropped.set(scheme_id(spec), 'BUDGET_EXHAUSTED')
      continue
    }

    candidates.push({
      spec: spec,
      slab: slab,
      measure: reading.measure,
      items: new Set(reading.qualifying.map((line) => line.item)),
      benefits: computed.benefits,
      free_goods: computed.free_goods,
      benefit_paise: computed.benefit_paise,
      budget_warning: verdict.warning,
    })
  }

  const stacked = s8_stacking(candidates)
  for (const entry of stacked.dropped) {
    dropped.set(entry.scheme, entry.reason)
  }

  const applied = []
  const free_goods = []
  for (const candidate of stacked.kept) {
    applied.push({
      scheme: scheme_id(candidate.spec),
      scheme_name: as_text(candidate.spec.scheme_name),
      slab_idx: as_int(candidate.slab.idx),
      measure: candidate.measure,
      benefits: candidate.benefits,
      benefit_paise: candidate.benefit_paise,
      budget_warning: candidate.budget_warning,
    })
    for (const free_line of candidate.free_goods) free_goods.push(free_line)
  }

  const totals = s9_total(cart_gross_paise, applied)

  return {
    cart_gross_paise: cart_gross_paise,
    discount_paise: totals.discount_paise,
    net_paise: totals.net_paise,
    incentive_paise: totals.incentive_paise,
    applied: applied,
    free_goods: free_goods,
    // A scheme that was taken away gets no nudge. Telling a rep they are twenty units from a
    // benefit that has already been dropped for budget or beaten by an exclusive is a lie the app
    // would be telling on our behalf, and they would find out at the counter.
    near_misses: s10_near_misses(measured.filter((entry) => !dropped.has(scheme_id(entry.spec)))),
    dropped: ordered
      .filter((spec) => dropped.has(scheme_id(spec)))
      .map((spec) => ({
        scheme: scheme_id(spec),
        scheme_name: as_text(spec.scheme_name),
        reason: dropped.get(scheme_id(spec)),
      })),
    errors: totals.errors,
  }
}
