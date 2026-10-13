/**
 * The cart, and the reason this app is worth building.
 *
 * A rep is standing at a counter with a shopkeeper who wants to know what ten cases come to. There
 * is no signal. There is frequently no signal for the whole beat. The number the rep says out loud
 * has to be the number on the invoice the distributor raises that evening, and it has to appear the
 * instant a quantity changes - not after a spinner, not after a round trip that may never return.
 *
 * So four rules run through everything below.
 *
 * **Re-pricing never touches the network.** `reprice()` is synchronous and calls the local scheme
 * engine over compiled specs cached per outlet. A quantity tap re-prices in memory. The only calls
 * that leave the phone are filling the two caches, checking the server's figure when there happens
 * to be signal, and submitting. `docs/SCHEME_SPEC.md` budgets 150 ms for a forty-line cart, which
 * is only achievable because nothing here awaits anything on the hot path.
 *
 * **Base units are the truth and the display is derived from them, never the other way round.** A
 * line holds `qty` in whole base units and a `conversion_factor`; "2 Cases" and "24 units" are two
 * readings of that one integer, computed on the way out. The Stitch cart shows both at once, and
 * two numbers stored separately are two numbers that eventually disagree - usually the evening
 * somebody types 2.5 cases.
 *
 * **Money is integer paise.** Same reason as the engine (ADR-022): the two runtimes round
 * differently the moment a half lands on a boundary. Rupees appear at exactly two edges - the
 * catalogue rate arriving from the server, and the payload leaving for it - and both conversions go
 * through `lib/money.js` and nowhere else. A float in the cart is a bug.
 *
 * **The cart is written down before it is anything else.** It lives in IndexedDB keyed by outlet,
 * so a rep who backgrounds the app mid-order, takes a call, or has the WebView killed by Android
 * comes back to the same cart. That is also why a rep can hold a part-built order at more than one
 * shop on a beat.
 *
 * What the phone computes is **advisory**. `fieldmate.api.scheme.evaluate` on the server is the
 * figure of record, and the order carries `proposed_net_total` - the number the rep actually said -
 * so the two can be compared rather than assumed equal. See ADR-021 and ADR-023: a retailer order
 * is a secondary sale, it goes to the distributor's queue, and it creates no Sales Order.
 */

import { computed, ref } from 'vue'
import { api, ApiError } from '../api/client'
import { db, deviceUuid, getMeta, rememberName, setMeta } from '../db'
import { enqueue } from '../sync/outbox'
import { evaluate } from '../scheme/engine'
import { formatPaise, fromPaise, toPaise } from '../lib/money'
import { forLines as taxFor } from '../lib/tax'
import { advanceView, isBooking } from '../lib/season'
import * as visitStore from './visit'

/** Anything the rep did that the cart will not accept, with a sentence they can act on. */
export class CartError extends Error {
  constructor(code, message) {
    super(message)
    this.code = code
  }
}

// How old a cached catalogue or set of specs may be before the screen says so out loud. Half a day,
// because a rep pulls at day start and anything older than that was fetched in a different market
// on a different price list. Nothing is blocked on it - a stale offer quoted knowingly is worth far
// more than an order the rep could not take at all - but it is never hidden either.
const STALE_AFTER_MS = 12 * 60 * 60 * 1000

// --------------------------------------------------------------------------------------- state

export const outlet = ref(null)
// Which kind of party the open order is for: null or 'Outlet' for a shop, 'Customer' for a
// party we bill ourselves. It rides beside the name rather than being inferred from it,
// because the two namespaces can and do collide - a Customer and an outlet may share a name,
// and guessing wrong prices the cart off the wrong list.
export const partyType = ref(null)
export const outletName = ref(null)

/** Cart lines, base units only. Everything a screen reads goes through `lines` below. */
const rawLines = ref([])

/** The cached catalogue payload for the open outlet, and the cached compiled specs. */
export const catalogue = ref(null)
export const specs = ref([])
export const skippedSchemes = ref([])

export const loading = ref(false)
export const error = ref(null)

/** When each cache was last filled, so the screen can show its own age rather than imply currency. */
const catalogueFetchedAt = ref(null)
const specsFetchedAt = ref(null)
const specsCompiledOn = ref(null)

/** The last engine result. Paise throughout; `totals` below is where rupees happen. */
const pricing = ref(emptyPricing())

// A rep who walks out of one shop and into the next while a catalogue is still downloading must not
// have the first shop's items land in the second shop's screen. Every async load carries the token
// it started under and discards itself if the outlet has moved on.
let loadToken = 0

function emptyPricing() {
  return {
    cart_gross_paise: 0,
    discount_paise: 0,
    net_paise: 0,
    incentive_paise: 0,
    applied: [],
    free_goods: [],
    near_misses: [],
    dropped: [],
    errors: [],
  }
}

function isOffline(e) {
  return e instanceof ApiError && e.code === 'OFFLINE'
}

function todayStamp() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function plain(value) {
  return JSON.parse(JSON.stringify(value))
}

// ------------------------------------------------------------------------------ units and lines

/**
 * A quantity the rep typed, as whole base units.
 *
 * `floor(qty * factor + 0.5)` is deliberately the same expression as `catalogue_service.cart_for`
 * on the server, so a cart of two and a half cases becomes the same integer on both sides. Rounding
 * once, here, is also what keeps a fraction from drifting through every slab comparison downstream -
 * the engine counts whole units and has no opinion about halves.
 */
function toBaseQty(value, factor) {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.floor(n * (Number(factor) || 1) + 0.5)
}

/**
 * One line as every screen reads it: the stored truth plus everything derived from it.
 *
 * Derived on the way out rather than stored, which is the only arrangement in which "2 Cases" and
 * "24 units" cannot come apart. `display_whole` and `display_remainder` are for the cart's second
 * line - "2 Cases + 1 Nos" reads better to a shopkeeper than "2.083 Cases" - and are left null where
 * the conversion is not a whole number, because there is no honest way to split a case then.
 */
function decorate(line) {
  const factor = Number(line.conversion_factor) || 1
  const wholeFactor = Number.isInteger(factor) && factor > 0
  const gross_paise = line.qty * (line.rate_paise || 0)

  return {
    ...line,
    gross_paise,
    gross: formatPaise(gross_paise),
    // The truth, restated. Never rounded to a display precision that could then be typed back in.
    display_qty: Math.round((line.qty / factor) * 1000) / 1000,
    display_whole: wholeFactor ? Math.floor(line.qty / factor) : null,
    display_remainder: wholeFactor ? line.qty % factor : null,
    display_rate_paise: line.rate_paise === null ? null : line.rate_paise * factor,
    display_rate: line.rate_paise === null ? null : formatPaise(line.rate_paise * factor),
    rate: line.rate_paise === null ? null : formatPaise(line.rate_paise),
  }
}

function newLine(item) {
  const factor = Number(item.conversion_factor) || 1
  return {
    item_code: item.item_code,
    item_name: item.item_name || item.item_code,
    item_group: item.item_group || null,
    brand: item.brand || null,

    // Base units, whole, and the only quantity anything is computed from.
    qty: 0,
    base_uom: item.stock_uom,
    display_uom: item.order_uom || item.stock_uom,
    conversion_factor: factor,
    // Recorded so a screen can say why a case order fell back to pieces rather than silently
    // booking twelve times less than the rep meant.
    uom_fallback: !!item.order_uom_fallback,

    // Per base unit, in paise. `rate` arrives from the server in rupees and is converted here, at
    // the edge, exactly as the specification's `to_paise` does it.
    rate_paise: item.unpriceable ? null : toPaise(item.rate),
    unpriceable: !!item.unpriceable,
    currency: item.currency || null,
    mrp: item.mrp ?? null,
    // The price list quotes above the price printed on the pack. The server refuses an order
    // holding one, so the cart says so here rather than letting the rep find out at submit.
    above_mrp: !!item.above_mrp,
    // The distributor's tax rate on this item, in basis points. Zero means no tax template
    // covers it, which is most items on most sites.
    tax_bps: Math.trunc(item.tax_bps || 0),

    // In display units, as the catalogue master was written.
    min_order_qty: item.min_order_qty ?? null,
    max_order_qty: item.max_order_qty ?? null,

    is_focus: !!item.is_focus,
    is_must_sell: !!item.is_must_sell,
    has_order_history: !!item.has_order_history,
    last_ordered_qty: item.last_ordered_qty ?? null,
    last_ordered_on: item.last_ordered_on ?? null,
    notes: item.notes || null,
  }
}

// ------------------------------------------------------------------------------------- exposed

/** Cart lines, decorated. This is what a screen iterates. */
export const lines = computed(() => rawLines.value.map(decorate))

export const lineCount = computed(() => rawLines.value.length)

/** Total pieces in the cart, base units. The figure that goes on the order as `total_qty`. */
export const baseUnitCount = computed(() =>
  rawLines.value.reduce((sum, line) => sum + line.qty, 0)
)

export const isEmpty = computed(() => rawLines.value.length === 0)

/**
 * The four figures, in paise and as strings ready for a `tnum` column.
 *
 * `net` is what the shop pays. `incentive` is the rep's own money and is deliberately not folded
 * into the discount - telling a shopkeeper they were given the rep's incentive is the kind of
 * number that turns into an argument at month-end.
 */
export const totals = computed(() => {
  const p = pricing.value
  // The distributor's tax on the distributor's sale, so that the figure the rep reads out is the
  // one the shop will be billed. FieldMate posts none of it - see `lib/tax.js`, which is this
  // rule's other copy and the server's.
  const rates = {}
  for (const line of rawLines.value) if (line.tax_bps) rates[line.item_code] = line.tax_bps
  const taxed = taxFor(p.lines || rawLines.value, rates, p.discount_paise)
  const grand = p.net_paise + taxed.tax_paise

  return {
    gross_paise: p.cart_gross_paise,
    discount_paise: p.discount_paise,
    net_paise: p.net_paise,
    incentive_paise: p.incentive_paise,
    tax_paise: taxed.tax_paise,
    grand_paise: grand,
    gross: formatPaise(p.cart_gross_paise),
    discount: formatPaise(p.discount_paise),
    net: formatPaise(p.net_paise),
    incentive: formatPaise(p.incentive_paise),
    tax: formatPaise(taxed.tax_paise),
    grand: formatPaise(grand),
    currency: catalogue.value?.currency || null,
    // The engine's own complaints, e.g. a discount larger than the cart. Never hidden.
    errors: p.errors || [],
  }
})

const specIndex = computed(() => new Map((specs.value || []).map((s) => [s.scheme, s])))

const catalogueIndex = computed(
  () => new Map((catalogue.value?.items || []).map((i) => [i.item_code, i]))
)

/**
 * The schemes that fired, in the engine's order, with the words a rep needs beside the money.
 *
 * "Why did I get this discount" is the single most common field support call, so `rep_pitch` from
 * the compiled spec travels all the way to the screen rather than leaving it to render an amount
 * with no explanation attached.
 */
export const appliedSchemes = computed(() =>
  (pricing.value.applied || []).map((entry) => {
    const spec = specIndex.value.get(entry.scheme)
    return {
      ...entry,
      rep_pitch: spec?.rep_pitch || null,
      basis: spec?.basis || null,
      stacking: spec?.stacking || null,
      benefit: formatPaise(entry.benefit_paise),
      benefits: (entry.benefits || []).map((b) => ({ ...b, amount: formatPaise(b.amount_paise) })),
    }
  })
)

/** Free stock this cart has earned, named and valued. Billed at zero, listed as its own lines. */
export const freeGoods = computed(() =>
  (pricing.value.free_goods || []).map((row) => {
    const item = catalogueIndex.value.get(row.item)
    const spec = specIndex.value.get(row.scheme)
    return {
      ...row,
      item_code: row.item,
      item_name: item?.item_name || row.item,
      uom: item?.stock_uom || null,
      scheme_name: spec?.scheme_name || null,
      value: formatPaise(row.value_paise),
    }
  })
)

/**
 * The nudge: "one more case unlocks Tier 3".
 *
 * The engine returns a bare `gap` whose unit depends on the scheme's basis - base units on a Qty
 * scheme, paise on a Value one. Splitting them here means no screen has to remember that, and a
 * paise gap can never be rendered as a piece count.
 */
export const nearMisses = computed(() =>
  (pricing.value.near_misses || []).map((entry) => {
    const spec = specIndex.value.get(entry.scheme)
    const byValue = entry.basis === 'Value'
    return {
      ...entry,
      rep_pitch: spec?.rep_pitch || null,
      gap_units: byValue ? null : entry.gap,
      gap_paise: byValue ? entry.gap : null,
      gap_display: byValue ? formatPaise(entry.gap) : String(entry.gap),
    }
  })
)

/** Schemes the engine took away, and why. Shown, never swallowed. */
export const droppedSchemes = computed(() => pricing.value.dropped || [])

/**
 * How old the two caches are. The screen shows this; it does not decide anything.
 *
 * A scheme edited in Desk does not reach a rep until the next pull, which is correct - the rep
 * quoted what they were holding - but it has to be visible rather than silent (ADR-021).
 */
export const dataAge = computed(() => {
  const now = Date.now()
  const age = (at) => (at ? now - at : null)
  return {
    catalogue: {
      fetchedAt: catalogueFetchedAt.value,
      ageMs: age(catalogueFetchedAt.value),
      stale: catalogueFetchedAt.value ? now - catalogueFetchedAt.value > STALE_AFTER_MS : true,
    },
    schemes: {
      fetchedAt: specsFetchedAt.value,
      ageMs: age(specsFetchedAt.value),
      compiledOn: specsCompiledOn.value,
      stale: specsFetchedAt.value ? now - specsFetchedAt.value > STALE_AFTER_MS : true,
    },
  }
})

/**
 * Everything standing between this cart and a submit, each with a sentence and the items at fault.
 *
 * A blocker is a hard stop the rep can fix at the counter, not a policy judgement. Credit, approval
 * ceilings and discount limits are deliberately absent: those are recorded, flagged and routed on
 * the server, because a rep blocked in front of a shopkeeper does not book a smaller order - he
 * stops using the app, and then there is no data at all.
 */
export const blockers = computed(() => {
  const out = []
  if (!rawLines.value.length) {
    out.push({ code: 'EMPTY', message: 'Nothing in this order yet. Add an item to start.', items: [] })
  }

  const unpriced = rawLines.value.filter((l) => l.unpriceable || l.rate_paise === null)
  if (unpriced.length) {
    out.push({
      code: 'UNPRICEABLE',
      message:
        'These have no price yet, so the order cannot be totalled. Take them off, or ask your ' +
        'manager to have them priced.',
      items: unpriced.map((l) => l.item_code),
    })
  }

  // A line can reach this state without ever being added through addLine: a re-price against a
  // list somebody changed mid-day turns a good line into this one.
  const overMrp = rawLines.value.filter((l) => l.above_mrp)
  if (overMrp.length) {
    out.push({
      code: 'ABOVE_MRP',
      message:
        'These are priced above the MRP printed on the pack, so the order cannot be sent. ' +
        'Ask your manager to correct the price list.',
      items: overMrp.map((l) => l.item_code),
    })
  }

  const below = rawLines.value.filter(
    (l) => l.min_order_qty && l.qty / (l.conversion_factor || 1) < l.min_order_qty
  )
  if (below.length) {
    out.push({
      code: 'BELOW_MIN',
      message: 'These are under the smallest quantity this shop can order.',
      items: below.map((l) => l.item_code),
    })
  }

  const above = rawLines.value.filter(
    (l) => l.max_order_qty && l.qty / (l.conversion_factor || 1) > l.max_order_qty
  )
  if (above.length) {
    out.push({
      code: 'ABOVE_MAX',
      message: 'These are over the most this shop can order at once.',
      items: above.map((l) => l.item_code),
    })
  }

  return out
})

/**
 * The catalogue as the browse screen wants it: every sellable line, priced in paise once.
 *
 * Deliberately independent of the cart. A shop's range runs to four hundred SKUs and this list has
 * a 400 ms render budget, so it must not be rebuilt every time a quantity changes - which is what
 * folding the cart into it would do, once per tap, on a four-year-old Android. What is in the cart
 * is a separate, tiny lookup below.
 */
export const catalogueItems = computed(() =>
  (catalogue.value?.items || []).map((item) => {
    const rate_paise = item.unpriceable ? null : toPaise(item.rate)
    const factor = Number(item.conversion_factor) || 1
    return {
      ...item,
      rate_paise,
      rate: rate_paise === null ? null : formatPaise(rate_paise),
      order_uom_rate_paise: rate_paise === null ? null : rate_paise * factor,
      order_uom_rate_display: rate_paise === null ? null : formatPaise(rate_paise * factor),
    }
  })
)

/**
 * What is in the cart, by item code, for a catalogue row to show its own quantity badge.
 *
 * A Map of the handful of lines the rep has picked rather than a flag on all four hundred rows:
 * a tap re-prices this and nothing else, so the long list keeps its DOM.
 */
export const cartQty = computed(
  () => new Map(rawLines.value.map((line) => [line.item_code, decorate(line)]))
)

/** The previous order at this shop, for the repeat-order prefill. */
export const lastOrder = computed(() => catalogue.value?.last_order || null)

// -------------------------------------------------------------------------------------- season

/**
 * The season this cart books into, or `null` for an ordinary order.
 *
 * The server's answer, carried whole and never re-derived. Which season an order books into is a
 * question about its date against a company's open window (`services/season.open_for`), and a
 * handset that worked it out from a price list name would be a second implementation of the one
 * rule Phase 2 is built on.
 */
export const season = computed(() => catalogue.value?.season || null)

/** Secondary, Primary or Booking, as the channel resolved it for this party today. */
export const orderKind = computed(() => catalogue.value?.order_kind || null)

/**
 * Which of our own branches may make this sale, and which one usually does.
 *
 * ERPNext calls it an Accounting Dimension; a site that has enabled one makes it mandatory on the
 * Sales Order and on everything built from it, and nothing fills it server-side - the default is
 * applied in the Desk form and nowhere else. So the rep is asked, and the party's usual branch is
 * what they are offered.
 *
 * An **empty list is the instruction not to ask**. Most sites have no Locations at all, and a
 * picker over nothing is a question with no answer.
 */
export const locations = computed(() => catalogue.value?.locations || [])
export const defaultLocation = computed(() => catalogue.value?.location || null)

export const isBookingCart = computed(() => isBooking(orderKind.value))

/**
 * What this cart would need up front if it were booked now, in paise.
 *
 * Nothing has arrived yet - there is no order for money to be allocated to - so this is the
 * requirement alone, which is the figure the rep has to say out loud before the party agrees to
 * anything. The arrived side appears once the booking exists, on the booking list and on the
 * confirmation screen, both of which read the server's own count.
 */
export const advanceOnCart = computed(() =>
  advanceView({ netPaise: totals.value.net_paise, season: season.value })
)

// ------------------------------------------------------------------------------------- pricing

/**
 * Specs that are still live today, by the phone's own clock.
 *
 * The engine never reads a clock - that is ADR-021 and it is what makes parity provable - so the
 * filtering happens out here, on the way in. It matters for a phone that has not synced for three
 * days: without it the rep is quoting an offer that ended on Sunday, and the server will refuse it.
 */
/**
 * Which offers this phone still honours today.
 *
 * Exported for its own test. It is one half of a rule the server also enforces - `for_outlet`
 * filters on the same four dates - and the two drifting apart is the whole class of bug this
 * app keeps finding in the field. A rule written twice gets tested twice.
 */
export function liveSpecs(all, on = todayStamp()) {
  return (all || []).filter((spec) => {
    if (spec.valid_from && String(spec.valid_from) > on) return false
    if (spec.valid_to && String(spec.valid_to) < on) return false
    // The early-booking window, which is a different question: `valid_*` is when the offer
    // exists, these are when the order has to be taken to earn it. A season scheme is live
    // from November to March because that is when it is billed, and rewards November's orders.
    // The server filters on them too; this is so a phone three days behind on its sync retires
    // the offer itself rather than quoting one whose book shut on Sunday.
    if (spec.booking_from && String(spec.booking_from) > on) return false
    if (spec.booking_to && String(spec.booking_to) < on) return false
    return true
  })
}

/**
 * Re-price the cart. Synchronous, local, and the hot path of the whole phase.
 *
 * No await, no fetch, no Dexie read. Called on every quantity change, so anything slow put in here
 * is felt as a laggy keypad by a rep standing in front of a shopkeeper.
 */
export function reprice() {
  const cartLines = []
  let idx = 0
  for (const line of rawLines.value) {
    // An unpriceable line is left out of the arithmetic rather than priced at zero. Zero would book
    // a pallet of soap for nothing and nobody would find out until the distributor read his own
    // invoice weeks later. `blockers` is what tells the rep about it.
    if (line.unpriceable || line.rate_paise === null) continue
    if (line.qty <= 0) continue
    idx += 1
    cartLines.push({ idx, item: line.item_code, qty: line.qty, rate_paise: line.rate_paise })
  }

  pricing.value = evaluate(
    { outlet: outlet.value, lines: cartLines },
    liveSpecs(specs.value)
  )
  return pricing.value
}

// ------------------------------------------------------------------------------- opening a cart

/**
 * Open the order screens for a shop: the saved cart, the catalogue, the specs, and a first price.
 *
 * Cache first, always. Both reads fall back to whatever this phone already holds, because a screen
 * that awaits the network cannot work in a basement market - and the cart it would have refused to
 * open is the order the rep then writes in a notebook.
 */
/** What is in this shop's cart, read straight from the phone.
 *
 * The visit hub needs a line count and a value to put on its Order card, and it must not pay for
 * that with a catalogue fetch and a scheme compile - the rep is standing in the shop and the hub
 * has to paint immediately. No network, no state change, safe to call from anywhere.
 */
export async function peek(outletName) {
  if (!outletName) return { lines: 0, units: 0 }
  try {
    const cached = await db.carts.get(outletName)
    const rows = cached?.lines || []
    return {
      lines: rows.length,
      units: rows.reduce((total, row) => total + (Number(row.qty) || 0), 0),
    }
  } catch {
    // A cart we cannot read is a cart we report as empty. The hub still has to render.
    return { lines: 0, units: 0 }
  }
}

export async function openOutlet(name, { refresh = true, type = null } = {}) {
  const token = ++loadToken

  // Everything held for the previous shop goes before the new one is named. Leaving it in place
  // was a way for a rep with no signal to walk into the next shop, find nothing cached for it, and
  // be shown the last shop's items at the last shop's prices - which looks entirely normal.
  if (outlet.value !== name || partyType.value !== type) {
    catalogue.value = null
    catalogueFetchedAt.value = null
    specs.value = []
    skippedSchemes.value = []
    specsFetchedAt.value = null
    specsCompiledOn.value = null
    pricing.value = emptyPricing()
    rawLines.value = []
    outletName.value = null
  }

  outlet.value = name
  partyType.value = type
  loading.value = true
  error.value = null

  try {
    const cached = await db.carts.get(name)
    if (token !== loadToken) return null
    rawLines.value = cached?.lines || []
    outletName.value = cached?.outletName || null
    // The identity comes back with the lines. A rep who closed the app mid-send and reopened it
    // must resend as the same order, not a second one.
    cartUuid.value = cached?.clientUuid || null
    // The cart remembers what kind of party it was for, and that wins when the caller does not
    // say. A rep reopening an unsent cart from a link with no type on it would otherwise have a
    // primary order re-priced as a shop order - off a different list, against a different credit
    // limit - with nothing on the screen to show it had changed.
    if (!type && cached?.party_type) partyType.value = cached.party_type

    await Promise.all([
      loadCatalogue(name, { refresh, token }),
      loadSchemes(name, { refresh, token }),
    ])
    if (token !== loadToken) return null

    outletName.value = catalogue.value?.outlet_name || outletName.value || name
    reconcileWithCatalogue()
    reprice()
    return { lines: lines.value, totals: totals.value }
  } finally {
    if (token === loadToken) loading.value = false
  }
}

/**
 * A cart built yesterday against a catalogue that has since changed is the quiet failure worth
 * guarding: an item pulled from the range, or repriced, would otherwise sit in the cart at the old
 * rate and be read out to a shopkeeper. Where the catalogue has an opinion, it wins; where the phone
 * has no catalogue at all, the cart is left exactly as the rep built it rather than emptied.
 */
function reconcileWithCatalogue() {
  const index = catalogueIndex.value
  if (!index.size) return

  for (const line of rawLines.value) {
    const item = index.get(line.item_code)
    if (!item) {
      // Still shown, still removable, but it cannot be priced and `blockers` will say so.
      line.unpriceable = true
      line.rate_paise = null
      line.off_catalogue = true
      continue
    }
    line.off_catalogue = false
    line.unpriceable = !!item.unpriceable
    line.rate_paise = item.unpriceable ? null : toPaise(item.rate)
    // Re-read, not carried over: a price list corrected during the day clears this, and one
    // changed the wrong way sets it on a line that was fine when the rep added it.
    line.above_mrp = !!item.above_mrp
    line.mrp = item.mrp ?? null
    line.tax_bps = Math.trunc(item.tax_bps || 0)
    line.item_name = item.item_name || line.item_name
    line.min_order_qty = item.min_order_qty ?? null
    line.max_order_qty = item.max_order_qty ?? null
  }
}

async function loadCatalogue(name, { refresh = true, token = null } = {}) {
  const cached = await db.catalogues.get(name)
  if (token !== null && token !== loadToken) return
  // Set from the cache or cleared, never left as it was: an `else` missing here is how the shop
  // the rep just walked out of stays on the screen of the shop they walked into.
  if (cached) {
    catalogue.value = cached.payload
    catalogueFetchedAt.value = cached.fetchedAt
  } else {
    catalogue.value = null
    catalogueFetchedAt.value = null
  }
  if (!refresh && cached) return

  try {
    const payload = await api.catalogue(name, partyType.value)
    if (token !== null && token !== loadToken) return
    catalogue.value = payload
    catalogueFetchedAt.value = Date.now()
    await db.catalogues.put(plain({ outlet: name, party_type: partyType.value, payload,
                                    fetchedAt: catalogueFetchedAt.value }))
  } catch (e) {
    if (!cached) {
      // Nothing cached and nothing fetched: the screen has to say why it is empty rather than draw
      // an empty list and let the rep conclude the shop sells nothing.
      error.value = isOffline(e)
        ? 'This shop\'s item list has not reached this phone yet. Connect once and it will be here for good.'
        : (e instanceof ApiError ? e.message : 'Could not load this shop\'s items.')
    }
  }
}

async function loadSchemes(name, { refresh = true, token = null } = {}) {
  const cached = await db.schemeSpecs.get(name)
  if (token !== null && token !== loadToken) return
  if (cached) {
    specs.value = cached.specs || []
    skippedSchemes.value = cached.skipped || []
    specsFetchedAt.value = cached.fetchedAt
    specsCompiledOn.value = cached.compiledOn || null
  } else {
    specs.value = []
    skippedSchemes.value = []
    specsFetchedAt.value = null
    specsCompiledOn.value = null
  }
  if (!refresh && cached) return

  try {
    const payload = await api.schemesFor(name, partyType.value)
    if (token !== null && token !== loadToken) return
    specs.value = payload.specs || []
    skippedSchemes.value = payload.skipped || []
    specsFetchedAt.value = Date.now()
    specsCompiledOn.value = payload.compiled_on || null
    await db.schemeSpecs.put(
      plain({
        outlet: name,
        specs: specs.value,
        skipped: skippedSchemes.value,
        compiledOn: specsCompiledOn.value,
        asOf: payload.as_of || null,
        priceList: payload.price_list || null,
        fetchedAt: specsFetchedAt.value,
      })
    )
  } catch {
    // An offer list we could not refresh is not an error the rep has to read. The cached specs
    // still price the cart, and `dataAge` is where the screen says how old they are.
  }
}

/** Pull both caches again for the open shop. What the "Refresh" affordance calls. */
export async function refreshAll() {
  const name = outlet.value
  if (!name) return
  const token = loadToken
  await Promise.all([
    loadCatalogue(name, { refresh: true, token }),
    loadSchemes(name, { refresh: true, token }),
  ])
  if (token !== loadToken) return
  reconcileWithCatalogue()
  reprice()
}

// ---------------------------------------------------------------------------------- the basket

/**
 * This cart's identity, which is the order's identity.
 *
 * **Minted once per cart and kept until the cart is gone, never per attempt.** A fresh id on a
 * retry is how one order becomes two: the first send reaches the server on a market uplink, the
 * answer does not, the rep taps again, and the server - which dedupes on exactly this id - sees a
 * second order it has never heard of. Two FieldMate Orders, two Sales Orders, two commitments.
 *
 * It is written into the cart record, so it survives the screen being closed, the app being
 * killed and the phone being restarted. `clear()` drops it with the lines, because the next cart
 * at the same shop is a different order.
 *
 * `Money.vue` has done this since it was written, and says why in a comment about collecting a
 * depot's money twice. The order path did the opposite.
 */
const cartUuid = ref(null)

async function orderIdentity() {
  if (!cartUuid.value) {
    cartUuid.value = crypto.randomUUID()
    await persist()
  }
  return cartUuid.value
}

async function persist() {
  if (!outlet.value) return
  // A cart with lines in it has an identity, from the moment it has them. Minting at send time
  // instead would leave the one case this exists for uncovered: an app killed between the request
  // going out and its answer coming back must resend as the same order, and by then there is no
  // code running to mint anything.
  if (!cartUuid.value && rawLines.value.length) cartUuid.value = crypto.randomUUID()
  await db.carts.put(
    plain({
      outlet: outlet.value,
      party_type: partyType.value,
      outletName: outletName.value,
      lines: rawLines.value,
      clientUuid: cartUuid.value,
      updatedAt: Date.now(),
    })
  )
}

export function lineFor(itemCode) {
  const line = rawLines.value.find((l) => l.item_code === itemCode)
  return line ? decorate(line) : null
}

/**
 * Put an item in the cart.
 *
 * `unit` is `'display'` by default - the unit the rep is actually typing in, usually cases - and
 * `'base'` for a caller that already holds pieces, like the repeat-order prefill.
 *
 * On an item already in the cart a quantity *sets* the line, and no quantity adds one more of
 * whatever the rep is ordering in. Tapping Add against a soap already in the basket has to mean one
 * more case, not one more piece out of a case.
 */
export async function addItem(itemCode, { qty = null, unit = 'display' } = {}) {
  if (!outlet.value) throw new CartError('NO_OUTLET', 'Open a shop before adding items.')

  const existing = rawLines.value.find((l) => l.item_code === itemCode)
  if (existing) {
    if (qty === null) return bumpQty(itemCode, 1, { unit: 'display' })
    return setQty(itemCode, qty, { unit })
  }

  const item = catalogueIndex.value.get(itemCode)
  if (!item) {
    throw new CartError('NOT_IN_CATALOGUE', 'That item is not on this shop\'s list.')
  }
  if (item.unpriceable) {
    // Refused rather than added at zero. An item nobody has priced has no safe number to stand in
    // for it: zero books it free, and a guess is a guess the rep has already read out.
    throw new CartError(
      'UNPRICEABLE',
      `${item.item_name || itemCode} has no price yet, so it cannot be ordered. Ask your manager to have it priced.`
    )
  }
  if (item.above_mrp) {
    // Refused at the tap, not at submit. The shopkeeper is standing there, and this is not
    // something the rep can fix or decide to accept - the printed price is on the pack in his
    // hand, and selling over it is an offence.
    throw new CartError(
      'ABOVE_MRP',
      `${item.item_name || itemCode} is priced above its MRP, so it cannot be ordered. Ask your manager to correct the price list.`
    )
  }

  const line = newLine(item)
  // A shop with a minimum order starts there rather than at one, so the first tap is already a
  // quantity the order will accept.
  const opening = qty === null ? item.min_order_qty || 1 : qty
  line.qty = unit === 'base' ? Math.max(0, Math.trunc(Number(opening) || 0))
                             : toBaseQty(opening, line.conversion_factor)
  if (line.qty <= 0) return null

  rawLines.value.push(line)
  reprice()
  await persist()
  return decorate(line)
}

/**
 * Set a line's quantity. The one way a quantity ever changes.
 *
 * Anything at or below zero removes the line, which is what a rep clearing the box means and what
 * the engine would do with it anyway.
 */
export async function setQty(itemCode, value, { unit = 'display' } = {}) {
  const line = rawLines.value.find((l) => l.item_code === itemCode)
  if (!line) return addItem(itemCode, { qty: value, unit })

  const base =
    unit === 'base' ? Math.trunc(Number(value) || 0) : toBaseQty(value, line.conversion_factor)
  if (base <= 0) return removeItem(itemCode)

  line.qty = base
  reprice()
  await persist()
  return decorate(line)
}

/** The + and - steppers. A tap adds one of whatever the rep is ordering in, usually a case. */
export async function bumpQty(itemCode, delta, { unit = 'display' } = {}) {
  const line = rawLines.value.find((l) => l.item_code === itemCode)
  if (!line) {
    return delta > 0 ? addItem(itemCode, { qty: delta, unit }) : null
  }
  const step = unit === 'base' ? Math.trunc(Number(delta) || 0)
                               : toBaseQty(delta, line.conversion_factor)
  return setQty(itemCode, line.qty + step, { unit: 'base' })
}

export async function removeItem(itemCode) {
  const at = rawLines.value.findIndex((l) => l.item_code === itemCode)
  if (at === -1) return null
  rawLines.value.splice(at, 1)
  reprice()
  await persist()
  return null
}

/** Empty the cart for the open shop and forget it on disk. */
export async function clear() {
  rawLines.value = []
  pricing.value = emptyPricing()
  // The next cart at this shop is a different order, so it gets a different identity.
  cartUuid.value = null
  if (outlet.value) await db.carts.delete(outlet.value)
}

/**
 * The repeat order: last time's lines, with quantities already in.
 *
 * DESIGN.md asks for two taps rather than forty, and this is the half of it the phone owes. The
 * server sends base-unit quantities on purpose, so nothing has to be reconverted here and a shop
 * that ordered "1 Case and 6 Nos" of the same soap comes back as one line of the right size.
 *
 * Free goods are already absent from the payload - they were granted by a scheme, not asked for,
 * and prefilling them would have the rep re-ordering what the last scheme gave away and paying for
 * it this time.
 */
export async function prefillFromLastOrder({ replace = false } = {}) {
  if (!outlet.value) throw new CartError('NO_OUTLET', 'Open a shop first.')

  let history = lastOrder.value
  if (!history) {
    try {
      history = await api.catalogueLastOrder(outlet.value, partyType.value)
    } catch {
      history = null
    }
  }

  const rows = Object.entries(history?.items || {})
  if (!rows.length) {
    return { filled: 0, skipped: [], order: null, order_date: null, had_history: false }
  }

  if (replace) {
    rawLines.value = []
  }

  const held = new Set(rawLines.value.map((l) => l.item_code))
  const skipped = []
  let filled = 0

  for (const [itemCode, row] of rows) {
    // Already in the cart: the rep's own number wins over last month's.
    if (held.has(itemCode)) continue

    const item = catalogueIndex.value.get(itemCode)
    // An item that has left the range, or that nobody has priced since, is named rather than
    // dropped in silence - the rep is the last person who should discover a gap in their own
    // repeat order at the counter.
    if (!item || item.unpriceable) {
      skipped.push({ item_code: itemCode, reason: item ? 'UNPRICEABLE' : 'NOT_IN_CATALOGUE' })
      continue
    }

    const base = Math.trunc(Number(row.last_ordered_base_qty) || 0)
    // Ordered at zero last time is real history - the shopkeeper looked at it and waved it away -
    // but it is not a quantity to prefill.
    if (base <= 0) continue

    const line = newLine(item)
    line.qty = base
    line.has_order_history = true
    line.last_ordered_qty = row.last_ordered_qty ?? null
    line.last_ordered_on = row.last_ordered_on || history.order_date || null
    rawLines.value.push(line)
    filled += 1
  }

  reprice()
  await persist()
  return {
    filled,
    skipped,
    order: history.order || null,
    order_date: history.order_date || null,
    had_history: true,
  }
}

// --------------------------------------------------------------------------- the server's figure

/**
 * Ask the server what this cart comes to, and say whether it agrees with us.
 *
 * Advisory in the sense that matters: the rep has already said a number out loud, and this is how
 * they find out before the shopkeeper does if it was wrong. Where the two differ the server stands,
 * because it priced against the live price list rather than a cache.
 */
export async function verifyWithServer() {
  if (!outlet.value || isEmpty.value) return { checked: false, reason: 'EMPTY' }

  const payload = rawLines.value
    .filter((l) => !l.unpriceable && l.rate_paise !== null && l.qty > 0)
    .map((l) => ({ item_code: l.item_code, qty: l.qty, uom: l.base_uom }))

  try {
    const server = await api.schemeEvaluate(outlet.value, payload, partyType.value)
    const local = pricing.value
    const localTotals = totals.value
    const delta = (server.net_paise ?? 0) - local.net_paise
    // Tax as well as net. The two sides run the same arithmetic, so a difference here is a
    // difference in the *rates* - a tax template changed today against a catalogue cached
    // yesterday - and it lands on the bill the shop receives just as surely as a wrong price.
    const taxDelta = (server.tax_paise ?? 0) - localTotals.tax_paise
    return {
      checked: true,
      matched: delta === 0 && taxDelta === 0,
      delta_paise: delta,
      tax_delta_paise: taxDelta,
      server,
      local: {
        cart_gross_paise: local.cart_gross_paise,
        discount_paise: local.discount_paise,
        net_paise: local.net_paise,
        incentive_paise: local.incentive_paise,
        tax_paise: localTotals.tax_paise,
      },
    }
  } catch (e) {
    if (isOffline(e)) return { checked: false, offline: true }
    throw e
  }
}

// ---------------------------------------------------------------------------------- the payload

/**
 * The order as a FieldMate Order document.
 *
 * One builder for both routes on purpose. The online submit posts this and the offline queue holds
 * this, so there is exactly one shape to get wrong rather than two that drift apart over a phase -
 * which is also why it uses DocType field names and rupees rather than the store's own vocabulary.
 *
 * Every total on it is a proposal. The server recomputes the figures from its own engine and its
 * own prices and overwrites them; `proposed_net_total` is the exception and is deliberately not
 * server-owned (see the sync registry), because it is the phone's statement of the number the rep
 * said across a counter and there is nothing left to compare against if it is rewritten.
 */
export function buildOrderDoc({
  paymentTerm = 'Credit',
  creditDays = null,
  expectedDeliveryDate = null,
  deliveryInstructions = null,
  confirmedWith = null,
  remarks = null,
  visit = null,
  deliveryDates = null,
  topsUp = null,
  location = null,
  clientUuid = null,
  createdOffline = 0,
  deviceId = null,
} = {}) {
  const p = pricing.value
  const cat = catalogue.value || {}

  return {
    docstatus: 1,
    client_uuid: clientUuid,
    order_date: todayStamp(),
    // A shop or a party we bill. The server infers the type when it is absent, so an older
    // build of this app that sends only an outlet goes on working.
    party_type: partyType.value || 'Outlet',
    outlet: partyType.value === 'Customer' ? null : outlet.value,
    customer: partyType.value === 'Customer' ? outlet.value : null,
    visit: visit || null,

    price_list: cat.price_list || null,
    currency: cat.currency || null,

    payment_term: paymentTerm,
    credit_days: creditDays,
    expected_delivery_date: expectedDeliveryDate,
    delivery_instructions: deliveryInstructions,
    confirmed_with: confirmedWith,
    remarks,

    // The booking this one adds to, when the rep said so. The server checks it is the same party
    // and the same season; this only carries the answer.
    tops_up: topsUp,

    // Which branch of ours is selling. `undefined` rather than null on a shop order, so nothing
    // about branches appears in a secondary order's payload at all - that sale is the
    // distributor's and no branch of ours is in it.
    location: location || undefined,

    // The number the rep read out. Rupees, because every Currency column downstream is rupees.
    proposed_net_total: fromPaise(p.net_paise),

    items: rawLines.value
      .filter((l) => l.qty > 0 && !l.unpriceable && l.rate_paise !== null)
      .map((line) => {
        const view = decorate(line)
        return {
          item_code: line.item_code,
          item_name: line.item_name,
          item_group: line.item_group,
          brand: line.brand,

          qty_display: view.display_qty,
          display_uom: line.display_uom,
          uom: line.display_uom,
          conversion_factor: line.conversion_factor,
          qty: line.qty,
          stock_uom: line.base_uom,

          price_list_rate: fromPaise(view.display_rate_paise),
          rate: fromPaise(view.display_rate_paise),
          gross_amount: fromPaise(view.gross_paise),
          is_free_item: 0,

          // When this line is wanted. Only a booking fills it in - the whole point of booking a
          // season is that different lines land in different weeks - and the server refuses a
          // date outside the season's delivery window. `undefined` rather than `null` for an
          // ordinary order, so nothing about dates appears in a shop order's payload at all.
          delivery_date: (deliveryDates && deliveryDates[line.item_code]) || undefined,

          has_order_history: line.has_order_history ? 1 : 0,
          last_ordered_qty: line.last_ordered_qty,
          last_ordered_on: line.last_ordered_on,
          notes: line.notes,
        }
      }),

    // What the phone believes the schemes did. The server recomputes all of it; sending it is what
    // makes a divergence visible instead of invisible.
    schemes_applied: (p.applied || []).flatMap((entry) =>
      (entry.benefits || []).map((benefit) => ({
        scheme: entry.scheme,
        scheme_name: entry.scheme_name,
        slab_idx: entry.slab_idx,
        benefit_kind: benefit.kind,
        benefit_description: specIndex.value.get(entry.scheme)?.rep_pitch || null,
        qualifying_amount: fromPaise(p.cart_gross_paise),
        benefit_amount: fromPaise(benefit.amount_paise),
        free_qty: benefit.qty || 0,
        budget_warning: entry.budget_warning ? 1 : 0,
      }))
    ),

    free_goods: (p.free_goods || []).map((row) => ({
      item_code: row.item,
      item_name: catalogueIndex.value.get(row.item)?.item_name || row.item,
      qty: row.qty,
      uom: catalogueIndex.value.get(row.item)?.stock_uom || null,
      scheme: row.scheme,
      valuation_amount: fromPaise(row.value_paise),
    })),

    created_offline: createdOffline,
    device_id: deviceId,
  }
}

/** What the review screen asks for when there is signal: the server's arithmetic, nothing booked. */
export async function estimate(options = {}) {
  if (isEmpty.value) return { checked: false, reason: 'EMPTY' }
  try {
    return { checked: true, ...(await api.orderEstimate(buildOrderDoc(options))) }
  } catch (e) {
    if (isOffline(e)) return { checked: false, offline: true }
    throw e
  }
}

/**
 * Book the order.
 *
 * The same shape as `day.start`, for the same reason: post it if the link is there, queue it if it
 * is not, and either way the rep walks out of the shop with the order recorded. An order that only
 * lives on the server is an order that vanishes when the lift doors close.
 *
 * `docstatus: 1` on the queued record asks the server to submit it, because a draft order is an
 * order the distributor never sees - and submitting is the whole event here. No Sales Order, no
 * invoice, no stock movement, no GL Entry: a shop order is a secondary sale and is terminal in our
 * books (ADR-023).
 *
 * The order is queued behind the visit it was taken during, so an offline day lands in the order it
 * happened rather than as an order against a visit the server has never heard of.
 */
export async function submit(options = {}) {
  if (!outlet.value) throw new CartError('NO_OUTLET', 'Open a shop first.')
  if (isEmpty.value) throw new CartError('EMPTY', 'There is nothing in this order yet.')

  const stopper = blockers.value.find((b) => b.code !== 'EMPTY')
  if (stopper) throw new CartError(stopper.code, stopper.message)

  const device = await deviceUuid()
  // The cart's own id, not a new one for this attempt. See `orderIdentity`.
  const clientUuid = await orderIdentity()

  // The visit this order came out of. Its server name once it has one, its client id while it has
  // not - `sync._apply` resolves the second through `depends_on` when the batch lands.
  const openVisit = visitStore.activeVisit.value
  const visitRef = options.visit || openVisit?.serverName || openVisit?.clientUuid || null
  const dependsOn = openVisit && !openVisit.serverName ? openVisit.clientUuid : null

  const doc = buildOrderDoc({ ...options, visit: visitRef, clientUuid, deviceId: device })

  const net = totals.value.net_paise

  try {
    const data = await api.orderSubmit(device, doc)
    await rememberName(clientUuid, 'FieldMate Order', data.order)
    await visitStore.recordOrder({ clientUuid, name: data.order, net, offline: false })
    await clear()
    return { order: data.order, client_uuid: clientUuid, offline: false, queued: false, server: data }
  } catch (e) {
    // Only a dead link falls through to the queue, exactly as day start does. A validation failure
    // is the rep's to fix now and the cart is still on the screen to fix it with; queueing it would
    // send the same rejection round the outbox six times and then block it.
    if (!isOffline(e)) throw e
  }

  await enqueue(
    'FieldMate Order',
    { ...doc, created_offline: 1 },
    { clientUuid, dependsOn }
  )
  await visitStore.recordOrder({ clientUuid, name: null, net, offline: true })
  await clear()
  return { order: clientUuid, client_uuid: clientUuid, offline: true, queued: true }
}

// ------------------------------------------------------------------------------------- history

/**
 * The rep's recent orders, with anything still in the outbox shown first.
 *
 * A queued order that did not appear in the list is the single most alarming thing this app could
 * do to a rep: they booked it, they told the shopkeeper, and the app shows no trace of it. So the
 * outbox is read locally and merged in whether or not the network answers.
 */
export async function recentOrders(filters = {}) {
  const queued = (await db.outbox.where('doctype').equals('FieldMate Order').toArray()).map(
    (row) => ({
      name: row.clientUuid,
      client_uuid: row.clientUuid,
      outlet: row.data?.outlet || null,
      order_date: row.data?.order_date || null,
      // The net, and only the net: `proposed_net_total` is the goods figure the rep read out and
      // the order document carries no tax of its own. The list falls back to it until the server
      // answers with the bill total, and the row is marked `pending` beside it.
      net_total: row.data?.proposed_net_total ?? null,
      grand_total: null,
      customer: row.data?.customer || null,
      party_type: row.data?.party_type || null,
      order_status: 'Draft',
      pending: true,
      blocked: row.state === 'blocked',
      last_error: row.lastError || null,
    })
  )

  try {
    const data = await api.orderList(filters)
    await setMeta('recentOrders', data.orders || [])
    return { orders: [...queued, ...(data.orders || [])], offline: false }
  } catch (e) {
    if (!isOffline(e)) throw e
    const cached = (await getMeta('recentOrders', [])) || []
    return { orders: [...queued, ...cached], offline: true }
  }
}

export async function orderDetail(name) {
  return api.orderDetail(name)
}

export async function cancelOrder(name, reason) {
  return api.orderCancel(name, reason)
}
