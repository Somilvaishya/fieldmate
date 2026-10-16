<script setup>
/**
 * The catalogue: what this shop may be sold, and the fastest way to put it in a cart.
 *
 * A rep opens this standing at a counter with the shopkeeper waiting. Forty taps loses the sale,
 * so every decision here is about taps and about what can be read at arm's length in sunlight.
 *
 * Four things this screen is built around.
 *
 * **Every quantity change re-prices locally.** `stores/order.js` is synchronous on the hot path -
 * no fetch, no spinner, no jitter - so the total in the bottom bar moves the instant a thumb
 * lands. Nothing on this screen awaits the network to show a number.
 *
 * **Credit is on the header, not on the rejection.** DESIGN.md UX requirement 9. The headroom is
 * read from the cache the shop's own screen already wrote, so it is there in a basement market,
 * and it is stamped with its own age rather than presented as today's.
 *
 * **The list is windowed.** A shop's range runs to several hundred SKUs and this renders on a
 * four-year-old Android. Rows arrive twenty-four at a time; the store deliberately keeps
 * `catalogueItems` independent of the cart so a quantity tap re-prices without rebuilding the
 * long list, and the cart badge on a row is a Map lookup rather than a flag on all four hundred.
 *
 * **Nothing is hidden because it is inconvenient.** An unpriceable item is shown and refused, not
 * quietly priced at zero. An offer the compiler could not build is named. A cached catalogue says
 * how old it is. An out-of-stock SKU keeps its row.
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { t } from '../lib/i18n'
import * as cart from '../stores/order'
import { credit, creditFetchedAt, creditOffline, loadCredit, assessCredit } from '../lib/credit'
import { moneyLabel, qtyWords, schemeBadge, symbolFor, uomLabel } from '../lib/schemeWords'
import { toPaise } from '../lib/money'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()

// Refs re-exported as local bindings: a template unwraps a ref that is a top-level setup binding,
// but not one reached through an imported namespace, so `cart.lines` in markup would render the
// ref object itself.
const loading = cart.loading
const loadError = cart.error
const catalogue = cart.catalogue
const outletName = cart.outletName
const totals = cart.totals
const lineCount = cart.lineCount
const baseUnitCount = cart.baseUnitCount
const isEmpty = cart.isEmpty
const cartQty = cart.cartQty
const freeGoods = cart.freeGoods
const appliedSchemes = cart.appliedSchemes
const skippedSchemes = cart.skippedSchemes
const dataAge = cart.dataAge
const lastOrder = cart.lastOrder
const specs = cart.specs

const query = ref('')
const group = ref('__all')
const chip = ref('')
const PAGE = 24
const shownCount = ref(PAGE)
const notice = ref(null)
const busy = ref(false)

const outlet = computed(() => route.params.outlet)
// The kind of party, from the query string. Absent means a shop, which is every link this
// app wrote before primary orders existed.
const partyType = computed(() => route.query.party || null)
// What to put back on the next link. An empty object for a shop, so every URL this app
// already writes stays exactly as it was.
const keepParty = computed(() => (partyType.value ? { party: partyType.value } : {}))

const currency = computed(() => catalogue.value?.currency || null)
const symbol = computed(() => symbolFor(currency.value))

function money(paise, options) {
  return moneyLabel(paise, currency.value, options)
}

async function open(name) {
  // Already holding this shop's catalogue: re-read from disk without pulling four hundred priced
  // SKUs down again. Walking cart -> catalogue -> cart is the ordinary path and must not cost
  // three round trips on a market uplink.
  const held = cart.outlet.value === name && !!cart.catalogue.value
  shownCount.value = PAGE
  await Promise.all([cart.openOutlet(name, { refresh: !held, type: partyType.value }), loadCredit(name)])
}

onMounted(() => open(outlet.value))
watch(outlet, (name) => name && open(name))
watch([query, group, chip], () => { shownCount.value = PAGE })

// --------------------------------------------------------------------------------- the offers

function todayStamp() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * Only offers that are live today get a badge.
 *
 * The engine never reads a clock - that is ADR-021, and it is what makes parity provable - so the
 * store filters by date on the way into `reprice()`. It does not export the filtered list, so the
 * same rule is applied here. Advertising an offer that ended on Sunday is worse than advertising
 * none: the rep quotes it, and the server refuses it after the shopkeeper has heard the number.
 */
const liveSpecs = computed(() => {
  const on = todayStamp()
  return (specs.value || []).filter((spec) => {
    if (spec.valid_from && String(spec.valid_from) > on) return false
    if (spec.valid_to && String(spec.valid_to) < on) return false
    return true
  })
})

/** Item-scoped offers, by item code. Built once per spec change, not once per row. */
const schemesByItem = computed(() => {
  const index = new Map()
  for (const spec of liveSpecs.value) {
    if (spec.measured_over === 'Order') continue
    for (const code of spec.qualifying_items || []) {
      if (!index.has(code)) index.set(code, [])
      index.get(code).push(spec)
    }
  }
  return index
})

/**
 * Offers measured over the whole order.
 *
 * Deliberately not badged on every row. A cart-value scheme qualifies all four hundred SKUs, and
 * four hundred identical green pills tell a rep nothing and cost a frame each. It is said once,
 * above the list, where it is actually actionable.
 */
const orderOffers = computed(() =>
  liveSpecs.value
    .filter((spec) => spec.measured_over === 'Order')
    .map((spec) => ({
      scheme: spec.scheme,
      words: schemeBadge(spec, { currency: currency.value, nameFor, freeUomFor }),
    }))
    // A spec whose benefits this build does not recognise has nothing truthful to say about it.
    .filter((row) => !!row.words)
)

const itemIndex = computed(
  () => new Map((catalogue.value?.items || []).map((i) => [i.item_code, i]))
)

function nameFor(code) {
  return itemIndex.value.get(code)?.item_name || code
}
function freeUomFor(code) {
  return itemIndex.value.get(code)?.stock_uom || null
}

function badgeFor(item) {
  const list = schemesByItem.value.get(item.item_code)
  if (!list || !list.length) return null
  return schemeBadge(list[0], {
    currency: currency.value,
    factor: item.conversion_factor,
    display_uom: item.order_uom,
    base_uom: item.stock_uom,
    nameFor,
    freeUomFor,
  })
}

function extraOffers(item) {
  const list = schemesByItem.value.get(item.item_code)
  return list && list.length > 1 ? list.length - 1 : 0
}

// ------------------------------------------------------------------------------ what has fired

/** Free stock this cart has earned, by item. Its own lines, never folded into a discount. */
const freeByItem = computed(() => {
  const index = new Map()
  for (const row of freeGoods.value) {
    const held = index.get(row.item_code)
    index.set(row.item_code, {
      qty: (held?.qty || 0) + row.qty,
      uom: row.uom,
      scheme: row.scheme_name || held?.scheme || null,
    })
  }
  return index
})

/**
 * Which cart items an applied scheme is actually paying on.
 *
 * A discount belongs to a scheme, not to a line - a percentage comes off the qualifying lines
 * together - so the row says "this offer is applied" rather than attributing rupees to one SKU,
 * which would be arithmetic nobody could reconcile against the bill.
 */
const appliedByItem = computed(() => {
  const index = new Map()
  const held = new Set(cartQty.value.keys())
  for (const entry of appliedSchemes.value) {
    const spec = liveSpecs.value.find((s) => s.scheme === entry.scheme)
    if (!spec) continue
    const words = spec.rep_pitch || entry.scheme_name || t('Offer applied')
    const codes = spec.measured_over === 'Order' ? [...held] : (spec.qualifying_items || [])
    for (const code of codes) {
      if (!held.has(code)) continue
      if (!index.has(code)) index.set(code, words)
    }
  }
  return index
})

// -------------------------------------------------------------------------------- the browsing

const groups = computed(() => {
  const counts = new Map()
  for (const item of cart.catalogueItems.value) {
    const key = item.item_group || 'Other'
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  const rows = [...counts.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([key, count]) => ({ key, label: key, count }))
  return [{ key: '__all', label: t('All'), count: cart.catalogueItems.value.length },
          ...rows]
})

// `computed`, not a plain array: a module-level const holding labels is evaluated once when
// this file is first imported, so it would hold whichever language loaded first and the chips
// alone would stay in it after a switch. That is the `Me.vue` LINKS fault.
const CHIPS = computed(() => [
  { key: 'focus', label: t('Hero SKUs') },
  { key: 'mustsell', label: t('Must sell') },
  { key: 'scheme', label: t('On offer') },
])

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  const g = group.value
  const c = chip.value

  return cart.catalogueItems.value.filter((item) => {
    if (g !== '__all' && (item.item_group || 'Other') !== g) return false
    if (c === 'focus' && !item.is_focus) return false
    if (c === 'mustsell' && !item.is_must_sell) return false
    if (c === 'scheme' && !schemesByItem.value.has(item.item_code)) return false
    if (!q) return true
    return (
      (item.item_name || '').toLowerCase().includes(q) ||
      (item.item_code || '').toLowerCase().includes(q) ||
      (item.brand || '').toLowerCase().includes(q) ||
      (item.item_group || '').toLowerCase().includes(q)
    )
  })
})

const shown = computed(() => filtered.value.slice(0, shownCount.value))
const moreCount = computed(() => Math.max(0, filtered.value.length - shown.value.length))

function clearFilters() {
  query.value = ''
  group.value = '__all'
  chip.value = ''
}

// -------------------------------------------------------------------------------- a row's facts

/**
 * A thumbnail built from tokens.
 *
 * `catalogue.items` carries no image URL today, and DESIGN.md rules out a remote fetch on a
 * metered connection in a market. A broken image icon beside a price is worse than no image at
 * all, so a row draws the pack's initials on the primary tint until the payload carries something
 * real - and falls back to the same box if an image it is given fails to load.
 */
function initials(item) {
  const source = (item.item_name || item.item_code || '').trim()
  const words = source.split(/\s+/).filter(Boolean)
  if (!words.length) return '?'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

const broken = ref(new Set())
function imageFor(item) {
  return item.image && !broken.value.has(item.item_code) ? item.image : null
}
function onImageError(item) {
  broken.value = new Set([...broken.value, item.item_code])
}

/**
 * Stock, only where the payload actually says.
 *
 * `catalogue.items` does not carry availability yet. An "In stock" badge invented on the phone is
 * a promise the depot never made, so nothing is claimed unless a field says it - and when one
 * does, the row keeps its place in the list with the depot's date on it rather than disappearing.
 * A rep needs to see that the SKU exists and is out, or they will ask the shopkeeper for it.
 */
function stockFor(item) {
  const out =
    item.out_of_stock === true ||
    item.stock_status === 'Out of Stock' ||
    (typeof item.available_qty === 'number' && item.available_qty <= 0)
  if (out) return { out: true, eta: item.depot_eta || item.expected_on || null }
  if (typeof item.available_qty === 'number') {
    return { out: false, qty: item.available_qty, uom: item.stock_uom }
  }
  return null
}

/** What the shop makes if it sells at MRP. Only where an MRP is on file and is above our rate. */
function marginPct(item) {
  const mrp = toPaise(item.mrp)
  if (!mrp || item.rate_paise === null || item.rate_paise <= 0) return null
  if (mrp <= item.rate_paise) return null
  return Math.round(((mrp - item.rate_paise) / mrp) * 100)
}

function packWords(item) {
  const factor = Number(item.conversion_factor) || 1
  if (factor <= 1 || item.order_uom === item.stock_uom) return qtyWords(1, item.stock_uom)
  return `${qtyWords(factor, item.stock_uom)} per ${item.order_uom}`
}

// ------------------------------------------------------------------------------------ the cart

function heldQty(code) {
  return cartQty.value.get(code) || null
}

/**
 * The two quick-add buttons, in quantities this shop may actually order.
 *
 * A shop with a minimum of 3 cases must not be offered "+1 Case": the line would land under its
 * own minimum, `blockers` would refuse the order at submit, and the rep would have found out at
 * the end of forty taps rather than the first one. The buttons open at the minimum instead, and
 * say the number they are actually adding.
 */
function quickAdds(item) {
  const min = Math.max(1, Number(item.min_order_qty) || 1)
  const second = min > 1 ? min * 2 : 2
  return [min, second]
}

let noticeTimer = null
function say(message, tone = 'ok') {
  notice.value = { message, tone }
  clearTimeout(noticeTimer)
  // A confirmation clears itself; a refusal stays until the rep does something about it. A "saved"
  // line that never leaves is clutter on a screen that has none to spare.
  if (tone === 'ok') noticeTimer = setTimeout(() => { notice.value = null }, 4000)
}

onUnmounted(() => clearTimeout(noticeTimer))

/** "12 Sep" out of "2025-09-12". A rep reads a date, not an ISO string. */
// English keys, translated where they are read. The array itself is a lookup table, and
// translating it here would freeze it the way a label const freezes.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function shortDate(iso) {
  const parts = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''))
  if (!parts) return iso || ''
  const month = MONTHS[Number(parts[2]) - 1]
  return `${Number(parts[3])} ${month ? t(month) : ''}`.trim()
}

async function addUnits(item, displayQty) {
  notice.value = null
  try {
    const line = await cart.addItem(item.item_code, { qty: displayQty, unit: 'display' })
    if (line) {
      // DESIGN.md UX requirement 3: every write commits locally first and says so. The cart is in
      // IndexedDB before this line runs.
      say(t('{qty} of {item} saved on this phone.', {
        qty: qtyWords(line.display_qty, line.display_uom),
        item: line.item_name,
      }))
    }
  } catch (e) {
    say(e.message || t('That item could not be added.'), 'crit')
  }
}

async function bump(item, delta) {
  notice.value = null
  try {
    // Minus at the floor takes the line out rather than doing nothing. The button used to be
    // disabled there, so a rep who had added a shop's one wrong item could not undo it from this
    // screen at all - the only way back was to select the typed quantity and clear it by hand.
    //
    // Removing is right even where the floor is above one: a minimum order of five means five or
    // none, and four was never on offer.
    if (delta < 0 && heldQty(item.item_code).display_qty <= floorFor(item)) {
      await cart.removeItem(item.item_code)
      return
    }
    await cart.bumpQty(item.item_code, delta, { unit: 'display' })
  } catch (e) {
    say(e.message || t('That quantity could not be set.'), 'crit')
  }
}

/**
 * The typed quantity. `change`, not `input`: a rep typing "12" passes through 1, and re-pricing
 * the whole cart against a quantity nobody meant puts a number on the screen that is read out.
 */
async function onTyped(item, event) {
  const raw = event.target.value
  const value = Number(String(raw).replace(/[^\d.]/g, ''))
  notice.value = null
  try {
    if (!Number.isFinite(value) || value <= 0) {
      await cart.removeItem(item.item_code)
      return
    }
    await cart.setQty(item.item_code, value, { unit: 'display' })
  } catch (e) {
    say(e.message || t('That quantity could not be set.'), 'crit')
  } finally {
    const held = heldQty(item.item_code)
    event.target.value = held ? held.display_qty : ''
  }
}

/** The lower bound a minus tap stops at, so a mis-tap cannot silently empty a line. */
function floorFor(item) {
  return Math.max(1, Number(item.min_order_qty) || 1)
}

async function repeatLastOrder() {
  busy.value = true
  notice.value = null
  try {
    const result = await cart.prefillFromLastOrder()
    if (!result.had_history || !result.filled) {
      say(t('Nothing from the last order could be added to this one.'), 'warn')
      return
    }
    if (result.skipped.length) {
      // Stay put. Pushing to the cart here would carry the rep away from the one sentence telling
      // them their repeat order is short of what it was last month, and they would find the gap
      // at the counter.
      say(
        [
          t('{n} added from the last order.', { n: result.filled }),
          t('{n} could not come across: off this shop’s list, or no price yet.',
            { n: result.skipped.length }),
          t('Check before you read the total out.'),
        ].join(' '),
        'warn'
      )
      return
    }
    router.push({ name: 'order-cart', params: { outlet: outlet.value }, query: keepParty.value })
  } catch (e) {
    say(e.message || t('The last order could not be loaded.'), 'crit')
  } finally {
    busy.value = false
  }
}

async function refresh() {
  busy.value = true
  try {
    await cart.refreshAll()
    await loadCredit(outlet.value)
  } finally {
    busy.value = false
  }
}

// ------------------------------------------------------------------------------------- credit

const creditView = computed(() => assessCredit(credit.value, totals.value.net_paise))

const creditAge = computed(() => ageWords(creditFetchedAt.value))
const catalogueAge = computed(() => ageWords(dataAge.value.catalogue.fetchedAt))

function ageWords(at) {
  if (!at) return null
  const mins = Math.round((Date.now() - at) / 60000)
  if (mins < 2) return t('just now')
  if (mins < 60) return t('{n} min ago', { n: mins })
  const hours = Math.round(mins / 60)
  if (hours < 24) return t('{n} h ago', { n: hours })
  const days = Math.round(hours / 24)
  return days === 1 ? t('{n} day ago', { n: days }) : t('{n} days ago', { n: days })
}

const historyWords = computed(() => {
  const last = lastOrder.value
  if (!last || !last.order) return t('First order for this shop')
  return last.order_date
    ? t('Ordered before · last on {date}', { date: shortDate(last.order_date) })
    : t('Ordered before')
})

const emptyReason = computed(() => {
  if (loading.value || !catalogue.value) return null
  const items = catalogue.value.items || []
  if (items.length) return null
  return catalogue.value.catalogues && catalogue.value.catalogues.length
    ? t('This shop’s catalogue has no items on it yet. Your manager sets what this shop may be sold.')
    : t('No catalogue has been set for this shop yet, so there is nothing to order from. Ask your manager to put it on one.')
})
</script>

<template>
  <div class="wrap screen">
    <div class="top">
      <!-- Who we are ordering for. The shop name is the biggest thing on the header because it is
           the one fact a rep checks before quoting anything. -->
      <header class="head">
        <RouterLink class="back" :to="`/outlet/${outlet}`" :aria-label="t('Back to shop')">
          <Icon name="back" size="24" />
        </RouterLink>
        <div class="who">
          <h2>{{ outletName || outlet }}</h2>
          <p class="sub">
            <span v-if="credit?.beat">{{ credit.beat }}</span>
            <span v-else-if="catalogue?.price_list">{{ catalogue.price_list }}</span>
          </p>
          <div class="badges">
            <span v-if="credit?.kyc_verified" class="tag ok">
              <Icon name="check" size="18" /> {{ t('Verified retailer') }}
            </span>
            <span class="tag">{{ historyWords }}</span>
          </div>
        </div>
      </header>

      <!-- Credit before the cart, never as a rejection after it.

           Named, not anonymous. These are the **distributor's** figures with us, and this header
           called them "Credit headroom" on a shop's own screen - so a rep standing in a kirana
           read the distributor's limit as that kirana's. The shop's own debt to its distributor
           is a different number and sits on the line below. -->
      <div class="credit" :class="creditView.tone">
        <div class="crow">
          <span>
            {{ t('{party} owes us',
                 { party: creditView.party_name || t('The distributor') }) }}
          </span>
          <b v-if="creditView.state === 'within' || creditView.state === 'breach'" class="tnum">
            {{ money(creditView.headroom_paise) }}
          </b>
          <b v-else-if="creditView.state === 'unlimited'">{{ t('No limit set') }}</b>
          <b v-else>{{ t('Not on this phone') }}</b>
        </div>
        <p v-if="creditView.state === 'within' || creditView.state === 'breach'" class="cnote tnum">
          {{ t('of {limit} limit · {owed} owed', {
               limit: money(creditView.limit_paise),
               owed: money(creditView.outstanding_paise) }) }}
          <span v-if="creditAge">
            &middot; {{ t('checked {age}', { age: creditAge }) }}
          </span>
        </p>
        <p v-else-if="creditView.state === 'unlimited'" class="cnote tnum">
          {{ t('{owed} owed today.',
               { owed: money(creditView.outstanding_paise) }) }}
        </p>
        <p v-else class="cnote">
          {{ creditOffline
            ? t('The distributor’s credit has not reached this phone yet. You can still take the order.')
            : t('No credit limit is recorded for this distributor.') }}
        </p>

        <!-- This shop's own debt, where somebody has set it a limit. A zero limit cannot be told
             from no limit at all, so a shop nobody has given one is not shown as having no room.
             Our own count, and it says so. -->
        <p v-if="creditView.shop_has_limit" class="cnote tnum shop">
          {{ t('This shop owes {owed} of {limit}', {
               owed: money(creditView.shop_outstanding_paise),
               limit: money(creditView.shop_limit_paise) }) }}
          &middot; <em>{{ t('our own count') }}</em>
        </p>
      </div>

      <p v-if="credit && !credit.can_take_order" class="flag crit" role="alert">
        <Icon name="alert" size="20" />
        <span>
          {{ credit.blocked_reason
            || t('This shop is not cleared for orders yet. Your manager has to approve it.') }}
        </span>
      </p>

      <!-- Search. No barcode affordance: the catalogue payload carries no barcode and nothing on
           this phone can decode one, and a button that only apologises is worse than no button. -->
      <div class="find">
        <span class="mag"><Icon name="search" size="22" /></span>
        <input
          v-model="query"
          type="text"
          inputmode="search"
          :placeholder="t('Search name, brand or code')"
          :aria-label="t('Search this shop\'s items')"
        />
        <button v-if="query" type="button" class="clear" @click="query = ''" :aria-label="t('Clear search')">
          <Icon name="close" size="22" />
        </button>
      </div>

      <div class="chips" role="group" :aria-label="t('Filters')">
        <button
          v-for="c in CHIPS"
          :key="c.key"
          type="button"
          class="chip"
          :class="{ on: chip === c.key }"
          :aria-pressed="chip === c.key"
          @click="chip = chip === c.key ? '' : c.key"
        >{{ c.label }}</button>
      </div>

      <div class="tabs" role="tablist" :aria-label="t('Categories')">
        <button
          v-for="g in groups"
          :key="g.key"
          type="button"
          role="tab"
          class="tab"
          :class="{ on: group === g.key }"
          :aria-selected="group === g.key"
          @click="group = g.key"
        >{{ g.label }} <span class="tnum">({{ g.count }})</span></button>
      </div>

      <!-- Offers measured on the whole order, said once rather than on four hundred rows. -->
      <p v-for="offer in orderOffers" :key="offer.scheme" class="offer">
        <Icon name="tag" size="20" />
        <span>{{ offer.words }}</span>
      </p>

      <p v-if="skippedSchemes.length" class="flag warn">
        <Icon name="alert" size="20" />
        <span class="tnum">
          {{ skippedSchemes.length === 1
              ? t('{n} offer needs fixing by your manager and is not being applied here.',
                  { n: skippedSchemes.length })
              : t('{n} offers need fixing by your manager and are not being applied here.',
                  { n: skippedSchemes.length }) }}
        </span>
      </p>

      <p v-if="dataAge.catalogue.stale && catalogue" class="flag warn">
        <Icon name="cloud-off" size="20" />
        <span>
          {{ t('These prices were saved on this phone {age}.', { age: catalogueAge }) }}
          {{ t('Quote them if you have to, and refresh when you get signal.') }}
        </span>
      </p>

      <p v-if="notice" class="flag" :class="notice.tone" role="status">
        <Icon :name="notice.tone === 'crit' ? 'alert' : notice.tone === 'warn' ? 'alert' : 'check'" size="20" />
        <span>{{ notice.message }}</span>
      </p>

      <!-- Loading, empty and error are designed states, not afterthoughts. -->
      <div v-if="loading && !catalogue" class="state">
        <Icon name="store" size="36" />
        <b>{{ t("Loading this shop's items") }}</b>
        <p>{{ t('One moment. This is kept on the phone afterwards, so it is quicker next time.') }}</p>
      </div>

      <div v-else-if="loadError && !catalogue" class="state crit" role="alert">
        <Icon name="cloud-off" size="36" />
        <b>{{ t('No item list for this shop yet') }}</b>
        <p>{{ loadError }}</p>
        <button type="button" class="ghost" :disabled="busy" @click="refresh">
          <Icon name="refresh" size="20" /> {{ busy ? t('Trying…') : t('Try again') }}
        </button>
      </div>

      <div v-else-if="emptyReason" class="state">
        <Icon name="store" size="36" />
        <b>{{ t('Nothing to order from here') }}</b>
        <p>{{ emptyReason }}</p>
        <button type="button" class="ghost" :disabled="busy" @click="refresh">
          <Icon name="refresh" size="20" /> {{ busy ? t('Refreshing…') : t('Refresh') }}
        </button>
      </div>

      <div v-else-if="!filtered.length" class="state">
        <Icon name="search" size="36" />
        <b v-if="query">{{ t('No items match “{query}”', { query }) }}</b>
        <b v-else>{{ t('Nothing under this filter') }}</b>
        <p>{{ t('Try a shorter word, or clear what is set.') }}</p>
        <button type="button" class="ghost" @click="clearFilters">
          {{ t('Clear search and filters') }}
        </button>
      </div>

      <!-- The list -->
      <template v-else>
        <p class="count tnum">
          {{ filtered.length === 1
              ? t('{n} item', { n: filtered.length })
              : t('{n} items', { n: filtered.length }) }}
          <span v-if="catalogue.unpriceable_count" class="warnword">
            &middot; {{ t('{n} with no price yet', { n: catalogue.unpriceable_count }) }}
          </span>
        </p>

        <article v-for="item in shown" :key="item.item_code" class="sku"
                 :class="{ inorder: heldQty(item.item_code) }">
          <div class="skuhead">
            <span class="thumb" aria-hidden="true">
              <img v-if="imageFor(item)" :src="imageFor(item)" alt="" @error="onImageError(item)" />
              <template v-else>{{ initials(item) }}</template>
            </span>
            <div class="idn">
              <b class="name">{{ item.item_name }}</b>
              <p class="meta tnum">{{ item.item_code }} &middot; {{ packWords(item) }}</p>

              <p v-if="item.unpriceable" class="noprice">
                <Icon name="alert" size="18" /> {{ t("No price on this shop's list yet") }}
              </p>
              <p v-else-if="item.above_mrp" class="noprice">
                <Icon name="alert" size="18" />
                {{ t('Priced above its MRP of {mrp}',
                     { mrp: money(toPaise(item.mrp)) }) }}
              </p>
              <template v-else>
                <p class="price">
                  <b class="tnum">{{ money(item.order_uom_rate_paise) }}</b>
                  <span class="per">{{ t('per {uom}', { uom: item.order_uom }) }}</span>
                </p>
                <p class="meta tnum">
                  {{ t('{rate} per {uom}',
                       { rate: money(item.rate_paise), uom: item.stock_uom }) }}
                  <template v-if="item.mrp">
                    &middot; {{ t('MRP') }} <s>{{ money(toPaise(item.mrp)) }}</s>
                  </template>
                  <template v-if="marginPct(item)">
                    &middot; <span class="margin">{{ t('{n}% margin', { n: marginPct(item) }) }}</span>
                  </template>
                </p>
              </template>
            </div>
          </div>

          <div class="marks">
            <span v-if="item.is_focus" class="tag">{{ t('Hero SKU') }}</span>
            <span v-if="item.is_must_sell" class="tag">{{ t('Must sell') }}</span>
            <span v-if="badgeFor(item)" class="tag scheme">
              <Icon name="tag" size="18" /> {{ badgeFor(item) }}
            </span>
            <span v-if="extraOffers(item)" class="tag tnum">
              {{ t('+{n} more offer', { n: extraOffers(item) }) }}
            </span>
          </div>

          <p v-if="stockFor(item)?.out" class="flag warn small">
            <Icon name="alert" size="20" />
            <span>
              {{ stockFor(item).eta
                  ? t('Out of stock at the depot, expected {when}.',
                      { when: stockFor(item).eta })
                  : t('Out of stock at the depot.') }}
              {{ t('You can still book it — it goes out when stock lands.') }}
            </span>
          </p>
          <p v-else-if="stockFor(item)" class="stock tnum">
            <Icon name="check" size="18" />
            {{ t('{qty} at the depot',
                 { qty: qtyWords(stockFor(item).qty, stockFor(item).uom) }) }}
          </p>

          <!-- Quantity. Nothing here awaits the network: each tap re-prices the cart in memory. -->
          <div v-if="item.unpriceable" class="blocked">
            {{ t('Ask your manager to have this priced. It cannot be ordered until it is.') }}
          </div>

          <div v-else-if="item.above_mrp" class="blocked">
            {{ t('The list price is over the MRP on the pack, so this cannot be ordered.') }}
            {{ t('Ask your manager to correct it.') }}
          </div>

          <div v-else-if="!heldQty(item.item_code)" class="quick">
            <button
              v-for="n in quickAdds(item)"
              :key="n"
              type="button"
              class="add"
              @click="addUnits(item, n)"
            >
              <Icon name="plus" size="20" /> {{ n }} {{ uomLabel(n, item.order_uom) }}
            </button>
          </div>

          <div v-else class="stepper">
            <button
              type="button"
              class="step"
              :aria-label="heldQty(item.item_code).display_qty <= floorFor(item)
                ? t('Remove {item}', { item: item.item_name })
                : t('One {uom} less', { uom: item.order_uom })"
              @click="bump(item, -1)"
            ><Icon name="minus" size="22" /></button>

            <label class="qtybox">
              <input
                class="qty tnum"
                type="text"
                inputmode="decimal"
                :value="heldQty(item.item_code).display_qty"
                :aria-label="t('{uom} of {item}', { uom: item.order_uom, item: item.item_name })"
                @change="onTyped(item, $event)"
              />
              <span class="qtyuom">{{ uomLabel(heldQty(item.item_code).display_qty, item.order_uom) }}</span>
            </label>

            <button
              type="button"
              class="step"
              :aria-label="t('One more {uom}', { uom: item.order_uom })"
              @click="bump(item, 1)"
            ><Icon name="plus" size="22" /></button>

            <span class="lineside">
              <span class="units tnum">{{ qtyWords(heldQty(item.item_code).qty, item.stock_uom) }}</span>
              <b class="linetotal tnum">{{ symbol }}{{ heldQty(item.item_code).gross }}</b>
            </span>
          </div>

          <p v-if="heldQty(item.item_code) && freeByItem.get(item.item_code)" class="fired">
            <Icon name="gift" size="20" />
            <span class="tnum">
              +{{ qtyWords(freeByItem.get(item.item_code).qty, freeByItem.get(item.item_code).uom) }}
              {{ t('free added') }}<template v-if="freeByItem.get(item.item_code).scheme">
              &middot; {{ freeByItem.get(item.item_code).scheme }}</template>
            </span>
          </p>
          <p v-else-if="heldQty(item.item_code) && appliedByItem.get(item.item_code)" class="fired">
            <Icon name="tag" size="20" />
            <span>{{ appliedByItem.get(item.item_code) }}</span>
          </p>

          <p v-if="heldQty(item.item_code) && item.min_order_qty
                   && heldQty(item.item_code).display_qty < item.min_order_qty" class="fired warnline">
            <Icon name="alert" size="20" />
            <span class="tnum">
              {{ t('This shop cannot order less than {qty}.',
                   { qty: qtyWords(item.min_order_qty, item.order_uom) }) }}
            </span>
          </p>
        </article>

        <button v-if="moreCount" type="button" class="more tnum" @click="shownCount += PAGE">
          {{ t('Show {n} more · {left} left',
               { n: Math.min(PAGE, moreCount), left: moreCount }) }}
        </button>
      </template>
    </div>

    <!-- Primary action in the bottom third, one per screen. -->
    <div class="bottom">
      <template v-if="!isEmpty">
        <div class="sum">
          <span class="tnum">
            {{ lineCount === 1 ? t('{n} item', { n: lineCount })
                              : t('{n} items', { n: lineCount }) }}
            &middot; {{ t('{n} units', { n: baseUnitCount }) }}
          </span>
          <b class="grand tnum">{{ symbol }}{{ totals.net }}</b>
        </div>
        <div class="sumnote">
          <span v-if="totals.discount_paise" class="saving tnum">
            <Icon name="tag" size="18" />
            {{ t('{amount} off the bill',
                 { amount: symbol + totals.discount }) }}
          </span>
          <span v-if="freeGoods.length" class="saving tnum">
            <Icon name="gift" size="18" />
            {{ freeGoods.length === 1
                ? t('{n} free line', { n: freeGoods.length })
                : t('{n} free lines', { n: freeGoods.length }) }}
          </span>
          <span v-if="!totals.discount_paise && !freeGoods.length" class="muted">
            {{ t('No offer has fired on this order yet.') }}
          </span>
        </div>
        <RouterLink class="btn-primary" :to="{ name: 'order-cart', params: { outlet }, query: keepParty }">
          <Icon name="cart" size="22" /> {{ t('Review order') }}
        </RouterLink>
      </template>

      <template v-else-if="lastOrder?.order">
        <p class="sumnote muted">
          {{ t('Nothing added yet. The last order at this shop can start it off.') }}
        </p>
        <button type="button" class="btn-primary" :disabled="busy" @click="repeatLastOrder">
          <Icon name="refresh" size="22" />
          {{ busy ? t('Filling…') : t('Repeat last order') }}
        </button>
      </template>

      <p v-else class="sumnote muted">
        {{ t('Add an item above to start this order. It is saved on this phone as you go.') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
/* Every size and colour below is a token or a field constraint. No text under 16 px, 48 px
   minimum on anything a thumb lands on, 8 px between adjacent targets. Renders at 360 px. */
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: grid; gap: 12px; align-content: start; }

.head { display: flex; align-items: flex-start; gap: 8px; margin-top: 8px; }
.back { width: 48px; height: 48px; flex: none; display: grid; place-items: center;
        margin-left: -12px; color: var(--primary); border-radius: 6px; }
.who { min-width: 0; flex: 1; }
h2 { margin: 0; font-size: 20px; overflow-wrap: anywhere; }
.sub { margin: 2px 0 0; color: var(--muted); font-size: 16px; }
.badges { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }

.tag { display: inline-flex; align-items: center; gap: 4px; font-size: 16px; font-weight: 600;
       padding: 3px 8px; border-radius: 4px; background: var(--primary-soft); color: var(--primary); }
.tag.ok { background: var(--ok-soft); color: var(--ok); }
/* The brand green is a fill and an icon colour only - it measures 2.4:1 as text on white and is
   illegible outdoors. `--ok` is the same hue darkened until it is readable, on its own tint. */
.tag.scheme { background: var(--ok-soft); color: var(--ok); }

.credit { border: 1px solid var(--line); border-radius: 6px; padding: 12px;
          background: var(--surface); }
.credit.ok { background: var(--ok-soft); border-color: var(--ok); color: var(--ok); }
.credit.warn { background: var(--warn-soft); border-color: var(--warn); color: var(--warn); }
.credit.crit { background: var(--crit-soft); border-color: var(--crit); color: var(--crit); }
.crow { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
        font-size: 16px; }
.crow b { font-size: 20px; }
.cnote.shop { margin-top: 6px; padding-top: 6px; border-top: 1px solid var(--line); }
.cnote.shop em { font-style: normal; color: var(--muted); }
.cnote { margin: 4px 0 0; font-size: 16px; }
.credit:not(.ok):not(.warn):not(.crit) .cnote { color: var(--muted); }

.flag { display: flex; gap: 8px; align-items: flex-start; margin: 0; padding: 10px 12px;
        border-radius: 6px; font-size: 16px; border: 1px solid; }
.flag.ok { background: var(--ok-soft); color: var(--ok); border-color: var(--ok); }
.flag.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
.flag.crit { background: var(--crit-soft); color: var(--crit); border-color: var(--crit); }
.flag.small { padding: 8px 10px; }

.find { position: relative; }
.find input { padding-left: 44px; padding-right: 48px; }
.mag { position: absolute; left: 12px; top: 0; bottom: 0; display: grid; place-items: center;
       color: var(--muted); pointer-events: none; }
.clear { position: absolute; right: 0; top: 0; width: 48px; height: 48px; display: grid;
         place-items: center; background: none; border: 0; color: var(--muted); }

.chips, .tabs { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px;
                scrollbar-width: none; }
.chips::-webkit-scrollbar, .tabs::-webkit-scrollbar { display: none; }
.chip, .tab { flex: none; min-height: 48px; padding: 0 14px; border-radius: 6px; font-size: 16px;
              font-weight: 600; background: var(--surface); border: 1px solid var(--line);
              color: var(--ink); white-space: nowrap; }
.chip.on, .tab.on { background: var(--primary); border-color: var(--primary);
                    color: var(--on-primary); }

.offer { display: flex; align-items: center; gap: 8px; margin: 0; padding: 10px 12px;
         border-radius: 6px; background: var(--ok-soft); color: var(--ok);
         border: 1px solid var(--ok); font-size: 16px; font-weight: 600; }

.count { margin: 4px 0 0; color: var(--muted); font-size: 16px; }
.warnword { color: var(--warn); font-weight: 600; }

/* A row, not a card stack. One border, no shadow - DESIGN.md spends border and fill by role. */
.sku { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
       padding: 12px; display: grid; gap: 10px; }
.sku.inorder { border-color: var(--primary); }
.skuhead { display: flex; gap: 12px; align-items: flex-start; }
.thumb { width: 56px; height: 56px; flex: none; border-radius: 6px; background: var(--primary-soft);
         color: var(--primary); display: grid; place-items: center; font-weight: 700;
         font-size: 18px; overflow: hidden; }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.idn { min-width: 0; flex: 1; }
.name { font-size: 16px; font-weight: 600; overflow-wrap: anywhere; }
.meta { margin: 2px 0 0; color: var(--muted); font-size: 16px; overflow-wrap: anywhere; }
.price { margin: 4px 0 0; display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.price b { font-size: 18px; }
.per { color: var(--muted); font-size: 16px; }
.margin { color: var(--ok); font-weight: 600; }
.noprice { display: flex; align-items: center; gap: 6px; margin: 6px 0 0; color: var(--warn);
           font-size: 16px; font-weight: 600; }

.marks { display: flex; flex-wrap: wrap; gap: 8px; }
.marks:empty { display: none; }
.stock { display: flex; align-items: center; gap: 6px; margin: 0; color: var(--ok);
         font-size: 16px; }

.blocked { font-size: 16px; color: var(--muted); }

.quick { display: flex; gap: 8px; }
.add { flex: 1; min-height: 48px; display: inline-flex; align-items: center;
       justify-content: center; gap: 6px; font-size: 16px; font-weight: 600;
       background: var(--primary-soft); color: var(--primary); border: 1px solid var(--primary);
       border-radius: 6px; }

.stepper { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.step { width: 48px; height: 48px; flex: none; display: grid; place-items: center;
        background: var(--surface); border: 1px solid var(--primary); color: var(--primary);
        border-radius: 6px; }
.step:disabled { border-color: var(--line); color: var(--muted); }
.qtybox { display: grid; justify-items: center; gap: 0; }
/* A real numeric field, so the device's own keypad opens. DESIGN.md UX requirement 7. */
.qty { width: 72px; min-height: 48px; text-align: center; font-size: 18px; font-weight: 600;
       padding: 0 4px; }
.qtyuom { font-size: 16px; color: var(--muted); }
.lineside { margin-left: auto; display: grid; justify-items: end; }
.units { font-size: 16px; color: var(--muted); }
.linetotal { font-size: 18px; }

.fired { display: flex; align-items: flex-start; gap: 8px; margin: 0; padding: 8px 10px;
         border-radius: 6px; background: var(--ok-soft); color: var(--ok); font-size: 16px; }
.fired.warnline { background: var(--warn-soft); color: var(--warn); }

.more { width: 100%; min-height: 48px; border: 1px solid var(--primary); color: var(--primary);
        background: var(--surface); border-radius: 6px; font-weight: 600; font-size: 16px; }

.state { display: grid; justify-items: center; gap: 8px; text-align: center; padding: 28px 16px;
         color: var(--muted); font-size: 16px; }
.state b { color: var(--ink); font-size: 18px; }
.state p { margin: 0; max-width: 300px; }
.state.crit { color: var(--crit); }
.ghost { display: inline-flex; align-items: center; justify-content: center; gap: 6px;
         min-height: 48px; padding: 0 16px; background: var(--surface); color: var(--primary);
         border: 1px solid var(--primary); border-radius: 6px; font-weight: 600; font-size: 16px; }

/* Sticky, not fixed: the app already carries a tab bar below this. */
.bottom { position: sticky; bottom: 0; margin-top: 12px; padding: 12px 0 4px; display: grid;
          gap: 8px; background: var(--bg); border-top: 1px solid var(--line); }
.sum { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
       font-size: 16px; }
.grand { font-size: 20px; }
.sumnote { display: flex; flex-wrap: wrap; gap: 10px; margin: 0; font-size: 16px; }
.saving { display: inline-flex; align-items: center; gap: 4px; color: var(--ok); font-weight: 600; }
.muted { color: var(--muted); }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 8px;
               min-height: 52px; padding: 14px; border-radius: 6px; text-decoration: none;
               font-size: 16px; }
</style>
