/**
 * Credit headroom, on the phone, before the cart exists.
 *
 * DESIGN.md UX requirement 9: "Credit headroom shown before the cart is built, never as a
 * rejection afterwards." A rep who builds a forty-line order and is then told the shop is over
 * its limit has wasted the shopkeeper's time and their own, and the next order goes in a
 * notebook. So the figure is on the catalogue header, above the first tap.
 *
 * **No new endpoint.** `outlet.detail` already returns `credit` and the Outlet 360 screen already
 * caches its whole payload under `outletDetail:<name>`, so this reads that cache first, paints,
 * and refreshes in the background. Two screens now share one cached answer instead of each
 * inventing a call, and a rep who opened the shop's own screen this morning has a credit figure
 * in a basement market this afternoon.
 *
 * **A figure this old has to say so.** Outstanding moves every time the distributor raises an
 * invoice or the shop pays. A cached headroom is still worth far more than none - it is the
 * difference between a rep knowing roughly where they stand and guessing - but it is never
 * presented as today's. `fetchedAt` comes back with it and the screens print its age.
 *
 * **It does not block anything.** `stores/order.js` deliberately keeps credit out of `blockers`,
 * and this file keeps to that: it returns a reading, not a verdict. A rep stopped in front of a
 * shopkeeper does not book a smaller order, they stop using the app. The server records, flags and
 * routes the breach - see `services/credit.py`, which ends every path in a sentence for exactly
 * this reason.
 */

import { ref } from 'vue'
import { api, ApiError } from '../api/client'
import { getMeta, setMeta } from '../db'
import { toPaise } from './money'

/** The reading for the outlet currently open. Screens read this directly. */
export const credit = ref(null)
export const creditFetchedAt = ref(null)
export const creditOffline = ref(false)

// Same shape the Outlet 360 screen writes, so the two caches are one cache.
const key = (outlet) => `outletDetail:${outlet}`
// Its own key rather than a field inside the payload: the Outlet 360 screen writes that payload
// whole, and adding a field to it there would be a change to a file this workstream does not own.
const stampKey = (outlet) => `outletDetail:${outlet}:at`

// A rep who walks out of one shop and into the next must not be shown the first shop's headroom.
// Same guard, and the same reason, as the catalogue load in stores/order.js.
let token = 0

function shape(detail) {
  if (!detail) return null
  const c = detail.credit || {}
  const o = detail.outlet || {}
  return {
    outlet: o.name || null,
    outlet_name: o.outlet_name || null,
    beat: o.primary_beat || null,
    gstin: o.gstin || null,
    kyc_verified: !!o.kyc_verified,
    credit_days: o.credit_days || null,
    can_take_order: detail.can_take_order !== false,
    blocked_reason: detail.blocked_reason || null,
    billing_party: detail.billing_party || null,
    // Rupees, as every Currency column downstream is (ADR-022). Converted to paise once, below,
    // so nothing on a screen ever does arithmetic on a float.
    limit_paise: toPaise(c.credit_limit) || 0,
    outstanding_paise: toPaise(c.outstanding) || 0,
    // ERPNext reads a zero limit as "no limit configured", not "no credit", and `compat.py` passes
    // that reading straight through as `unlimited`. A screen that treated zero as a wall would
    // stop every order on a site where nobody has typed a limit yet.
    unlimited: !!c.unlimited || !c.credit_limit,
    known: Object.keys(c).length > 0,
  }
}

/**
 * Load the reading for one shop. Cache first, always, and the network only if it answers.
 *
 * Never throws. A screen's `onMounted` has nowhere to put a rejection, and an expired session on
 * this call used to surface elsewhere in the app as a silent unhandled promise.
 */
export async function loadCredit(outlet) {
  const mine = ++token
  if (!outlet) {
    credit.value = null
    return null
  }

  const cached = await getMeta(key(outlet))
  if (mine !== token) return credit.value
  credit.value = shape(cached)
  creditFetchedAt.value = cached ? await getMeta(stampKey(outlet), null) : null
  creditOffline.value = false

  try {
    const data = await api.outlet(outlet)
    if (mine !== token) return credit.value
    credit.value = shape(data)
    creditFetchedAt.value = Date.now()
    await setMeta(key(outlet), data)
    await setMeta(stampKey(outlet), creditFetchedAt.value)
  } catch (e) {
    if (mine !== token) return credit.value
    // Offline with nothing cached is not an error worth a red box on an order screen - the rep can
    // still take the order, and the header simply says the figure is not on this phone.
    creditOffline.value = e instanceof ApiError && e.code === 'OFFLINE'
  }
  return credit.value
}

/**
 * Where this order leaves the shop's credit.
 *
 * `orderPaise` is the cart's net, which is what the distributor will bill. The exposure test is
 * the server's: outstanding plus this order against the limit, compared at rupee precision, so the
 * phone and `services/credit.py` cannot disagree over a paisa on a limit that was exactly met.
 */
export function assessCredit(reading, orderPaise = 0) {
  const order = Number(orderPaise) || 0

  if (!reading || !reading.known) {
    return { state: 'unknown', tone: 'muted', order_paise: order }
  }
  if (reading.unlimited) {
    return {
      state: 'unlimited',
      tone: 'muted',
      order_paise: order,
      outstanding_paise: reading.outstanding_paise,
      headline: 'No credit limit set for this shop',
    }
  }

  const limit = reading.limit_paise
  const headroom = limit - reading.outstanding_paise
  const after = headroom - order
  // Rupee precision, matching the server: "you are 0.000001 over" is not something anybody can say
  // to a shopkeeper, and a paisa of float noise is not a credit decision.
  const over = Math.round(-after / 100) > 0

  const used = Math.max(0, Math.min(100, Math.round(((reading.outstanding_paise + order) / limit) * 100)))
  const tone = over ? 'crit' : after < limit * 0.2 ? 'warn' : 'ok'

  return {
    state: over ? 'breach' : 'within',
    tone,
    limit_paise: limit,
    outstanding_paise: reading.outstanding_paise,
    headroom_paise: headroom,
    order_paise: order,
    after_paise: after,
    over_paise: over ? -after : 0,
    used_pct: used,
  }
}
