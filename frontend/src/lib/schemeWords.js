/**
 * A compiled scheme spec, in the words a rep says out loud.
 *
 * DESIGN.md UX requirement 10 is the whole reason this file exists: "why did I get this discount"
 * is the single most common field support call, and an amount with no sentence beside it is what
 * generates it. The engine returns `{scheme, slab_idx, benefit_paise}` and nothing a shopkeeper
 * could be told; this turns that into "5% off on 2 Cases and up" without any screen having to know
 * what a basis point is.
 *
 * Three rules run through it.
 *
 * **The manager's own sentence wins.** `FieldMate Scheme.rep_pitch` is a field called "Reads As",
 * written by the person who designed the offer, and it travels all the way to the phone on the
 * compiled spec. Where it is filled, nothing here paraphrases it. What follows is the fallback for
 * the schemes nobody wrote a line for - which, in practice, is most of them.
 *
 * **Thresholds are spoken in the rep's units, not the engine's.** A compiled slab reads
 * `{"from": 240}` because the compiler converted "2 cases" into base units (SCHEME_SPEC.md, the
 * compiled-spec section). Reading 240 back out to a rep who typed 2 is how an offer stops making
 * sense at a counter, so every threshold is converted back through the same conversion factor the
 * cart holds - and falls back to base units, named, when the division is not whole.
 *
 * **Nothing here computes money.** Every paise figure is handed in already computed by the engine
 * or the store. This file formats and narrates; a number invented here would be a second opinion
 * about what the shop is owed, and there is only ever allowed to be one.
 *
 * Deliberately does not import from `scheme/engine.js`, for the same reason `lib/money.js` does
 * not: that file is a line-for-line mirror of its Python twin under a zero-tolerance parity gate,
 * and a display helper has no business being a reason to open it. The one constant it needs is
 * restated below and is checked by eye against S9.
 */

import { formatPaise } from './money'

// S9: the kinds that come off the bill. `Free Goods` is not among them - it ships at zero in
// addition to the order - and neither is `Incentive`, which is the rep's money and was never the
// shopkeeper's. DESIGN.md UX requirement 11 turns on this distinction holding everywhere.
const DISCOUNT_KINDS = ['Percent Discount', 'Value Discount', 'Rate Off']

/**
 * The symbol in front of a figure.
 *
 * `lib/money.js` deliberately has none: it is arithmetic at a boundary and a hard-coded rupee sign
 * there would be wrong the first time this ships somewhere it is not one. This is the display
 * layer, where a rep is reading a price off a screen at a counter, so the symbol belongs. The
 * outlet's own currency comes down on the catalogue payload; anything we do not have a glyph for
 * is spoken as its code, which is at least unambiguous.
 */
export function symbolFor(currency) {
  if (!currency || currency === 'INR') return '₹'
  if (currency === 'USD') return '$'
  if (currency === 'EUR') return '€'
  if (currency === 'GBP') return '£'
  return `${currency} `
}

/** Paise as money a rep reads out. Always pair the rendering element with the `tnum` class. */
export function moneyLabel(paise, currency, options = {}) {
  return `${symbolFor(currency)}${formatPaise(paise, options)}`
}

/**
 * A unit of measure beside a quantity.
 *
 * Not pluralised blindly. ERPNext's stock UOMs are things like `Nos`, `Box` and `Kg`, and an `s`
 * on the end of the commonest one in Indian FMCG gives "24 Noss" - which is how a rep decides the
 * app was not written by anybody who has stood in a shop. Anything already ending in a sibilant is
 * left exactly as the item master spells it.
 */
export function uomLabel(qty, uom) {
  const unit = (uom || '').trim()
  if (!unit) return ''
  if (Number(qty) === 1) return unit
  if (/[sxz]$/i.test(unit)) return unit
  return `${unit}s`
}

/** "2 Cases", "24 Nos" - a quantity and its unit, ready to sit beside each other. */
export function qtyWords(qty, uom) {
  const n = Number(qty)
  const shown = Number.isInteger(n) ? n : Math.round(n * 1000) / 1000
  return `${shown} ${uomLabel(shown, uom)}`.trim()
}

/**
 * A percentage out of basis points. 500 is "5%", 250 is "2.5%".
 *
 * Basis points are integers by construction (ADR-022), so the division has no float trouble at
 * this magnitude - but the trailing zeros do have to go, because "5.00% off" reads like a figure
 * somebody is being careful about rather than an offer.
 */
export function percentWords(pct_bp) {
  const value = (Number(pct_bp) || 0) / 100
  return `${value.toFixed(2).replace(/\.?0+$/, '')}%`
}

/**
 * A slab floor, spoken in the unit the rep types in.
 *
 * `ctx.factor` is the conversion factor of the item this threshold is being spoken about - the one
 * on the catalogue row, or on the cart line. Where the floor does not divide by it evenly there is
 * no honest way to say it in cases, so it is said in pieces instead and named as such.
 */
export function thresholdWords(spec, slab, ctx = {}) {
  const from = Number(slab?.from) || 0
  if (spec?.basis === 'Value') return moneyLabel(from, ctx.currency)

  const factor = Number(ctx.factor) || 1
  if (factor > 1 && from % factor === 0) return qtyWords(from / factor, ctx.display_uom)
  return qtyWords(from, ctx.base_uom)
}

/**
 * One benefit, in a phrase that can stand on its own.
 *
 * `ctx.nameFor(code)` resolves a free item's code to the name on the pack, because "1 Nos of
 * SE-1000 free" is not something anybody says in a shop.
 */
export function benefitWords(benefit, spec, ctx = {}) {
  const kind = benefit?.kind
  const currency = ctx.currency

  if (kind === 'Percent Discount') {
    return `${percentWords(benefit.pct_bp)} off`
  }
  if (kind === 'Value Discount') {
    return `${moneyLabel(benefit.amount_paise, currency)} off`
  }
  if (kind === 'Rate Off') {
    const each = ctx.base_uom ? ` each ${ctx.base_uom}` : ' per unit'
    return `${moneyLabel(benefit.amount_paise, currency)} off${benefit.per === 'Unit' ? each : ''}`
  }
  if (kind === 'Free Goods') {
    const name = ctx.nameFor ? ctx.nameFor(benefit.item) : benefit.item
    const qty = Number(benefit.qty) || 0
    return `${qtyWords(qty, ctx.freeUomFor ? ctx.freeUomFor(benefit.item) : null)} ${name} free`.replace(/\s+/g, ' ')
  }
  if (kind === 'Incentive') {
    // Marked as the rep's own wherever it appears. A shopkeeper told they were given the rep's
    // incentive is an argument at month-end, and the engine keeps the two apart for that reason.
    return `${moneyLabel(benefit.amount_paise, currency)} incentive for you`
  }
  // A kind this build has never heard of. The engine leaves it out of every total rather than
  // guessing, so there is nothing truthful to say about it here either.
  return null
}

/** Every benefit on a slab, joined into one phrase. */
export function slabWords(spec, slab, ctx = {}) {
  const parts = (slab?.benefits || [])
    .map((b) => benefitWords(b, spec, ctx))
    .filter(Boolean)
  return parts.join(' + ')
}

/**
 * The badge a catalogue row wears: the shortest true thing about this offer.
 *
 * The manager's own line first. Otherwise the first slab, which is the one a shop that is not
 * buying yet can actually reach.
 */
export function schemeBadge(spec, ctx = {}) {
  if (spec?.rep_pitch) return spec.rep_pitch

  const slabs = [...(spec?.slabs || [])].sort((a, b) => (Number(a.from) || 0) - (Number(b.from) || 0))
  const first = slabs[0]
  if (!first) return spec?.scheme_name || null

  const benefits = slabWords(spec, first, ctx)
  if (!benefits) return spec?.scheme_name || null

  const floor = Number(first.from) || 0
  if (floor <= 0) return benefits
  return `${benefits} on ${thresholdWords(spec, first, ctx)}+`
}

/**
 * What a scheme that has already fired gave this cart, in a sentence.
 *
 * Takes a row of the store's `appliedSchemes`, which carries the engine's benefits plus the spec's
 * own pitch. The free goods are named separately by the caller and are not folded in here, so no
 * screen can accidentally render one combined savings figure (DESIGN.md UX requirement 11).
 */
export function appliedWords(entry, spec, ctx = {}) {
  const slab = (spec?.slabs || []).find((s) => Number(s.idx) === Number(entry?.slab_idx))
  const measure = spec?.basis === 'Value'
    ? moneyLabel(entry?.measure, ctx.currency)
    : thresholdWords(spec, { from: entry?.measure }, ctx)

  const benefits = slab ? slabWords(spec, slab, ctx) : null
  if (!benefits) return spec?.rep_pitch || entry?.scheme_name || null
  return `${measure} in the order → ${benefits}`
}

/** What comes off this bill because of one scheme. Free stock and the rep's incentive are not it. */
export function billDiscountPaise(entry) {
  return (entry?.benefits || [])
    .filter((b) => DISCOUNT_KINDS.includes(b.kind))
    .reduce((sum, b) => sum + (Number(b.amount_paise) || 0), 0)
}

/** What this scheme pays the rep. Never part of a total the shop is shown. */
export function incentivePaise(entry) {
  return (entry?.benefits || [])
    .filter((b) => b.kind === 'Incentive')
    .reduce((sum, b) => sum + (Number(b.amount_paise) || 0), 0)
}

/**
 * The nudge, in words: what one more case earns, and what it beats.
 *
 * `entry` is a row of the store's `nearMisses`, which has already split the engine's bare `gap`
 * into units and paise so nothing here has to remember which a basis implies. `applied` is the
 * same scheme's row in `appliedSchemes` when it is already firing at a lower slab, which is what
 * turns "get 5% off" into "5% off instead of 3%" - the version that actually moves an order.
 */
export function nearMissWords(entry, spec, ctx = {}, applied = null) {
  const target = (spec?.slabs || []).find((s) => Number(s.idx) === Number(entry?.slab_idx))
  if (!target) return null

  const earns = slabWords(spec, target, ctx)
  if (!earns) return null

  const current = applied
    ? slabWords(spec, (spec.slabs || []).find((s) => Number(s.idx) === Number(applied.slab_idx)), ctx)
    : null

  return {
    earns,
    instead_of: current || null,
    threshold: thresholdWords(spec, target, ctx),
    scheme_name: spec?.scheme_name || entry?.scheme_name || null,
    pitch: spec?.rep_pitch || null,
  }
}

/**
 * The tap that closes a near miss: which line to add to, and how many of the rep's own units.
 *
 * Pure, and out here rather than inside the cart screen, because it is the one piece of arithmetic
 * on that screen a rep acts on without checking. "Add 1 case" has to be a case that actually
 * crosses the slab, and the failure mode - a button that adds stock and earns nothing - is one the
 * rep discovers only after the shopkeeper has agreed to it.
 *
 * `miss` is a row of the store's `nearMisses`, whose `gap` the store has already split into
 * `gap_units` (base units, on a Qty scheme) and `gap_paise` (on a Value one). `lines` is the
 * decorated cart. Returns `null` where the gap cannot honestly be closed, which is the case that
 * matters most: no qualifying line in the cart to add to, or every candidate line already at the
 * most this shop may order.
 *
 * Both roundings go up. A tap that leaves the rep one unit short of the slab is the worst outcome
 * this function has, so where a case does not divide the gap evenly it buys the whole case.
 */
export function planNudge(miss, spec, lines) {
  if (!miss || !spec) return null

  const wholeCart = spec.measured_over === 'Order'
  const wanted = new Set(spec.qualifying_items || [])

  const candidates = (lines || [])
    .filter((l) => l.qty > 0 && !l.unpriceable && l.rate_paise)
    .filter((l) => wholeCart || wanted.has(l.item_code))
    // The line the rep is already buying most of, and the cheapest one where two are level: the
    // tap has to feel like more of what is already on the counter.
    .sort((a, b) => b.qty - a.qty || a.rate_paise - b.rate_paise)

  for (const line of candidates) {
    const factor = Number(line.conversion_factor) || 1

    let needBase
    if (miss.gap_units !== null && miss.gap_units !== undefined) {
      needBase = Number(miss.gap_units)
    } else if (miss.gap_paise) {
      needBase = Math.ceil(Number(miss.gap_paise) / line.rate_paise)
    } else {
      continue
    }
    if (!(needBase > 0)) continue

    const addDisplay = Math.ceil(needBase / factor)
    if (!(addDisplay > 0)) continue

    // The store would refuse the whole order at submit over this, and the rep would find out at
    // the end of it rather than here.
    if (line.max_order_qty && line.display_qty + addDisplay > line.max_order_qty) continue

    const addBase = addDisplay * factor
    return {
      item_code: line.item_code,
      item_name: line.item_name,
      add_display: addDisplay,
      add_uom: line.display_uom,
      add_base: addBase,
      cost_paise: addBase * line.rate_paise,
    }
  }

  return null
}

/** Why a scheme was taken away, in a rep's words rather than an enum. */
export function droppedWords(reason) {
  if (reason === 'BUDGET_EXHAUSTED') return 'This offer has run out of budget for the month.'
  if (reason === 'EXCLUSIVE_OVERLAP') return 'A better offer on the same items is being applied instead.'
  if (reason === 'BEST_OF_GROUP') return 'Another offer in the same group pays this shop more.'
  return 'This offer is not being applied to this order.'
}

/** The engine's own complaints about a cart, said out loud rather than swallowed. */
export function totalErrorWords(code) {
  if (code === 'NEGATIVE_NET') {
    return 'The offers on this order come to more than the order itself. It has been held at zero — ' +
      'show this to your manager before you promise it.'
  }
  return 'Something in the offers on this order does not add up. Show it to your manager before you promise it.'
}
