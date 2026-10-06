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
import { api, ApiError } from '../api/client'
import { db, getMeta, setMeta } from '../db'
import { toPaise } from '../lib/money'
import { isPosmItem } from '../lib/posm'
import { moneyLabel, symbolFor } from '../lib/schemeWords'
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
  return `${DAYS[d.getDay()]}, ${d.getDate()} ${MONTHS[d.getMonth()]}`
}
function timeLabel(d) {
  const h = d.getHours()
  const m = String(d.getMinutes()).padStart(2, '0')
  const suffix = h < 12 ? 'am' : 'pm'
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
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} h ago`
  const days = Math.floor(hr / 24)
  return `${days} ${days === 1 ? 'day' : 'days'} ago`
}
const creditAge = computed(() => (creditAt.value ? ago(Date.now() - creditAt.value) : null))

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
  return [...tally.entries()].filter(([, n]) => n > 0).map(([uom, n]) => `${n} ${uom}`)
})

function qtyLabel(line) {
  const factor = Number(line.conversion_factor) || 1
  if (factor <= 1 || line.display_whole === null) {
    return `${line.qty} ${line.base_uom}`
  }
  const whole = `${line.display_whole} ${line.display_uom}`
  const loose = line.display_remainder ? ` + ${line.display_remainder} ${line.base_uom}` : ''
  return `${whole}${loose} · ${line.qty} ${line.base_uom}`
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
  () => !isEmpty.value && !stoppers.value.length && readBack.value && !busy.value
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
  window.addEventListener('online', setOnline)
  window.addEventListener('offline', setOffline)

  if (cart.outlet.value !== outlet.value || !catalogue.value) {
    await cart.openOutlet(outlet.value, { type: partyType.value })
  }
  await loadShop()
  if (creditDays.value === null) paymentTerm.value = 'Cash on Delivery'
  queued.value = await pendingCount()
  runCheck()
})

onUnmounted(() => {
  window.removeEventListener('online', setOnline)
  window.removeEventListener('offline', setOffline)
})

// ----------------------------------------------------------------------------------- the punch

const TERMS = [
  { value: 'Credit', label: 'On credit', icon: 'timer' },
  { value: 'Cash on Delivery', label: 'Cash on delivery', icon: 'store' },
  { value: 'UPI on Delivery', label: 'UPI on delivery', icon: 'phone' },
]

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
    }
  } catch (e) {
    error.value =
      (e && e.message) ||
      'Could not send the order. It is still here on the phone - try again in a moment.'
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
          <span>{{ done.offline ? 'Saved on this phone' : 'Sent to the distributor' }}</span>
        </span>
        <b class="amount tnum">{{ sym }}{{ done.net }}</b>
        <p class="tnum ref" v-if="done.reference">Order {{ done.reference }}</p>
        <p class="tnum ref" v-else>No order number yet</p>

        <p v-if="!done.offline">
          It is with <b>{{ distributorName || 'your distributor' }}</b> now. They deliver the
          order and bill the shop.
        </p>
        <p v-if="done.approval" class="held-note">
          <Icon name="alert" size="18" />
          <span>
            Your manager has to approve this one before the distributor works it. It is recorded
            and they can see it &mdash; there is nothing more for you to do here.
          </span>
        </p>
        <p v-else>
          There is no signal here, so the order is written down on this phone. It goes to
          <b>{{ distributorName || 'your distributor' }}</b> on its own the moment you have a
          link &mdash; you can walk on.
        </p>
      </div>

      <div class="card">
        <div class="srow tnum"><span>Lines</span><b>{{ done.lines }}</b></div>
        <div class="srow tnum"><span>Units</span><b>{{ done.units }}</b></div>
        <div class="srow tnum" v-if="done.freeUnits">
          <span>Free stock</span><b>{{ done.freeUnits }}</b>
        </div>
        <div class="srow tnum"><span>Off the bill</span><b>{{ sym }}{{ done.discount }}</b></div>
        <div class="srow tnum" v-if="done.status"><span>Status</span><b>{{ done.status }}</b></div>
        <div class="srow tnum"><span>Payment</span><b>{{ done.term }}</b></div>
        <div class="srow tnum" v-if="done.dispatch">
          <span>Dispatch</span><b>{{ done.dispatch }}</b>
        </div>
      </div>

      <p class="note plain" v-if="queued">
        <Icon name="cloud-off" size="18" />
        <span class="tnum">
          <b>{{ queued }}</b> {{ queued === 1 ? 'record' : 'records' }} waiting to send from this
          phone. They go on their own.
        </span>
      </p>
    </div>

    <div class="bottom">
      <button class="btn-primary" @click="finish">
        {{ activeVisit ? 'Back to the visit' : 'Back to today' }}
      </button>
    </div>
  </div>

  <!-- --------------------------------------------------------------------- before the punch -->
  <div v-else class="wrap screen">
    <div class="top">
      <RouterLink class="crumb" :to="cartRoute">
        <Icon name="back" size="18" /> <span>Back to the cart</span>
      </RouterLink>

      <header>
        <div class="idline">
          <h2>{{ outletName || outlet }}</h2>
          <span v-if="shop && shop.outlet_class" class="tag">{{ shop.outlet_class }}</span>
        </div>
        <p class="sub tnum">
          <span class="pill draft">Draft &middot; not sent</span>
          <span>{{ startedLabel }}</span>
        </p>
        <p class="muted tnum">{{ outlet }}</p>
      </header>

      <div v-if="loading && !catalogue" class="card">
        <b>Opening the order&hellip;</b>
        <p class="muted">One moment.</p>
      </div>

      <div v-else-if="isEmpty" class="card empty">
        <b>Nothing to send yet</b>
        <p class="muted">
          This order has no lines on it. Add what the shopkeeper asked for and come back here to
          read it out to them.
        </p>
      </div>

      <template v-else>
        <!-- ------------------------------------------------------- financial clearance -->
        <div class="section"><h3>What the shop pays</h3></div>

        <div class="card pay">
          <div class="payhead">
            <span>Total payable</span>
            <b class="big tnum">{{ sym }}{{ totals.tax_paise ? totals.grand : totals.net }}</b>
          </div>
          <!-- The GST the distributor will charge, so that what is read out here is what arrives
               on the bill. FieldMate posts none of it; a net-only figure is short by all of it.
               Hidden where no tax template covers the cart, because a zero GST row is a claim
               about this company's tax position rather than a fact about this order. -->
          <template v-if="totals.tax_paise">
            <div class="srow tnum">
              <span>Goods</span>
              <b>{{ sym }}{{ totals.net }}</b>
            </div>
            <div class="srow tnum">
              <span>GST on the distributor's bill</span>
              <b>{{ sym }}{{ totals.tax }}</b>
            </div>
          </template>
          <RouterLink class="srow tnum link" :to="schemesRoute">
            <span>Scheme saving</span>
            <b class="ok">
              &minus;{{ sym }}{{ totals.discount }}
              <Icon name="chevron" size="18" />
            </b>
          </RouterLink>
          <p class="foot" v-if="freeUnitCount">
            <b class="tnum">{{ freeUnitCount }}</b>
            free {{ freeUnitCount === 1 ? 'unit ships' : 'units ship' }} with this order at
            {{ sym }}0.00. Their value is not taken off the total.
          </p>
          <!-- Measured on what the shop actually receives. A scheme whose only benefit is the
               rep's incentive has "applied" and given the shopkeeper nothing. -->
          <p class="foot" v-if="totals.discount_paise === 0 && !freeUnitCount">
            No scheme takes anything off this order.
          </p>
        </div>

        <!-- The office's arithmetic, where there was a link to ask down. Never a blocker. -->
        <p v-if="check && !check.matched" class="note warn">
          <Icon name="alert" size="18" />
          <span class="tnum">
            The office bills this order at
            <b>{{ money(officeTotal) }}</b>, not
            <b>{{ money(myTotal) }}</b>. The office figure is what the shop will be billed.
            Read that one out, and tell your manager if it looks wrong.
          </span>
          <span v-if="check.tax_delta_paise" class="tnum">
            The difference is the GST: the office has
            <b>{{ money(check.server.tax_paise || 0) }}</b> of tax on it and this phone has
            <b>{{ money(totals.tax_paise) }}</b>. Pull this screen down to fetch today&rsquo;s
            rates.
          </span>
        </p>

        <!-- Credit. Shown, recorded and routed - never used to refuse the order. -->
        <div v-if="credit" class="card credit" :class="credit.breach ? 'breach' : 'clear'">
          <div class="crown">
            <span class="stamp" :class="credit.breach ? 'bad' : 'good'">
              <Icon :name="credit.breach ? 'alert' : 'check'" size="18" />
              <span>{{ credit.breach ? 'Over the credit limit' : 'Within the credit limit' }}</span>
            </span>
          </div>

          <!-- This card is the **distributor's** position with us, not the shop's. It always was
               - `api.outlet` reads the billing party's credit - but it said "this shop", which
               is the one party the figures are not about. The shop's own position with its
               distributor is a different number and `credit.check` now returns it; wiring this
               card to both is its own piece of work. -->
          <template v-if="credit.unlimited">
            <p class="foot">
              No credit limit is set for {{ distributorName || 'this distributor' }}, so nothing
              is holding this order. They owe
              <b class="tnum">{{ money(credit.outstanding) }}</b> today.
            </p>
          </template>

          <template v-else>
            <div class="track" role="img"
                 :aria-label="'Credit used ' + money(credit.exposure) + ' of ' + money(credit.limit)">
              <span class="seg used" :style="{ width: credit.segOutstanding + '%' }"></span>
              <span class="seg this" :style="{ width: credit.segOrder + '%' }"></span>
              <span class="seg over" :style="{ width: credit.segOver + '%' }"></span>
            </div>
            <div class="legend">
              <span><i class="sw used"></i> Already owed <b class="tnum">{{ money(credit.outstanding) }}</b></span>
              <span><i class="sw this"></i> This order <b class="tnum">{{ money(credit.order) }}</b></span>
              <span v-if="credit.segOver"><i class="sw over"></i> Over <b class="tnum">{{ money(credit.over) }}</b></span>
            </div>

            <div class="srow tnum">
              <span>Sanctioned limit</span><b>{{ money(credit.limit) }}</b>
            </div>

            <!-- The shop's own debt to its distributor, which is a different number from
                 everything above and was invisible until now. Shown only where somebody has set
                 the shop a limit: a zero limit cannot be told from no limit at all, and a shop
                 nobody has given one is not a shop with no room. -->
            <div v-if="shopCredit" class="srow tnum" :class="{ bad: shopCredit.breach }">
              <span>
                This shop owes its distributor
                <em class="muted">our own count</em>
              </span>
              <b>{{ money(shopCredit.outstanding) }} of {{ money(shopCredit.limit) }}</b>
            </div>
            <div class="srow tnum">
              <span>{{ credit.breach ? 'Past the limit by' : 'Headroom left after this' }}</span>
              <b :class="credit.breach ? 'bad' : 'ok'">
                {{ money(credit.breach ? credit.over : credit.after) }}
              </b>
            </div>

            <p v-if="credit.breach" class="foot strong">
              Send it anyway. The order is recorded with the breach on it and goes to your manager
              for review &mdash; the shopkeeper does not have to wait at the counter.
            </p>
          </template>

          <p class="muted tnum" v-if="creditAge">Credit position as of {{ creditAge }}.</p>
        </div>

        <div v-else class="card">
          <b>Credit position not on this phone</b>
          <p class="muted">
            This shop&rsquo;s limit and outstanding have not reached this handset yet. The order
            still goes through, and the credit check runs on your manager&rsquo;s side.
          </p>
        </div>

        <!-- --------------------------------------------------------------- the lines -->
        <div class="section">
          <h3>What was ordered</h3>
          <span class="muted tnum">{{ lineCount }} {{ lineCount === 1 ? 'line' : 'lines' }}</span>
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
                {{ sym }}{{ line.display_rate }} / {{ line.display_uom }}
              </span>
              <span class="muted" v-else>no price</span>
            </span>
          </div>

          <!-- Free lines bill at zero and are marked as such. They are dispatched in addition,
               so they carry no amount that any total may subtract. -->
          <div v-for="row in freeGoods" :key="'f' + row.item_code + row.scheme"
               class="lrow free" :class="{ posm: isPosm(row) }">
            <span class="lbody">
              <b>
                {{ row.item_name }}
                <span class="pill" :class="isPosm(row) ? 'flat' : 'ok'">
                  {{ isPosm(row) ? 'POSM' : 'Free' }}
                </span>
              </b>
              <span class="muted tnum">
                {{ row.qty }} {{ row.uom || 'units' }}
                <template v-if="row.scheme_name"> &middot; {{ row.scheme_name }}</template>
              </span>
            </span>
            <span class="lmoney">
              <b class="tnum">{{ sym }}0.00</b>
              <span class="muted">{{ isPosm(row) ? 'display material' : 'not billed' }}</span>
            </span>
          </div>

          <div class="lrow sum">
            <span class="lbody">
              <b>Total</b>
              <span class="muted tnum" v-if="volume.length">{{ volume.join(' · ') }}</span>
            </span>
            <span class="lmoney">
              <b class="tnum big">{{ sym }}{{ totals.net }}</b>
              <span class="muted tnum">gross {{ sym }}{{ totals.gross }}</span>
            </span>
          </div>
        </div>

        <RouterLink v-if="stoppers.length" class="note crit" :to="cartRoute">
          <Icon name="alert" size="18" />
          <span>{{ stoppers[0].message }} <b>Open the cart to fix it.</b></span>
        </RouterLink>

        <!-- ------------------------------------------------------------- payment terms -->
        <div class="section"><h3>How the shop pays</h3></div>
        <fieldset class="terms">
          <legend class="sr">Payment term</legend>
          <label v-for="t in TERMS" :key="t.value" class="term"
                 :class="{ on: paymentTerm === t.value }">
            <input type="radio" name="payment-term" :value="t.value" v-model="paymentTerm" />
            <Icon :name="t.icon" size="20" />
            <span class="tbody">
              <b>{{ t.label }}</b>
              <span class="muted tnum" v-if="t.value === 'Credit' && dueDate">
                Due {{ dayLabel(dueDate) }} &middot; {{ creditDays }} days from the bill
              </span>
              <span class="muted" v-else-if="t.value === 'Credit'">
                Terms are set by your distributor.
              </span>
              <span class="muted" v-else>Collected when the order is delivered.</span>
            </span>
            <Icon v-if="paymentTerm === t.value" name="check" size="20" class="mark" />
          </label>
        </fieldset>

        <!-- --------------------------------------------------------------- dispatch -->
        <div class="card slot">
          <Icon name="timer" size="22" />
          <span class="sbody">
            <b v-if="dispatchDate" class="tnum">Dispatch {{ dayLabel(dispatchDate) }}</b>
            <b v-else>Dispatch date set by the distributor</b>
            <span class="muted tnum" v-if="dispatchDate">
              {{ deliveryDays }} {{ deliveryDays === 1 ? 'day' : 'days' }}, as committed by
              {{ distributorName || 'your distributor' }}
            </span>
            <span class="muted" v-else>
              They confirm it when they accept the order.
            </span>
          </span>
        </div>

        <!-- --------------------------------------------------- instructions and the read-back -->
        <div class="card">
          <label class="lbl" for="instructions">
            Delivery instructions <span class="muted">(optional)</span>
          </label>
          <textarea id="instructions" v-model="instructions" rows="2"
                    placeholder="Back lane after 4 pm, ask for Ramesh" />
        </div>

        <div class="card">
          <label class="lbl" for="confirmed">Read the order back to</label>
          <input id="confirmed" v-model="confirmedWith" type="text"
                 placeholder="Who you read it to" autocomplete="off" />
          <label class="attest" :class="{ on: readBack }">
            <input type="checkbox" v-model="readBack" />
            <span>
              I read this order back to
              <b>{{ confirmedWith.trim() || 'the proprietor' }}</b> and they agreed to it.
            </span>
          </label>
        </div>

        <p v-if="error" class="note crit" role="alert">
          <Icon name="alert" size="18" /><span>{{ error }}</span>
        </p>

        <!-- ADR-023, said plainly and every time. Nothing here is invoiced by us. -->
        <p class="note plain">
          <Icon name="store" size="18" />
          <span>
            Sending this puts the order in
            <b>{{ distributorName || 'your distributor' }}</b>&rsquo;s queue. They deliver it and
            they bill the shop. Nothing is invoiced from here.
          </span>
        </p>
      </template>
    </div>

    <div class="bottom">
      <template v-if="isEmpty">
        <button class="btn-primary" @click="router.push(catalogueRoute)">
          Add items to this order
        </button>
      </template>
      <template v-else>
        <p v-if="!readBack" class="gate tnum">
          Read the order back to the shopkeeper, then tick the box above.
        </p>
        <p v-else-if="!online" class="gate tnum">
          No signal. The order saves on this phone and sends itself later.
        </p>
        <button class="btn-primary" :disabled="!ready" @click="send">
          <span v-if="busy">Sending&hellip;</span>
          <span v-else class="tnum">
            {{ online ? 'Send to distributor' : 'Save on this phone' }} &middot;
            {{ sym }}{{ totals.net }}
          </span>
        </button>
        <button class="btn-plain" :disabled="busy" @click="router.push(cartRoute)">
          Back to edit
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
.gate { margin: 0; text-align: center; font-size: 16px; color: var(--muted); }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               padding: 14px; min-height: 52px; border-radius: 6px; width: 100%; }
.btn-primary:disabled { opacity: 0.55; }
.btn-plain { background: none; border: 1px solid var(--line); color: var(--ink); width: 100%;
             min-height: 48px; }
</style>
