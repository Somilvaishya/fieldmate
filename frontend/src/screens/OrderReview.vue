<script setup>
/**
 * The last screen before a rep commits, and the one that must not lie about what happens next.
 *
 * **ADR-023.** A retailer order is a *secondary* sale. Sending it routes it to the distributor's
 * queue; the distributor delivers and bills the shop out of their own stock. It creates no Sales
 * Order, no invoice, no GL entry and no stock movement. So nothing on this screen may say
 * "invoice raised" or "posted" - it says the order goes to the distributor, because that is the
 * whole of what happens.
 *
 * **A credit breach is recorded and routed, never refused at the counter.** A rep stopped in front
 * of a shopkeeper does not book a smaller order; they stop using the app, and then there is no
 * data at all. The breach is shown plainly, the copy says a manager reviews it, and the button
 * still sends.
 *
 * **It works with no signal.** This is exactly where a rep is standing when they commit. Every
 * figure is the local engine's, the credit position falls back to the last one this phone saw, and
 * `cart.submit()` queues the order on the handset when the link is dead - and says so.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { t } from '../lib/i18n'
import { api, ApiError } from '../api/client'
import { db, getMeta, setMeta } from '../db'
import { toPaise } from '../lib/money'
import { isPosmItem } from '../lib/posm'
import { moneyLabel, symbolFor } from '../lib/schemeWords'
import {
  advanceView, changeNote, defaultDeliveryDate, deliveryWindow, isBooking, outsideWindow,
  seasonLabel,
} from '../lib/season'
import { pendingCount } from '../sync/outbox'
import * as cart from '../stores/order'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()
const outlet = computed(() => String(route.params.outlet || ''))
// The kind of party, from the query string. Absent means a shop, which is every link this app
// wrote before primary orders existed.
const partyType = computed(() => route.query.party || null)
// What to put back on the next link. An empty object for a shop, so every URL this app
// already writes stays exactly as it was.
const keepParty = computed(() => (partyType.value ? { party: partyType.value } : {}))

// Top-level bindings: a module namespace is not ref-unwrapped by the template compiler.
const loading = cart.loading
const catalogue = cart.catalogue
const lines = cart.lines
const lineCount = cart.lineCount
const baseUnitCount = cart.baseUnitCount
const isEmpty = cart.isEmpty
const totals = cart.totals
const freeGoods = cart.freeGoods
const blockers = cart.blockers
const outletName = cart.outletName
const activeVisit = visitStore.activeVisit
const season = cart.season
const orderKind = cart.orderKind
const locations = cart.locations

/**
 * Which of our own branches is making this sale.
 *
 * ERPNext models it as an Accounting Dimension, and a site that has enabled one makes it mandatory
 * on the Sales Order, the Delivery Note and the invoice — the document's naming series, the
 * company address and the GSTIN can all hang off it. Nothing fills it server-side: ERPNext applies
 * a dimension's default in the Desk form and nowhere else, so an order posted from a phone arrived
 * with it blank and was refused with "Select Location before Saving", a message naming a field the
 * rep has never heard of and had no way to supply.
 *
 * Asked only where there is something to ask. An empty list means the site has no Locations, and
 * then nothing downstream wants the field either.
 */
const location = ref(null)
const needsLocation = computed(() => weBill.value && locations.value.length > 0)

const shop = ref(null)
const distributor = ref(null)
const creditRow = ref(null)
const creditAt = ref(null)
const startedAt = ref(new Date())
const online = ref(navigator.onLine)
const check = ref(null)

const paymentTerm = ref('Credit')
const instructions = ref('')
const confirmedWith = ref('')
const readBack = ref(false)

const busy = ref(false)
const error = ref('')
const done = ref(null)
const queued = ref(0)

const cartRoute = computed(() => ({ name: 'order-cart', params: { outlet: outlet.value }, query: keepParty.value }))
const catalogueRoute = computed(() => ({
  name: 'order-catalogue',
  params: { outlet: outlet.value },
}))
const schemesRoute = computed(() => ({ name: 'order-schemes', params: { outlet: outlet.value }, query: keepParty.value }))

// -------------------------------------------------------------------------------------- money

// The symbol and the grouping both come from the shared display layer, so the review screen and
// the scheme screen cannot render the same figure two ways.
const sym = computed(() => symbolFor(totals.value.currency))
function money(paise) {
  return moneyLabel(paise, totals.value.currency)
}

/**
 * The two bill totals, net *and* tax, for the divergence warning below.
 *
 * `verifyWithServer` fails the match on either figure, so the warning fires when only the tax
 * differs - and it used to compare net to net, which printed the same number twice: "the office
 * prices this order at Rs981.80, not Rs981.80". The difference a rep could not see was the whole
 * of the GST, which is the half of the bill this app does not charge and cannot afford to
 * misquote. A cart carrying a tax rate the phone has not fetched yet is exactly how that happens.
 */
const officeTotal = computed(() => {
  const s = check.value && check.value.server
  if (!s) return null
  return (s.net_paise || 0) + (s.tax_paise || 0)
})

const myTotal = computed(() => totals.value.net_paise + totals.value.tax_paise)

// --------------------------------------------------------------------------------------- date

// English keys, translated where they are read. Translating the arrays here would freeze
// them at import the way a label const freezes.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function addDays(from, n) {
  const d = new Date(from.getTime())
  d.setDate(d.getDate() + n)
  return d
}
function iso(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
// Written out rather than left to `toLocaleDateString`, which is a different implementation on
// every Android WebView in the field and occasionally a different calendar.
function dayLabel(d) {
  return t('{day}, {date} {month}', {
    day: t(DAYS[d.getDay()]),
    date: d.getDate(),
    month: t(MONTHS[d.getMonth()]),
  })
}
function timeLabel(d) {
  const h = d.getHours()
  const m = String(d.getMinutes()).padStart(2, '0')
  const suffix = h < 12 ? t('am') : t('pm')
  const hour = h % 12 === 0 ? 12 : h % 12
  return `${hour}:${m} ${suffix}`
}

const startedLabel = computed(
  () => `${dayLabel(startedAt.value)} · ${timeLabel(startedAt.value)}`
)

// ------------------------------------------------------------------------------- the dispatch

const deliveryDays = computed(() => {
  const n = Number((distributor.value && distributor.value.delivery_days) || 0)
  return n > 0 ? n : null
})
const dispatchDate = computed(() =>
  deliveryDays.value === null ? null : addDays(startedAt.value, deliveryDays.value)
)
const dispatchIso = computed(() => (dispatchDate.value ? iso(dispatchDate.value) : null))
const distributorName = computed(
  () =>
    (distributor.value && distributor.value.distributor_name) ||
    (shop.value && shop.value.distributor) ||
    null
)

const creditDays = computed(() => {
  const own = Number((shop.value && shop.value.credit_days) || 0)
  if (own > 0) return own
  const theirs = Number((distributor.value && distributor.value.credit_days) || 0)
  return theirs > 0 ? theirs : null
})
const dueDate = computed(() => {
  if (creditDays.value === null) return null
  return addDays(dispatchDate.value || startedAt.value, creditDays.value)
})

// --------------------------------------------------------------------------------- the credit

/**
 * The shop's position with its distributor, in paise so the arithmetic is integer.
 *
 * `credit_limit` and `outstanding` arrive as rupees on a Frappe Currency column and are converted
 * once, here, through the same `to_paise` the compiler uses. The result is advisory either way -
 * ADR-023 holds this as a soft ledger that warns and routes but posts nothing.
 */
const credit = computed(() => {
  const row = creditRow.value
  if (!row) return null
  const limit = toPaise(row.credit_limit) || 0
  const outstanding = toPaise(row.outstanding) || 0
  const order = totals.value.net_paise
  const exposure = outstanding + order
  const unlimited = !limit

  const scale = Math.max(limit, exposure) || 1
  const pct = (n) => Math.max(0, Math.min(100, Math.round((n / scale) * 100)))

  return {
    unlimited,
    limit,
    outstanding,
    order,
    exposure,
    after: unlimited ? null : limit - exposure,
    over: unlimited ? 0 : Math.max(0, exposure - limit),
    breach: !unlimited && exposure > limit,
    segOutstanding: unlimited ? 0 : pct(Math.min(outstanding, limit)),
    segOrder: unlimited ? 0 : pct(Math.max(0, Math.min(limit - outstanding, order))),
    segOver: unlimited ? 0 : pct(Math.max(0, exposure - Math.max(limit, outstanding))),
  }
})

/**
 * What this shop owes its distributor, as paise, or null where nobody has given it a limit.
 *
 * A different debt from the card above it: that one is the distributor's balance with us, read
 * from ERPNext's receivable. This one is FieldMate's own count over the orders booked here and
 * the money collected against them, and the label says so - a rep arguing a figure across a
 * counter has to know which of the two it is.
 */
const shopCredit = computed(() => {
  const row = creditRow.value && creditRow.value.shop
  if (!row || !row.limit) return null
  const limit = toPaise(row.limit) || 0
  const outstanding = toPaise(row.outstanding) || 0
  return {
    limit,
    outstanding,
    overdue: toPaise(row.overdue) || 0,
    breach: outstanding + totals.value.net_paise > limit,
  }
})

function ago(ms) {
  if (ms === null || ms === undefined) return null
  const min = Math.floor(ms / 60000)
  if (min < 1) return t('just now')
  if (min < 60) return t('{n} min ago', { n: min })
  const hr = Math.floor(min / 60)
  if (hr < 24) return t('{n} h ago', { n: hr })
  const days = Math.floor(hr / 24)
  return days === 1 ? t('{n} day ago', { n: days }) : t('{n} days ago', { n: days })
}
const creditAge = computed(() => (creditAt.value ? ago(Date.now() - creditAt.value) : null))

// -------------------------------------------------------------------------------------- season

/**
 * A booking, and what that changes on this screen.
 *
 * Three things, and all three are promises made to the party at the counter: the rates are held
 * at today's and will not be repriced before delivery, an advance has to be collected before the
 * goods are planned, and every line is delivered inside the season's window. A rep who books a
 * season order without saying any of that has promised the party nothing the company will keep.
 *
 * `weBill` is wider than a booking: an ordinary primary order is also a sale we invoice ourselves.
 * The whole bottom half of this screen used to say "the distributor delivers it and bills the
 * shop" over an order whose Sales Order we raise and whose invoice we send (ADR-023 is about a
 * *retailer* order), so a rep booking on a distributor read out the one sentence that was false.
 */
const booking = computed(() => isBooking(orderKind.value))
const weBill = computed(() => orderKind.value === 'Primary' || booking.value)
const seasonName = computed(() => seasonLabel(season.value))
const frozen = computed(() => changeNote(season.value))
// Not `window`: this file adds listeners to the real one, and shadowing it here would have
// silenced the online/offline handlers that make the whole screen work with no signal.
const deliverWindow = computed(() => deliveryWindow(season.value))

/**
 * What this booking needs up front, from the phone's own arithmetic.
 *
 * Nothing has arrived yet - there is no order for money to be allocated against - so this is the
 * requirement alone, which is the figure the rep has to say out loud before the party agrees to
 * anything. What has actually been collected appears on the confirmation below, from the server's
 * own count, because by then there is an order to count against.
 */
const advance = computed(() =>
  advanceView({ netPaise: totals.value.net_paise, season: season.value })
)

/**
 * When each line is wanted.
 *
 * One date for the order, which fills every line, and a per-line override for the few that differ
 * - which is the shape a season booking actually has. Making a rep type the same date on forty
 * lines is how a form stops being filled in honestly, and the server agrees: a blank line takes
 * the window's first day rather than being refused.
 */
const bookingDate = ref('')
const lineDates = ref({})

function dateFor(line) {
  return lineDates.value[line.item_code] || bookingDate.value || ''
}

function setLineDate(line, value) {
  lineDates.value = { ...lineDates.value, [line.item_code]: value }
}

/** Every line's date, as the payload wants it. Empty for an order with no season. */
const deliveryDates = computed(() => {
  if (!booking.value) return null
  const out = {}
  for (const line of lines.value) {
    const date = dateFor(line)
    if (date) out[line.item_code] = date
  }
  return out
})

/**
 * The lines the season will refuse, named here rather than at submit.
 *
 * The server throws on the first one it meets. A rep reading that has to fix it, send again, and
 * be told about the next one - standing at a counter, on a market uplink.
 */
const badDates = computed(() =>
  booking.value
    ? outsideWindow(
        lines.value.map((l) => ({ ...l, delivery_date: dateFor(l) })),
        season.value
      )
    : []
)

// ---------------------------------------------------------------------------------- the lines

/**
 * The order's volume, tallied in the units it was actually ordered in.
 *
 * "14 cases" is wrong the moment one of the lines is sold in bags, so this counts per UOM: whole
 * display units on one side, the loose remainder in base units on the other. `display_whole` and
 * `display_remainder` come off the store already derived from the one integer quantity, so the two
 * readings cannot come apart.
 */
const volume = computed(() => {
  const tally = new Map()
  const bump = (uom, n) => {
    if (!uom || !n) return
    tally.set(uom, (tally.get(uom) || 0) + n)
  }
  for (const line of lines.value) {
    const factor = Number(line.conversion_factor) || 1
    if (factor > 1 && line.display_whole !== null) {
      bump(line.display_uom, line.display_whole)
      bump(line.base_uom, line.display_remainder)
    } else {
      bump(line.base_uom, line.qty)
    }
  }
  return [...tally.entries()]
    .filter(([, n]) => n > 0)
    .map(([uom, n]) => t('{n} {unit}', { n, unit: uom }))
})

function qtyLabel(line) {
  const factor = Number(line.conversion_factor) || 1
  if (factor <= 1 || line.display_whole === null) {
    return t('{n} {unit}', { n: line.qty, unit: line.base_uom })
  }
  const whole = t('{n} {unit}', { n: line.display_whole, unit: line.display_uom })
  const loose = line.display_remainder
    ? ' + ' + t('{n} {unit}', { n: line.display_remainder, unit: line.base_uom })
    : ''
  const base = t('{n} {unit}', { n: line.qty, unit: line.base_uom })
  return `${whole}${loose} · ${base}`
}

// Display material is dispatched with the order and belongs in the line list, but it is not free
// *stock* and is never counted as one. Same rule as the scheme screen, from the same file, so the
// two screens cannot give a rep two different counts for the same order.
const itemIndex = computed(
  () => new Map(cart.catalogueItems.value.map((i) => [i.item_code, i]))
)
function isPosm(row) {
  return isPosmItem(itemIndex.value.get(row.item_code))
}
const freeUnitCount = computed(() =>
  freeGoods.value.filter((row) => !isPosm(row)).reduce((sum, row) => sum + (row.qty || 0), 0)
)

// Only what the rep can fix standing here. EMPTY has its own state.
const stoppers = computed(() => blockers.value.filter((b) => b.code !== 'EMPTY'))

const ready = computed(
  () =>
    !isEmpty.value &&
    !stoppers.value.length &&
    !badDates.value.length &&
    !(needsLocation.value && !location.value) &&
    readBack.value &&
    !busy.value
)

// ------------------------------------------------------------------------------ the two engines

/**
 * The office's own arithmetic, when there is a link to ask down.
 *
 * The phone's figure is what the rep said out loud; the server's is the figure of record. They are
 * allowed no divergence, so a difference means one of the two engines is wrong and the rep is the
 * person best placed to find out before the shopkeeper does. It never blocks anything.
 */
async function runCheck() {
  if (!online.value || isEmpty.value) return
  try {
    const result = await cart.verifyWithServer()
    if (result && result.checked) check.value = result
  } catch {
    // A check we could not make is not news a rep has to read. Their figure stands.
  }
}

// ------------------------------------------------------------------------------- loading state

async function loadShop() {
  const name = outlet.value
  const record = await db.records.get(['FieldMate Outlet', name])

  const cached = await getMeta(`shopCredit:${name}`)
  if (cached) {
    shop.value = { ...(record || {}), ...(cached.outlet || {}) }
    creditRow.value = cached.credit || null
    creditAt.value = cached.fetchedAt || null
  } else {
    shop.value = record || null
  }

  if (!outletName.value) {
    outletName.value = (shop.value && shop.value.outlet_name) || name
  }
  confirmedWith.value = (shop.value && shop.value.owner_name) || ''

  // The distributor's own terms - delivery days and credit days - are read out at a counter with
  // no signal, so they travel in the bootstrap payload that Today.vue stores. They used to come
  // from a synced FieldMate Distributor Profile table, which no longer exists: a distributor is
  // an ERPNext Customer, and a handset is not given read access to the customer master.
  const code = shop.value && shop.value.distributor
  if (code) {
    const boot = (await getMeta('profile')) || {}
    distributor.value =
      (boot.distributors || []).find((d) => d.distributor === code) || null
  }

  try {
    const detail = await api.outlet(name)
    shop.value = { ...(shop.value || {}), ...(detail.outlet || {}) }
    creditRow.value = detail.credit || null
    creditAt.value = Date.now()
    confirmedWith.value = confirmedWith.value || detail.outlet?.owner_name || ''
    await setMeta(`shopCredit:${name}`, {
      outlet: detail.outlet || null,
      credit: detail.credit || null,
      fetchedAt: creditAt.value,
    })
  } catch (e) {
    // Offline, or a shop whose credit we simply cannot reach right now. Whatever this phone
    // already held stands, and the card below says how old it is. Never a blocker.
    if (!(e instanceof ApiError)) throw e
  }
}

function setOnline() {
  online.value = true
}
function setOffline() {
  online.value = false
}

onMounted(async () => {
  if (!outlet.value) return router.replace('/today')
  // The open visit, read back off the handset if this page is a fresh load - which the installed
  // app launched from its icon is. Without it the punch went up with no visit on it and the way
  // out of this screen read "Back to today" to a rep who was standing in a shop.
  await visitStore.ensureActive()
  window.addEventListener('online', setOnline)
  window.addEventListener('offline', setOffline)

  if (cart.outlet.value !== outlet.value || !catalogue.value) {
    await cart.openOutlet(outlet.value, { type: partyType.value })
  }
  await loadShop()
  // The window's first day. Most lines of most bookings are wanted as early as they can be had,
  // which is also what the server fills a blank line with.
  bookingDate.value = defaultDeliveryDate(season.value) || ''
  // The branch that usually serves this party. A rep covering one branch never touches this.
  location.value = cart.defaultLocation.value || null
  if (creditDays.value === null) paymentTerm.value = 'Cash on Delivery'
  queued.value = await pendingCount()
  runCheck()
})

onUnmounted(() => {
  window.removeEventListener('online', setOnline)
  window.removeEventListener('offline', setOffline)
})

// ----------------------------------------------------------------------------------- the punch

/**
 * What the button says, and what the stamp says afterwards.
 *
 * "Send to distributor" over an order we invoice ourselves is the same false sentence as the note
 * at the bottom of the screen, in the one place a rep cannot miss it.
 */
const sendWords = computed(() => {
  if (booking.value) {
    return t('Book {season}', { season: seasonName.value || t('this season') })
  }
  if (weBill.value) return t('Send to the office')
  return t('Send to distributor')
})

const doneWords = computed(() => {
  if (done.value && done.value.offline) return t('Saved on this phone')
  if (done.value && done.value.booking) return t('Booked')
  if (weBill.value) return t('Sent to the office')
  return t('Sent to the distributor')
})

// `computed`, not a plain array. A module-level const holding labels is evaluated once at
// import, so the payment terms alone would have stayed in whichever language loaded first.
// `value` stays English either way - it is what the server stores and what the radio compares.
const TERMS = computed(() => [
  { value: 'Credit', label: t('On credit'), icon: 'timer' },
  { value: 'Cash on Delivery', label: t('Cash on delivery'), icon: 'store' },
  { value: 'UPI on Delivery', label: t('UPI on delivery'), icon: 'phone' },
])

async function send() {
  if (!ready.value) return
  error.value = ''
  busy.value = true

  // Snapshotted first. `submit()` empties the cart on success, so a confirmation screen that read
  // the totals afterwards would show the rep a zero for the order they just placed.
  const snapshot = {
    net: totals.value.net,
    discount: totals.value.discount,
    lines: lineCount.value,
    units: baseUnitCount.value,
    freeUnits: freeUnitCount.value,
    term: paymentTerm.value,
    dispatch: dispatchDate.value ? dayLabel(dispatchDate.value) : null,
  }

  try {
    const result = await cart.submit({
      paymentTerm: paymentTerm.value,
      creditDays: paymentTerm.value === 'Credit' ? creditDays.value : null,
      expectedDeliveryDate: dispatchIso.value,
      deliveryInstructions: instructions.value.trim() || null,
      confirmedWith: confirmedWith.value.trim() || null,
      deliveryDates: deliveryDates.value,
      location: location.value,
    })
    queued.value = await pendingCount()
    // `stores/order.js` reads the new order's name off `data.order`, but `fieldmate.api.order
    // .submit` returns `summarise(doc)`, whose key is `name`. Until those two agree the store's
    // `order` is undefined on the online path, and this screen would show a rep the word "Order"
    // with nothing after it - at the exact moment they need a reference to read out. So the name
    // is taken from whichever of the two carries it, and the offline path keeps its own honest
    // answer, which is that there is no number yet.
    const server = result.server || null
    done.value = {
      ...snapshot,
      ...result,
      reference: result.offline ? null : result.order || (server && server.name) || null,
      // What the server did with it. ADR-023 routing lands here as a status, never as an invoice.
      status: (server && server.order_status) || null,
      approval: !!(server && server.approval_required),
      // The server's own count of what has arrived against this booking, which on a booking
      // just taken is nothing. The phone's figure is the requirement; this is the position.
      advance: (server && server.advance) || null,
      season: seasonName.value,
      booking: booking.value,
      weBill: weBill.value,
    }
  } catch (e) {
    error.value =
      (e && e.message) ||
      t('Could not send the order. It is still here on the phone - try again in a moment.')
  } finally {
    busy.value = false
  }
}

function finish() {
  const open = activeVisit.value
  router.replace(open ? { name: 'visit', params: { uuid: open.clientUuid } } : '/today')
}
</script>

<template>
  <!-- ------------------------------------------------------------------ after the punch -->
  <div v-if="done" class="wrap screen">
    <div class="top">
      <div class="card sent" :class="done.offline ? 'held' : 'gone'">
        <span class="stamp">
          <Icon :name="done.offline ? 'cloud-off' : 'check'" size="22" />
          <span>{{ doneWords }}</span>
        </span>
        <b class="amount tnum">{{ sym }}{{ done.net }}</b>
        <p class="tnum ref" v-if="done.reference">
          {{ t('Order {reference}', { reference: done.reference }) }}
        </p>
        <p class="tnum ref" v-else>{{ t('No order number yet') }}</p>

        <!-- What actually happened, which is three different things. A booking short of its
             advance is **held**: the status says so and nothing is reserved, and a rep who walks
             away thinking the goods are coming has told the party something untrue. -->
        <p v-if="!done.offline && done.booking">
          {{ t('Booked against') }} <b>{{ done.season }}</b>
          {{ t('at today’s rates.') }}
          <template v-if="done.advance && done.advance.short">
            {{ t('It is held until') }}
            <b class="tnum">{{ money(toPaise(done.advance.short)) }}</b>
            {{ t('more advance is collected.') }}
            {{ t('Nothing is reserved or dispatched before then.') }}
          </template>
          <template v-else-if="done.advance && done.advance.required">
            {{ t('The advance is in hand, so it goes forward to be planned.') }}
          </template>
        </p>
        <p v-else-if="!done.offline && done.weBill">
          {{ t('It is with the office now. We raise the order and we invoice it.') }}
        </p>
        <p v-else-if="!done.offline">
          {{ t('It is with') }}
          <b>{{ distributorName || t('your distributor') }}</b>
          {{ t('now. They deliver the order and bill the shop.') }}
        </p>

        <!-- The one number a rep has to leave the counter with. -->
        <p v-if="done.advance && done.advance.short" class="held-note">
          <Icon name="alert" size="18" />
          <span class="tnum">
            {{ t('Collect') }}
            <b>{{ money(toPaise(done.advance.short)) }}</b>
            {{ t('to release this booking.') }}
          </span>
        </p>
        <p v-if="done.approval" class="held-note">
          <Icon name="alert" size="18" />
          <span>
            {{ t('Your manager has to approve this one before the distributor works it.') }}
            {{ t('It is recorded and they can see it — there is nothing more for you to do here.') }}
          </span>
        </p>
        <p v-else>
          {{ t('There is no signal here, so the order is written down on this phone.') }}
          {{ done.weBill
              ? t('It reaches the office on its own the moment you have a link — you can walk on.')
              : t('It goes to {party} on its own the moment you have a link — you can walk on.',
                  { party: distributorName || t('your distributor') }) }}
        </p>
      </div>

      <div class="card">
        <div class="srow tnum">
          <span>{{ t('Lines') }}</span><b>{{ done.lines }}</b>
        </div>
        <div class="srow tnum">
          <span>{{ t('Units') }}</span><b>{{ done.units }}</b>
        </div>
        <div class="srow tnum" v-if="done.freeUnits">
          <span>{{ t('Free stock') }}</span><b>{{ done.freeUnits }}</b>
        </div>
        <div class="srow tnum">
          <span>{{ t('Off the bill') }}</span><b>{{ sym }}{{ done.discount }}</b>
        </div>
        <div class="srow tnum" v-if="done.status">
          <span>{{ t('Status') }}</span><b>{{ done.status }}</b>
        </div>
        <div class="srow tnum">
          <span>{{ t('Payment') }}</span><b>{{ done.term }}</b>
        </div>
        <div class="srow tnum" v-if="done.dispatch">
          <span>{{ t('Dispatch') }}</span><b>{{ done.dispatch }}</b>
        </div>
      </div>

      <p class="note plain" v-if="queued">
        <Icon name="cloud-off" size="18" />
        <span class="tnum">
          <b>{{ queued }}</b>
          {{ queued === 1
              ? t('record waiting to send from this phone. They go on their own.')
              : t('records waiting to send from this phone. They go on their own.') }}
        </span>
      </p>
    </div>

    <div class="bottom">
      <button class="btn-primary" @click="finish">
        {{ activeVisit ? t('Back to the visit') : t('Back to today') }}
      </button>
    </div>
  </div>

  <!-- --------------------------------------------------------------------- before the punch -->
  <div v-else class="wrap screen">
    <div class="top">
      <RouterLink class="crumb" :to="cartRoute">
        <Icon name="back" size="18" /> <span>{{ t('Back to the cart') }}</span>
      </RouterLink>

      <header>
        <div class="idline">
          <h2>{{ outletName || outlet }}</h2>
          <span v-if="shop && shop.outlet_class" class="tag">{{ shop.outlet_class }}</span>
        </div>
        <p class="sub tnum">
          <span class="pill draft">{{ t('Draft · not sent') }}</span>
          <span>{{ startedLabel }}</span>
        </p>
        <p class="muted tnum">{{ outlet }}</p>
      </header>

      <div v-if="loading && !catalogue" class="card">
        <b>{{ t('Opening the order…') }}</b>
        <p class="muted">{{ t('One moment.') }}</p>
      </div>

      <div v-else-if="isEmpty" class="card empty">
        <b>{{ t('Nothing to send yet') }}</b>
        <p class="muted">
          {{ t('This order has no lines on it.') }}
          {{ t('Add what the shopkeeper asked for and come back here to read it out to them.') }}
        </p>
      </div>

      <template v-else>
        <!-- ------------------------------------------------------------- the season -->
        <!-- Three promises, said before the money: the rates are held, an advance is due, and
             every line lands inside the window. A rep who books a season order without saying
             them has promised the party nothing the company will keep. -->
        <div v-if="booking" class="card season">
          <div class="crown">
            <span class="stamp good">
              <Icon name="timer" size="18" />
              <span>{{ t('Booking · {season}', { season: seasonName }) }}</span>
            </span>
          </div>
          <p class="foot">
            {{ t('These rates are held for this season.') }}
            {{ t('The order is not repriced before it is delivered, whatever the list does in between.') }}
          </p>
          <div v-if="advance.required" class="srow tnum">
            <span>{{ t('Advance to collect') }}</span>
            <b>{{ money(advance.required) }}</b>
          </div>
          <p v-if="advance.required" class="foot strong">
            {{ t('Nothing is reserved or dispatched until that much is in hand.') }}
            {{ t('Take it now if you can — a cheque dated later does not count until its date.') }}
          </p>
          <div v-if="deliverWindow.from" class="srow tnum">
            <span>{{ t('Delivery window') }}</span>
            <b>{{ t('{from} to {to}',
                 { from: deliverWindow.from, to: deliverWindow.to }) }}</b>
          </div>
          <p v-if="frozen" class="foot strong">{{ frozen }}</p>
        </div>

        <!-- ------------------------------------------------------- financial clearance -->
        <div class="section">
          <h3>{{ weBill ? t('What the party pays') : t('What the shop pays') }}</h3>
        </div>

        <div class="card pay">
          <div class="payhead">
            <span>{{ t('Total payable') }}</span>
            <b class="big tnum">{{ sym }}{{ totals.tax_paise ? totals.grand : totals.net }}</b>
          </div>
          <!-- The GST the distributor will charge, so that what is read out here is what arrives
               on the bill. FieldMate posts none of it; a net-only figure is short by all of it.
               Hidden where no tax template covers the cart, because a zero GST row is a claim
               about this company's tax position rather than a fact about this order. -->
          <template v-if="totals.tax_paise">
            <div class="srow tnum">
              <span>{{ t('Goods') }}</span>
              <b>{{ sym }}{{ totals.net }}</b>
            </div>
            <div class="srow tnum">
              <span>{{ t("GST on the distributor's bill") }}</span>
              <b>{{ sym }}{{ totals.tax }}</b>
            </div>
          </template>
          <RouterLink class="srow tnum link" :to="schemesRoute">
            <span>{{ t('Scheme saving') }}</span>
            <b class="ok">
              &minus;{{ sym }}{{ totals.discount }}
              <Icon name="chevron" size="18" />
            </b>
          </RouterLink>
          <p class="foot" v-if="freeUnitCount">
            <b class="tnum">{{ freeUnitCount }}</b>
            {{ freeUnitCount === 1
                ? t('free unit ships with this order at {zero}.', { zero: sym + '0.00' })
                : t('free units ship with this order at {zero}.', { zero: sym + '0.00' }) }}
            {{ t('Their value is not taken off the total.') }}
          </p>
          <!-- Measured on what the shop actually receives. A scheme whose only benefit is the
               rep's incentive has "applied" and given the shopkeeper nothing. -->
          <p class="foot" v-if="totals.discount_paise === 0 && !freeUnitCount">
            {{ t('No scheme takes anything off this order.') }}
          </p>
        </div>

        <!-- The office's arithmetic, where there was a link to ask down. Never a blocker. -->
        <p v-if="check && !check.matched" class="note warn">
          <Icon name="alert" size="18" />
          <span class="tnum">
            {{ t('The office bills this order at') }}
            <b>{{ money(officeTotal) }}</b>, {{ t('not') }}
            <b>{{ money(myTotal) }}</b>.
            {{ t('The office figure is what the shop will be billed.') }}
            {{ t('Read that one out, and tell your manager if it looks wrong.') }}
          </span>
          <span v-if="check.tax_delta_paise" class="tnum">
            {{ t('The difference is the GST: the office has') }}
            <b>{{ money(check.server.tax_paise || 0) }}</b>
            {{ t('of tax on it and this phone has') }}
            <b>{{ money(totals.tax_paise) }}</b>.
            {{ t('Pull this screen down to fetch today’s rates.') }}
          </span>
        </p>

        <!-- Credit. Shown, recorded and routed - never used to refuse the order. -->
        <div v-if="credit" class="card credit" :class="credit.breach ? 'breach' : 'clear'">
          <div class="crown">
            <span class="stamp" :class="credit.breach ? 'bad' : 'good'">
              <Icon :name="credit.breach ? 'alert' : 'check'" size="18" />
              <span>
                {{ distributorName || t('The distributor') }}
                {{ credit.breach
                    ? t('is over the credit limit')
                    : t('is within the credit limit') }}
              </span>
            </span>
          </div>

          <!-- This card is the **distributor's** position with us, not the shop's. It always was
               - `api.outlet` reads the billing party's credit - but it said "this shop", which
               is the one party the figures are not about. The shop's own position with its
               distributor is a different number and `credit.check` now returns it; it is the row
               at the bottom of this card. The distributor is named on every line now, here and
               on the catalogue header and the cart. -->
          <template v-if="credit.unlimited">
            <p class="foot">
              {{ t('No credit limit is set for {party}, so nothing is holding this order.',
                   { party: distributorName || t('this distributor') }) }}
              {{ t('They owe') }}
              <b class="tnum">{{ money(credit.outstanding) }}</b> {{ t('today.') }}
            </p>
          </template>

          <template v-else>
            <div class="track" role="img"
                 :aria-label="t('Credit used {used} of {limit}',
                                { used: money(credit.exposure), limit: money(credit.limit) })">
              <span class="seg used" :style="{ width: credit.segOutstanding + '%' }"></span>
              <span class="seg this" :style="{ width: credit.segOrder + '%' }"></span>
              <span class="seg over" :style="{ width: credit.segOver + '%' }"></span>
            </div>
            <div class="legend">
              <span>
                <i class="sw used"></i> {{ t('Already owed') }}
                <b class="tnum">{{ money(credit.outstanding) }}</b>
              </span>
              <span>
                <i class="sw this"></i> {{ t('This order') }}
                <b class="tnum">{{ money(credit.order) }}</b>
              </span>
              <span v-if="credit.segOver">
                <i class="sw over"></i> {{ t('Over') }}
                <b class="tnum">{{ money(credit.over) }}</b>
              </span>
            </div>

            <div class="srow tnum">
              <span>{{ t('Sanctioned limit') }}</span>
              <b>{{ money(credit.limit) }}</b>
            </div>

            <!-- The shop's own debt to its distributor, which is a different number from
                 everything above and was invisible until now. Shown only where somebody has set
                 the shop a limit: a zero limit cannot be told from no limit at all, and a shop
                 nobody has given one is not a shop with no room. -->
            <div v-if="shopCredit" class="srow tnum" :class="{ bad: shopCredit.breach }">
              <span>
                {{ t('This shop owes its distributor') }}
                <em class="muted">{{ t('our own count') }}</em>
              </span>
              <b>{{ t('{owed} of {limit}', {
                   owed: money(shopCredit.outstanding),
                   limit: money(shopCredit.limit) }) }}</b>
            </div>
            <div class="srow tnum">
              <span>{{ credit.breach
                  ? t('Past the limit by')
                  : t('Headroom left after this') }}</span>
              <b :class="credit.breach ? 'bad' : 'ok'">
                {{ money(credit.breach ? credit.over : credit.after) }}
              </b>
            </div>

            <p v-if="credit.breach" class="foot strong">
              {{ t('Send it anyway.') }}
              {{ t('The order is recorded with the breach on it and goes to your manager for review — the shopkeeper does not have to wait at the counter.') }}
            </p>
          </template>

          <p class="muted tnum" v-if="creditAge">
            {{ t('Credit position as of {age}.', { age: creditAge }) }}
          </p>
        </div>

        <div v-else class="card">
          <b>{{ t('Credit position not on this phone') }}</b>
          <p class="muted">
            {{ t('This shop’s limit and outstanding have not reached this handset yet.') }}
            {{ t('The order still goes through, and the credit check runs on your manager’s side.') }}
          </p>
        </div>

        <!-- --------------------------------------------------------------- the lines -->
        <div class="section">
          <h3>{{ t('What was ordered') }}</h3>
          <span class="muted tnum">
            {{ lineCount === 1 ? t('{n} line', { n: lineCount })
                               : t('{n} lines', { n: lineCount }) }}
          </span>
        </div>

        <div class="card table">
          <div v-for="line in lines" :key="line.item_code" class="lrow"
               :class="{ off: line.unpriceable }">
            <span class="lbody">
              <b>{{ line.item_name }}</b>
              <span class="muted tnum">{{ qtyLabel(line) }}</span>
            </span>
            <span class="lmoney">
              <b class="tnum">{{ line.unpriceable ? '—' : sym + line.gross }}</b>
              <span class="muted tnum" v-if="!line.unpriceable">
                {{ t('{rate} / {uom}',
                     { rate: sym + line.display_rate, uom: line.display_uom }) }}
              </span>
              <span class="muted" v-else>{{ t('no price') }}</span>
            </span>
            <!-- One date for the order fills every line; this is the override for the few that
                 differ, which is the shape a season booking actually has. -->
            <label v-if="booking" class="when">
              <span class="sr">
                {{ t('When {item} is wanted', { item: line.item_name }) }}
              </span>
              <!-- Both events, deliberately. A date input fires `change` when the picker is
                   committed and `input` as the value is edited, and which of the two arrives
                   depends on the Android WebView - a handler on one of them loses the date on
                   the other, silently, and the line then books on the order date instead of the
                   one the rep chose. Setting it twice costs nothing. -->
              <input type="date" :value="dateFor(line)" :min="deliverWindow.from"
                     :max="deliverWindow.to"
                     @input="setLineDate(line, $event.target.value)"
                     @change="setLineDate(line, $event.target.value)" />
            </label>
          </div>

          <!-- Free lines bill at zero and are marked as such. They are dispatched in addition,
               so they carry no amount that any total may subtract. -->
          <div v-for="row in freeGoods" :key="'f' + row.item_code + row.scheme"
               class="lrow free" :class="{ posm: isPosm(row) }">
            <span class="lbody">
              <b>
                {{ row.item_name }}
                <span class="pill" :class="isPosm(row) ? 'flat' : 'ok'">
                  {{ isPosm(row) ? t('POSM') : t('Free') }}
                </span>
              </b>
              <span class="muted tnum">
                {{ t('{n} {unit}', { n: row.qty, unit: row.uom || t('units') }) }}
                <template v-if="row.scheme_name"> &middot; {{ row.scheme_name }}</template>
              </span>
            </span>
            <span class="lmoney">
              <b class="tnum">{{ sym }}0.00</b>
              <span class="muted">
                {{ isPosm(row) ? t('display material') : t('not billed') }}
              </span>
            </span>
          </div>

          <div class="lrow sum">
            <span class="lbody">
              <b>{{ t('Total') }}</b>
              <span class="muted tnum" v-if="volume.length">{{ volume.join(' · ') }}</span>
            </span>
            <span class="lmoney">
              <b class="tnum big">{{ sym }}{{ totals.net }}</b>
              <span class="muted tnum">
                {{ t('gross {amount}', { amount: sym + totals.gross }) }}
              </span>
            </span>
          </div>
        </div>

        <RouterLink v-if="stoppers.length" class="note crit" :to="cartRoute">
          <Icon name="alert" size="18" />
          <span>{{ stoppers[0].message }} <b>{{ t('Open the cart to fix it.') }}</b></span>
        </RouterLink>

        <!-- The one date, which every line follows unless the rep moved it above. -->
        <div v-if="booking" class="card">
          <label class="lbl" for="booking-date">{{ t('When is this wanted') }}</label>
          <input id="booking-date" type="date" v-model="bookingDate"
                 :min="deliverWindow.from" :max="deliverWindow.to" />
          <p class="muted small">
            {{ t('Every line follows this unless you set one of them differently.') }}
            {{ t('It has to fall between') }}
            <b class="tnum">{{ deliverWindow.from }}</b> {{ t('and') }}
            <b class="tnum">{{ deliverWindow.to }}</b>.
          </p>
        </div>

        <!-- Named here, all of them, rather than one at a time at submit. -->
        <p v-if="badDates.length" class="note crit" role="alert">
          <Icon name="alert" size="18" />
          <span>
            {{ badDates.length === 1
                ? t('One line is wanted outside this season’s delivery window:')
                : t('{n} lines are wanted outside this season’s delivery window:',
                    { n: badDates.length }) }}
            <b>{{ badDates.map((l) => l.item_name).join(', ') }}</b>.
            {{ badDates.length === 1 ? t('Move it between') : t('Move them between') }}
            <b class="tnum">{{ deliverWindow.from }}</b> {{ t('and') }}
            <b class="tnum">{{ deliverWindow.to }}</b>.
          </span>
        </p>

        <!-- ------------------------------------------------------------- payment terms -->
        <div class="section">
          <h3>{{ weBill ? t('How the party pays') : t('How the shop pays') }}</h3>
        </div>
        <fieldset class="terms">
          <legend class="sr">{{ t('Payment term') }}</legend>
          <!-- `term`, not `t`: the loop variable was shadowing the imported translator, and
               this block has three sentences inside it that need it. -->
          <label v-for="term in TERMS" :key="term.value" class="term"
                 :class="{ on: paymentTerm === term.value }">
            <input type="radio" name="payment-term" :value="term.value" v-model="paymentTerm" />
            <Icon :name="term.icon" size="20" />
            <span class="tbody">
              <b>{{ term.label }}</b>
              <span class="muted tnum" v-if="term.value === 'Credit' && dueDate">
                {{ t('Due {date} · {n} days from the bill',
                     { date: dayLabel(dueDate), n: creditDays }) }}
              </span>
              <span class="muted" v-else-if="term.value === 'Credit'">
                {{ t('Terms are set by your distributor.') }}
              </span>
              <span class="muted" v-else>
                {{ t('Collected when the order is delivered.') }}
              </span>
            </span>
            <Icon v-if="paymentTerm === term.value" name="check" size="20" class="mark" />
          </label>
        </fieldset>

        <!-- ------------------------------------------------------------ our branch -->
        <!-- Only where the site has Locations. On every other site this is not drawn at all,
             because a picker over nothing is a question with no answer. -->
        <div v-if="needsLocation" class="card">
          <label class="lbl" for="location">
            {{ t('Which of our branches is this sale from') }}
          </label>
          <select id="location" v-model="location">
            <option :value="null">{{ t('Choose one') }}</option>
            <option v-for="l in locations" :key="l.name" :value="l.name">
              {{ l.location_name || l.name }}
            </option>
          </select>
          <p class="muted small">
            {{ t('It decides the branch on the order and on the bill that follows it.') }}
          </p>
        </div>

        <!-- --------------------------------------------------------------- dispatch -->
        <div class="card slot">
          <Icon name="timer" size="22" />
          <span class="sbody">
            <b v-if="dispatchDate" class="tnum">
              {{ t('Dispatch {date}', { date: dayLabel(dispatchDate) }) }}
            </b>
            <b v-else>{{ t('Dispatch date set by the distributor') }}</b>
            <span class="muted tnum" v-if="dispatchDate">
              {{ deliveryDays === 1
                  ? t('{n} day, as committed by {party}',
                      { n: deliveryDays, party: distributorName || t('your distributor') })
                  : t('{n} days, as committed by {party}',
                      { n: deliveryDays, party: distributorName || t('your distributor') }) }}
            </span>
            <span class="muted" v-else>
              {{ t('They confirm it when they accept the order.') }}
            </span>
          </span>
        </div>

        <!-- --------------------------------------------------- instructions and the read-back -->
        <div class="card">
          <label class="lbl" for="instructions">
            {{ t('Delivery instructions') }}
            <span class="muted">{{ t('(optional)') }}</span>
          </label>
          <textarea id="instructions" v-model="instructions" rows="2"
                    :placeholder="t('Back lane after 4 pm, ask for Ramesh')" />
        </div>

        <div class="card">
          <label class="lbl" for="confirmed">{{ t('Read the order back to') }}</label>
          <input id="confirmed" v-model="confirmedWith" type="text"
                 :placeholder="t('Who you read it to')" autocomplete="off" />
          <label class="attest" :class="{ on: readBack }">
            <input type="checkbox" v-model="readBack" />
            <span>
              {{ t('I read this order back to') }}
              <b>{{ confirmedWith.trim() || t('the proprietor') }}</b>
              {{ t('and they agreed to it.') }}
            </span>
          </label>
        </div>

        <p v-if="error" class="note crit" role="alert">
          <Icon name="alert" size="18" /><span>{{ error }}</span>
        </p>

        <!-- ADR-023, said plainly and every time - and only where it applies. A *retailer*
             order is a secondary sale the distributor bills; a primary order and a booking are
             sales we invoice ourselves, and this screen said otherwise over every one of them. -->
        <p class="note plain">
          <Icon name="store" size="18" />
          <span v-if="booking">
            {{ t('This books') }} <b>{{ seasonName }}</b> {{ t('for') }}
            <b>{{ outletName || outlet }}</b>
            {{ t('at today’s rates. We raise the order and we invoice it.') }}
            <template v-if="advance.required">
              {{ t('It is held until') }}
              <b class="tnum">{{ money(advance.required) }}</b>
              {{ t('of advance is collected — nothing is reserved before then.') }}
            </template>
          </span>
          <span v-else-if="weBill">
            {{ t('This is a sale we invoice.') }}
            {{ t('Sending it raises the order on our side — it does not go to anybody else’s queue.') }}
          </span>
          <span v-else>
            {{ t('Sending this puts the order in') }}
            <b>{{ distributorName || t('your distributor') }}</b>{{ t('’s queue.') }}
            {{ t('They deliver it and they bill the shop. Nothing is invoiced from here.') }}
          </span>
        </p>
      </template>
    </div>

    <div class="bottom">
      <template v-if="isEmpty">
        <button class="btn-primary" @click="router.push(catalogueRoute)">
          {{ t('Add items to this order') }}
        </button>
      </template>
      <template v-else>
        <p v-if="needsLocation && !location" class="gate tnum">
          {{ t('Pick which of our branches this sale is from.') }}
        </p>
        <p v-else-if="!readBack" class="gate tnum">
          {{ t('Read the order back to the shopkeeper, then tick the box above.') }}
        </p>
        <p v-else-if="!online" class="gate tnum">
          {{ t('No signal. The order saves on this phone and sends itself later.') }}
        </p>
        <button class="btn-primary" :disabled="!ready" @click="send">
          <span v-if="busy">{{ t('Sending…') }}</span>
          <span v-else class="tnum">
            {{ online ? sendWords : t('Save on this phone') }} &middot;
            {{ sym }}{{ totals.net }}
          </span>
        </button>
        <button class="btn-plain" :disabled="busy" @click="router.push(cartRoute)">
          {{ t('Back to edit') }}
        </button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: grid; gap: 12px; align-content: start; }

.crumb { display: inline-flex; align-items: center; gap: 6px; min-height: 48px;
         text-decoration: none; color: var(--primary); font-weight: 600; }

h2 { margin: 0; font-size: 20px; overflow-wrap: anywhere; }
h3 { margin: 0; font-size: 16px; }
.idline { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sub { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 6px 0 0;
       color: var(--muted); font-size: 14px; }
.tag { font-size: 14px; font-weight: 600; padding: 3px 8px; border-radius: 4px;
       background: var(--primary-soft); color: var(--primary); }
.muted { color: var(--muted); font-size: 14px; margin: 2px 0 0; }
.ok { color: var(--ok); }
.bad { color: var(--crit); }

.section { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
           margin-top: 8px; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; display: grid; gap: 8px; }
.card.empty b { font-size: 16px; }
.card.empty p { font-size: 16px; }

.pill { font-size: 14px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.pill.draft { background: var(--warn-soft); color: var(--warn); }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.flat { background: var(--primary-soft); color: var(--primary); }

.payhead { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.big { font-size: 20px; font-weight: 700; }
.srow { display: flex; align-items: baseline; justify-content: space-between; gap: 8px;
        font-size: 16px; }
.srow.link { text-decoration: none; color: inherit; min-height: 48px; align-items: center; }
.srow.link b { display: inline-flex; align-items: center; gap: 4px; }
.foot { margin: 0; font-size: 14px; color: var(--muted); }
.foot.strong { color: var(--crit); font-weight: 600; font-size: 16px; }

 /* An error or a warning is copy the rep has to act on, so it holds the 16px floor even
    though labels and captions around it sit at the house 14px. */
.note { display: flex; gap: 8px; align-items: flex-start; margin: 0; padding: 12px;
        border-radius: 6px; font-size: 16px; text-decoration: none; }
.note svg { flex: none; margin-top: 2px; }
.note.warn { background: var(--warn-soft); color: var(--warn); border: 1px solid var(--warn); }
.note.crit { background: var(--crit-soft); color: var(--crit); border: 1px solid var(--crit); }
.note.plain { background: var(--primary-soft); color: var(--primary); }

.credit.clear { border-left: 4px solid var(--ok); }
.credit.breach { border-left: 4px solid var(--crit); }
.crown { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.stamp { display: inline-flex; align-items: center; gap: 6px; font-size: 16px; font-weight: 600; }
.stamp.good { color: var(--ok); }
.stamp.bad { color: var(--crit); }

.track { display: flex; height: 12px; border-radius: 6px; overflow: hidden;
         background: var(--primary-soft); }
.seg { display: block; height: 100%; }
.seg.used { background: var(--primary); }
.seg.this { background: var(--accent); }
.seg.over { background: var(--crit); }
.legend { display: grid; gap: 4px; font-size: 14px; color: var(--muted); }
.legend span { display: flex; align-items: center; gap: 6px; }
.legend b { margin-left: auto; color: var(--ink); }
.sw { width: 12px; height: 12px; border-radius: 3px; flex: none; }
.sw.used { background: var(--primary); }
.sw.this { background: var(--accent); }
.sw.over { background: var(--crit); }

.table { gap: 0; padding: 0 14px; }
.lrow { display: flex; gap: 10px; padding: 12px 0; border-top: 1px solid var(--line);
        align-items: flex-start; }
.lrow:first-of-type { border-top: 0; }
.lbody { flex: 1; display: grid; gap: 2px; min-width: 0; }
.lbody b { font-size: 16px; overflow-wrap: anywhere; }
.lmoney { flex: none; display: grid; gap: 2px; text-align: right; }
.lmoney b { font-size: 16px; }
.lrow.free { background: var(--ok-soft); margin: 0 -14px; padding-left: 14px;
             padding-right: 14px; }
.lrow.free.posm { background: var(--bg); }
.lrow.off b { color: var(--muted); }
.lrow.sum { border-top: 2px solid var(--line); }
.lrow.sum .big { font-size: 20px; }

.terms { border: 0; padding: 0; margin: 0; display: grid; gap: 8px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);
      white-space: nowrap; }
.term { display: flex; align-items: center; gap: 10px; min-height: 60px; padding: 10px 14px;
        border-radius: 6px; background: var(--surface); border: 1px solid var(--line);
        cursor: pointer; }
.term.on { border-color: var(--primary); background: var(--primary-soft); }
.term input { position: absolute; opacity: 0; width: 1px; height: 1px; }
.term:focus-within { outline: 2px solid var(--primary); outline-offset: 2px; }
.tbody { flex: 1; display: grid; gap: 2px; min-width: 0; }
.tbody b { font-size: 16px; }
.mark { flex: none; color: var(--primary); }

.slot { display: flex; align-items: center; gap: 10px; }
.sbody { flex: 1; display: grid; gap: 2px; min-width: 0; }
.sbody b { font-size: 16px; }

.lbl { display: block; font-weight: 600; font-size: 16px; }
textarea { width: 100%; font: inherit; padding: 10px 12px; border: 1px solid var(--line);
           border-radius: 6px; background: var(--bg); color: var(--ink); }
.attest { display: flex; align-items: flex-start; gap: 10px; min-height: 48px; padding: 10px;
          border-radius: 6px; border: 1px solid var(--line); background: var(--bg);
          font-size: 16px; cursor: pointer; }
.attest.on { border-color: var(--ok); background: var(--ok-soft); }
.attest input { width: 24px; height: 24px; min-height: 24px; margin: 2px 0 0; flex: none;
                accent-color: var(--ok); }

.sent { text-align: left; }
.sent.gone { border-left: 4px solid var(--ok); }
.sent.held { border-left: 4px solid var(--warn); }
.sent .stamp { font-size: 18px; }
.sent.gone .stamp { color: var(--ok); }
.sent.held .stamp { color: var(--warn); }
.amount { font-size: 28px; line-height: 1.2; }
.ref { margin: 0; color: var(--muted); font-size: 14px; }
.held-note { display: flex; gap: 8px; align-items: flex-start; padding: 10px 12px;
             border-radius: 6px; background: var(--warn-soft); color: var(--warn);
             font-size: 16px; }
.held-note svg { flex: none; margin-top: 2px; }
.sent p { margin: 0; font-size: 16px; }

.bottom { position: sticky; bottom: 0; padding: 10px 0 4px; margin-top: 16px;
          background: var(--bg); border-top: 1px solid var(--line); display: grid; gap: 8px; }
/* Instructional copy that gates the primary action: it holds the 16px floor. */
/* The season card. Same furniture as the credit card above it, so the two read as one column. */
.season .crown { margin-bottom: 6px; }
.season .srow + .foot { margin-top: 6px; }

/* The per-line delivery date. Narrow, because it sits beside a figure on a phone, and still 44px
   of target - a date a rep cannot hit is a date they leave wrong. */
.when { flex: none; }
.when input { min-height: 44px; font: inherit; font-size: 14px; padding: 4px 6px;
              border: 1px solid var(--line); border-radius: 6px; background: var(--surface);
              color: var(--ink); }
.small { font-size: 13px; margin: 6px 0 0; }
.gate { margin: 0; text-align: center; font-size: 16px; color: var(--muted); }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               padding: 14px; min-height: 52px; border-radius: 6px; width: 100%; }
.btn-primary:disabled { opacity: 0.55; }
.btn-plain { background: none; border: 1px solid var(--line); color: var(--ink); width: 100%;
             min-height: 48px; }
</style>
