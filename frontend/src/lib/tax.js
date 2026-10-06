/**
 * Tax on the cart — the phone's half of `fieldmate/services/tax.py`.
 *
 * **This file and that one are one rule written twice, and they must change together.** A rep
 * quotes from this copy with no signal; the server re-states the order from the other when the
 * phone finally reaches it, and the two are compared to the paise. Every rule below is the rule
 * there, in the same order, under the same names.
 *
 * Why there is tax here at all, given that a retailer order posts nothing (ADR-023): the cart has
 * exactly one job, stated at the top of `stores/order.js` — the number the rep says out loud has
 * to be the number on the invoice the distributor raises that evening. That invoice carries GST.
 * This is the distributor's tax, computed so the rep does not quote a figure short by all of it,
 * and FieldMate charges none of it.
 *
 * The rate arrives per item as `tax_bps` on the catalogue row (1800 is 18%), already summed from
 * whatever accounts the distributor's tax template names. One effective rate, not a CGST/SGST
 * split: the split depends on two states and belongs on the distributor's own invoice.
 */

import { PERCENT_DENOMINATOR, round_half_up_div } from '../scheme/engine'

/** Tax on one line, in whole paise. Same primitive as every other division in the money path. */
export function onPaise(taxablePaise, bps) {
  if (!taxablePaise || !bps) return 0
  return round_half_up_div(Math.trunc(taxablePaise) * Math.trunc(bps), PERCENT_DENOMINATOR)
}

function grossPaise(line) {
  if (line.gross_paise !== undefined && line.gross_paise !== null) return Math.trunc(line.gross_paise)
  return Math.trunc(line.rate_paise || 0) * Math.trunc(line.qty || 0)
}

/**
 * The cart discount split across lines by gross, to the paise, keyed by index.
 *
 * The engine keeps one cart-level discount rather than marking down each line, so taxing a line's
 * gross would charge tax on money the shop is not paying. With one line at 5% and another at 18%,
 * *which* line the discount lands on changes the total — so the rule is fixed and stated: floor
 * each line's share, then give whatever paise flooring left over to the largest line, ties broken
 * by item code so two carts holding the same lines in a different order cannot disagree.
 */
function apportion(rows, discount, grossTotal) {
  if (discount <= 0 || grossTotal <= 0) return {}

  const shares = {}
  let assigned = 0
  rows.forEach((line, i) => {
    shares[i] = Math.floor((grossPaise(line) * discount) / grossTotal)
    assigned += shares[i]
  })

  const left = discount - assigned
  if (left) {
    let biggest = 0
    rows.forEach((line, i) => {
      const a = [grossPaise(line), String(line.item || line.item_code || '')]
      const b = [grossPaise(rows[biggest]), String(rows[biggest].item || rows[biggest].item_code || '')]
      if (a[0] > b[0] || (a[0] === b[0] && a[1] > b[1])) biggest = i
    })
    shares[biggest] += left
  }
  return shares
}

/**
 * Tax for a priced cart: `{ lines: [...], tax_paise }`.
 *
 * `lines` are the engine's priced lines, `rates` maps item code to basis points, and `discount`
 * is the cart-level discount the engine decided. An item with no rate is not taxed and is not an
 * error — most ERPNext sites hold no tax templates at all.
 */
export function forLines(lines, rates, discountPaise = 0) {
  const rows = lines || []
  const grossTotal = rows.reduce((sum, line) => sum + grossPaise(line), 0)
  const shares = apportion(rows, Math.min(Math.trunc(discountPaise || 0), grossTotal), grossTotal)

  let total = 0
  const perLine = rows.map((line, i) => {
    const item = line.item || line.item_code
    const bps = Math.trunc((rates && rates[item]) || 0)
    const taxable = grossPaise(line) - (shares[i] || 0)
    const amount = onPaise(taxable, bps)
    total += amount
    return { item, taxable_paise: taxable, tax_bps: bps, tax_paise: amount }
  })

  return { lines: perLine, tax_paise: total }
}
