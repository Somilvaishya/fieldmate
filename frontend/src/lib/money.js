/**
 * Money on its way to a rep's eyes, and back off a numeric keypad.
 *
 * Everything inside the app holds money as **integer paise** (ADR-022, docs/SCHEME_SPEC.md S2).
 * This file is the only place that leaves that world, and it leaves it in exactly two directions:
 * paise out to a string a shopkeeper reads over the rep's shoulder, and a typed figure back in to
 * paise. A float in the cart is a bug; a float here is the boundary the specification allows.
 *
 * Two rules it exists to hold.
 *
 * **The rupee-to-paise conversion must be the server's conversion, character for character.** The
 * specification writes it as `to_paise(rupees) = floor(rupees * 100 + 0.5)` and puts it in the
 * compiler, on the server. But `catalogue.items` hands the phone a price list rate in rupees, so
 * the phone has to do it too before the engine can be handed a cart. Both runtimes perform the
 * same IEEE-754 double multiply and the same floor, so `Math.floor(v * 100 + 0.5)` here is the
 * same integer as `math.floor(flt(v) * 100 + 0.5)` there - which is why the number path below is
 * written as that one expression and nothing cleverer.
 *
 * **Grouping is Indian, not thousands.** 8008.60 is `8,008.60` and 1234567.89 is `12,34,567.89` -
 * last three digits, then pairs. `Intl.NumberFormat('en-IN')` gets this right and is not used: it
 * rounds in its own way, it is a different implementation on every Android WebView in the field,
 * and it costs a locale-data lookup on a screen that re-prices on every quantity tap. The grouping
 * here is string surgery on an integer that has already been rounded exactly once, upstream.
 *
 * Nothing in this file knows about Vue, the store or the network, and nothing may import it into
 * the scheme engine - the engine is handed paise and never formats anything.
 *
 * A currency symbol is deliberately absent from every function. The catalogue payload carries the
 * outlet's own `currency`, and a helper that hard-coded a rupee sign would be wrong the first time
 * this ships anywhere it is not one.
 */

/**
 * Integer coercion, the same rule the engine applies at every boundary.
 *
 * Deliberately not imported from `scheme/engine.js`. That file is a line-for-line mirror of its
 * Python twin under a zero-tolerance parity gate, and a display helper has no business being a
 * reason to open it. Garbage becomes 0 rather than NaN, because a NaN reaches a screen as the
 * literal text "NaN" beside a shopkeeper's total.
 */
function asInt(value) {
  if (value === null || value === undefined || value === '') return 0
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  return Math.trunc(n)
}

/**
 * Digits grouped the Indian way: the last three, then pairs.
 *
 * Takes and returns a bare digit string, so the caller owns the sign and the decimals.
 */
export function groupIndian(digits) {
  if (digits.length <= 3) return digits

  const last3 = digits.slice(-3)
  let head = digits.slice(0, -3)
  const pairs = []
  while (head.length > 2) {
    pairs.unshift(head.slice(-2))
    head = head.slice(0, -2)
  }
  if (head) pairs.unshift(head)
  return `${pairs.join(',')},${last3}`
}

/**
 * Paise to the string that goes on the screen. `800860` renders as `8,008.60`.
 *
 * `decimals: 0` is for KPI tiles and nothing else - it rounds half up on the paise, so a tile
 * reading 8,009 and a total reading 8,008.60 are the same money rather than a contradiction a rep
 * has to explain. Pair every call with the `tnum` class: a figure that changes width as it
 * re-prices is unreadable at arm's length.
 */
export function formatPaise(paise, { decimals = 2, showSign = false } = {}) {
  const value = asInt(paise)
  const negative = value < 0
  const magnitude = Math.abs(value)

  let body
  if (decimals === 0) {
    // floor((2n + d) / 2d) with d = 100 - the specification's own rounding primitive, so a
    // rounded tile never disagrees with the exact total by more than the paise it is hiding.
    body = groupIndian(String(Math.floor((2 * magnitude + 100) / 200)))
  } else {
    const rupees = Math.floor(magnitude / 100)
    const remainder = magnitude % 100
    body = `${groupIndian(String(rupees))}.${String(remainder).padStart(2, '0')}`
  }

  if (negative) return `-${body}`
  return showSign && value > 0 ? `+${body}` : body
}

/**
 * What the rep typed, as paise. Returns `null` for anything that is not a number, so a caller can
 * tell an empty box from a zero - a blank quantity field and a deliberate 0 are different answers.
 *
 * A number takes the specification's own expression, so the phone and the server agree by
 * construction. A string never touches a float at all: it is read digit by digit, which is both
 * exact and immune to a keypad that emits `"1,250.50"` with the grouping still in it.
 */
export function toPaise(value) {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return null
    return Math.floor(value * 100 + 0.5)
  }

  // Strip what a keypad, a paste or our own formatter can put in front of the digits. The rupee
  // sign is here because a rep pasting a figure out of a chat message brings it along; the
  // non-breaking space such a paste also carries is already covered by `\s` in JavaScript.
  const text = String(value).trim().replace(/[\s,₹]/g, '')
  if (!text) return null

  const parts = /^([+-])?(\d*)(?:\.(\d*))?$/.exec(text)
  if (!parts) return null
  const sign = parts[1]
  const whole = parts[2] || ''
  const frac = parts[3] || ''
  if (!whole && !frac) return null

  const digits = frac.padEnd(3, '0')
  const magnitude = Number(whole || '0') * 100 + Number(digits.slice(0, 2))
  const third = Number(digits[2])
  // Anything past the third decimal can only push a half over the line, never pull it back.
  const beyond = digits.slice(3).replace(/0/g, '') !== ''

  if (sign !== '-') {
    // floor(x * 100 + 0.5): a half rounds up.
    return third >= 5 ? magnitude + 1 : magnitude
  }
  // The same floor on a negative rounds a half *towards zero*, because floor(-100.5 + 0.5) is
  // -100. Mirrored rather than simplified: prices are never negative today, and the day one is,
  // this must not be the place the two engines part company.
  const bump = third > 5 || (third === 5 && beyond)
  return -(bump ? magnitude + 1 : magnitude)
}

/**
 * A rupee figure the server already sent us, grouped for display.
 *
 * For the values that never enter the money path at all - a credit limit, an outstanding balance,
 * a target - which arrive as rupees from Frappe Currency columns and are read, never computed on.
 */
export function formatRupees(rupees, options = {}) {
  const paise = toPaise(rupees)
  return paise === null ? '-' : formatPaise(paise, options)
}

/**
 * Paise back to the rupees a Frappe Currency column holds.
 *
 * The mirror of `scheme_compile.in_rupees`, and the only conversion allowed on the way to a
 * payload: every DocType field downstream is rupees because Desk and the people reading it work in
 * rupees (ADR-022), and converting in four places is how three of them round differently.
 */
export function fromPaise(paise) {
  return asInt(paise) / 100
}
