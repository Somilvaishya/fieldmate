<script setup>
/**
 * The cart: what this shop is buying, what it costs, and the one case that would earn more.
 *
 * This is the screen a rep turns round and shows the shopkeeper, so every figure on it has to be
 * one that survives being read out loud.
 *
 * **It opens on the last order.** DESIGN.md UX requirement 8 - a repeat order is two taps, not
 * forty - so an empty cart at a shop with history fills itself once per shop per day, says so in
 * a banner, and offers to undo. The rep's own numbers are never overwritten: the store skips any
 * item already in the cart.
 *
 * **The nudge is the commercial point of the screen.** `nearMisses` from the engine says a scheme
 * is one slab away; this works out which line to add it to, how many cases that is in the unit the
 * rep types in, what it costs and what it earns, and puts it behind one button. It is shown only
 * when the gap can actually be closed - never when there is no qualifying line in the cart, and
 * never when the line's own maximum stands in the way. A nudge a rep taps and watches do nothing
 * is worse than no nudge.
 *
 * **Free stock is never folded into a saving.** DESIGN.md UX requirement 11. `discount_paise` is
 * the only figure a total subtracts; the value of free goods is shown on the free-goods lines,
 * labelled as what the shop received. One combined "you saved" figure pays the shop twice on paper
 * and leaves the distributor settling a claim nobody authorised.
 *
 * **Credit is a reading, not a gate.** The bar and the words say exactly where this order leaves
 * the shop. Nothing here refuses to proceed: a rep stopped in front of a shopkeeper stops using
 * the app, and the server is where a breach is recorded, flagged and routed.
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as cart from '../stores/order'
import { credit, creditFetchedAt, creditOffline, loadCredit, assessCredit } from '../lib/credit'
import {
  appliedWords, billDiscountPaise, droppedWords, incentivePaise, moneyLabel, nearMissWords,
  planNudge, qtyWords, symbolFor, totalErrorWords, uomLabel,
} from '../lib/schemeWords'
import { toPaise } from '../lib/money'
import { getMeta, setMeta } from '../db'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()

const loading = cart.loading
const loadError = cart.error
const catalogue = cart.catalogue
const outletName = cart.outletName
const lines = cart.lines
const lineCount = cart.lineCount
const baseUnitCount = cart.baseUnitCount
const isEmpty = cart.isEmpty
const totals = cart.totals
const appliedSchemes = cart.appliedSchemes
const freeGoods = cart.freeGoods
const nearMisses = cart.nearMisses
const droppedSchemes = cart.droppedSchemes
const blockers = cart.blockers
const dataAge = cart.dataAge
const specs = cart.specs
const lastOrder = cart.lastOrder

const notice = ref(null)
const busy = ref(false)
const confirming = ref(null)
const prefilled = ref(null)

const outlet = computed(() => route.params.outlet)
// The kind of party, from the query string. Absent means a shop, which is every link this
// app wrote before primary orders existed.
const partyType = computed(() => route.query.party || null)
// What to put back on the next link. An empty object for a shop, so every URL this app already
// writes stays exactly as it was.
const keepParty = computed(() => (partyType.value ? { party: partyType.value } : {}))

const currency = computed(() => catalogue.value?.currency || null)
const symbol = computed(() => symbolFor(currency.value))

function money(paise, options) {
  return moneyLabel(paise, currency.value, options)
}

let noticeTimer = null
function say(message, tone = 'ok') {
  notice.value = { message, tone }
  clearTimeout(noticeTimer)
  if (tone === 'ok') noticeTimer = setTimeout(() => { notice.value = null }, 4000)
}
onUnmounted(() => clearTimeout(noticeTimer))

// ------------------------------------------------------------------------------------ opening

function todayStamp() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

async function open(name) {
  const held = cart.outlet.value === name && !!cart.catalogue.value
  await Promise.all([cart.openOutlet(name, { refresh: !held, type: partyType.value }), loadCredit(name)])
  await maybePrefill(name)
}

/**
 * The repeat order, filled once per shop per day.
 *
 * Once, and recorded, because a rep who deliberately cleared the cart and came back to it must not
 * find last month's order poured back in. The flag is written whether or not anything was filled,
 * so a shop with nothing to repeat is not asked again either.
 */
async function maybePrefill(name) {
  if (!cart.isEmpty.value) return
  if (!lastOrder.value?.order) return

  const flag = `orderPrefill:${name}:${todayStamp()}`
  if (await getMeta(flag)) return
  await setMeta(flag, true)

  try {
    const result = await cart.prefillFromLastOrder()
    if (result.filled) prefilled.value = result
  } catch {
    // Nothing to tell the rep here. The cart is simply empty and the catalogue is one tap away.
  }
}

async function undoPrefill() {
  await cart.clear()
  prefilled.value = null
  say('Started empty. Nothing was sent anywhere.')
}

onMounted(() => open(outlet.value))
watch(outlet, (name) => name && open(name))

// ------------------------------------------------------------------------------------- lines

async function bump(line, delta) {
  notice.value = null
  try {
    // At the floor, minus takes the line off. Same reasoning as the catalogue: the button was
    // disabled there instead, which left a dead control under the rep's thumb and no way down
    // from one except selecting the number and clearing it.
    if (delta < 0 && line.display_qty <= floorFor(line)) {
      await remove(line)
      return
    }
    await cart.bumpQty(line.item_code, delta, { unit: 'display' })
  } catch (e) {
    say(e.message || 'That quantity could not be set.', 'crit')
  }
}

async function onTyped(line, event) {
  const value = Number(String(event.target.value).replace(/[^\d.]/g, ''))
  notice.value = null
  try {
    if (!Number.isFinite(value) || value <= 0) {
      confirming.value = line.item_code
      return
    }
    await cart.setQty(line.item_code, value, { unit: 'display' })
  } catch (e) {
    say(e.message || 'That quantity could not be set.', 'crit')
  } finally {
    const held = cart.lineFor(line.item_code)
    event.target.value = held ? held.display_qty : ''
  }
}

async function remove(line) {
  await cart.removeItem(line.item_code)
  confirming.value = null
  say(`${line.item_name} taken off this order.`)
}

/** The lower bound a minus tap stops at, so a mis-tap cannot silently drop a line. */
function floorFor(line) {
  return Math.max(1, Number(line.min_order_qty) || 1)
}

// ------------------------------------------------------------------------------- the schemes

const specIndex = computed(() => new Map((specs.value || []).map((s) => [s.scheme, s])))
const itemIndex = computed(
  () => new Map((catalogue.value?.items || []).map((i) => [i.item_code, i]))
)

function nameFor(code) {
  return itemIndex.value.get(code)?.item_name || code
}
function freeUomFor(code) {
  return itemIndex.value.get(code)?.stock_uom || null
}

function contextFor(spec) {
  // The threshold is spoken in the units of a qualifying item the rep can see, so "240" becomes
  // "20 Cases" rather than a number nobody typed.
  const code = (spec?.qualifying_items || [])[0]
  const item = code ? itemIndex.value.get(code) : null
  return {
    currency: currency.value,
    factor: item?.conversion_factor,
    display_uom: item?.order_uom,
    base_uom: item?.stock_uom,
    nameFor,
    freeUomFor,
  }
}

/** One row per scheme that fired: what it did, in words, and what it took off this bill. */
const billRows = computed(() =>
  appliedSchemes.value.map((entry) => {
    const spec = specIndex.value.get(entry.scheme)
    return {
      scheme: entry.scheme,
      label: entry.rep_pitch || entry.scheme_name || entry.scheme,
      words: spec ? appliedWords(entry, spec, contextFor(spec)) : null,
      discount_paise: billDiscountPaise(entry),
      incentive_paise: incentivePaise(entry),
      budget_warning: !!entry.budget_warning,
    }
  })
)

/**
 * The nudge, with the exact tap that closes it.
 *
 * Gone through candidate by candidate rather than assumed:
 *
 * - a Qty gap is base units, so the tap is `ceil(gap / conversion_factor)` of whatever the rep
 *   types in, rounded up because half a case is not a thing anyone orders;
 * - a Value gap is paise, so the units needed are `ceil(gap / rate)` and then rounded up to whole
 *   display units the same way - both overshoot the line rather than land under it, because a
 *   nudge that leaves the rep one unit short is the worst outcome on this screen;
 * - a line whose maximum the tap would breach is passed over, and if no line survives that the
 *   nudge is not shown at all. The store would refuse the order at submit and the rep would find
 *   out at the end.
 *
 * Sorted by what it costs the shop, so the cheapest way to earn more is first.
 */
const nudges = computed(() => {
  const out = []
  for (const miss of nearMisses.value) {
    const spec = specIndex.value.get(miss.scheme)
    if (!spec) continue

    const plan = planNudge(miss, spec, lines.value)
    if (!plan) continue

    const applied = appliedSchemes.value.find((a) => a.scheme === miss.scheme) || null
    const words = nearMissWords(miss, spec, contextFor(spec), applied)
    if (!words) continue

    out.push({ key: `${miss.scheme}:${miss.slab_idx}`, scheme: miss.scheme, ...plan, ...words })
  }

  // Cheapest first, and never more than two: a screen of nudges is a screen a rep scrolls past.
  return out.sort((a, b) => a.cost_paise - b.cost_paise).slice(0, 2)
})

async function takeNudge(nudge) {
  busy.value = true
  try {
    await cart.bumpQty(nudge.item_code, nudge.add_display, { unit: 'display' })
    say(
      `${qtyWords(nudge.add_display, nudge.add_uom)} of ${nudge.item_name} added. ` +
      'The order has been re-priced on this phone.'
    )
  } catch (e) {
    say(e.message || 'That could not be added.', 'crit')
  } finally {
    busy.value = false
  }
}

// --------------------------------------------------------------------------------- the money

/**
 * What the shop makes if it sells at MRP.
 *
 * Only over the lines that carry an MRP, and it says how many those are. A margin quoted over a
 * cart where half the items have no MRP on file is a number that looks precise and is not, and it
 * is the kind of figure a shopkeeper writes down.
 */
const marginNote = computed(() => {
  let earns = 0
  let covered = 0
  for (const line of lines.value) {
    const mrp = toPaise(line.mrp)
    if (!mrp || line.rate_paise === null || mrp <= line.rate_paise) continue
    earns += (mrp - line.rate_paise) * line.qty
    covered += 1
  }
  if (!covered) return null
  return { earns_paise: earns, covered, total: lineCount.value }
})

const creditView = computed(() => assessCredit(credit.value, totals.value.net_paise))

const bar = computed(() => {
  const view = creditView.value
  if (view.state !== 'within' && view.state !== 'breach') return null
  const limit = view.limit_paise || 1
  const owed = Math.max(0, Math.min(100, (view.outstanding_paise / limit) * 100))
  const order = Math.max(0, Math.min(100 - owed, (view.order_paise / limit) * 100))
  return { owed, order }
})

const creditAge = computed(() => {
  const at = creditFetchedAt.value
  if (!at) return null
  const mins = Math.round((Date.now() - at) / 60000)
  if (mins < 2) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.round(hours / 24)
  return `${days} ${days === 1 ? 'day' : 'days'} ago`
})

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
function shortDate(iso) {
  const parts = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''))
  if (!parts) return iso || ''
  return `${Number(parts[3])} ${MONTHS[Number(parts[2]) - 1] || ''}`.trim()
}

/** Blockers other than "there is nothing here yet", which the empty state already says better. */
const realBlockers = computed(() => blockers.value.filter((b) => b.code !== 'EMPTY'))

/**
 * The items a blocker is about, by the name on the pack.
 *
 * The cart line first, then the catalogue: an item that has come off this shop's list since it was
 * added is exactly the kind of thing a blocker names, and it is no longer in the catalogue index
 * to look up. Falling straight through to the code would print "SE-1000" at a rep who has only
 * ever seen "Surf Excel 1 kg".
 */
function blockerLines(blocker) {
  return blocker.items
    .map((code) => lines.value.find((l) => l.item_code === code)?.item_name || nameFor(code))
    .join(', ')
}
</script>

<template>
  <div class="wrap screen">
    <div class="top">
      <header class="head">
        <RouterLink class="back" :to="{ name: 'order-catalogue', params: { outlet }, query: keepParty }"
                    aria-label="Back to the item list">
          <Icon name="back" size="24" />
        </RouterLink>
        <div class="who">
          <h2>{{ outletName || outlet }}</h2>
          <p v-if="credit?.gstin" class="sub tnum">GSTIN {{ credit.gstin }}</p>
          <div class="badges">
            <span v-if="creditView.state === 'within'" class="tag ok">
              <Icon name="check" size="18" /> Credit active
            </span>
            <span v-else-if="creditView.state === 'breach'" class="tag crit">
              <Icon name="alert" size="18" /> Over credit limit
            </span>
            <span v-else-if="creditView.state === 'unlimited'" class="tag">No credit limit set</span>
            <span v-if="credit?.credit_days" class="tag tnum">{{ credit.credit_days }} day terms</span>
          </div>
        </div>
      </header>

      <!-- Credit, in full, because this is the screen where the order value exists. -->
      <section class="credit" :class="creditView.tone" aria-label="Credit position">
        <div class="crow">
          <b v-if="creditView.state === 'breach'">Over the limit</b>
          <b v-else-if="creditView.state === 'within'">Safe zone &middot; under limit</b>
          <b v-else-if="creditView.state === 'unlimited'">No limit set for this shop</b>
          <b v-else>Credit not on this phone</b>
          <span v-if="creditView.state === 'breach'" class="tnum">
            {{ money(creditView.over_paise) }} over
          </span>
          <span v-else-if="creditView.state === 'within'" class="tnum">
            {{ money(creditView.after_paise) }} left after this
          </span>
        </div>

        <template v-if="bar">
          <div class="bar" role="img"
               :aria-label="`${creditView.used_pct} percent of the credit limit used with this order`">
            <span class="seg owed" :style="{ width: bar.owed + '%' }"></span>
            <span class="seg now" :style="{ width: bar.order + '%' }"></span>
          </div>
          <dl class="figures">
            <div><dt>Sanctioned</dt><dd class="tnum">{{ money(creditView.limit_paise) }}</dd></div>
            <div><dt>Already owed</dt><dd class="tnum">{{ money(creditView.outstanding_paise) }}</dd></div>
            <div><dt>This order</dt><dd class="tnum">{{ money(creditView.order_paise) }}</dd></div>
          </dl>
          <p class="cnote">
            <span v-if="creditView.state === 'breach'">
              This order takes the shop past its limit. You can still book it &mdash; your manager
              sees it flagged and decides.
            </span>
            <span v-else class="tnum">{{ creditView.used_pct }}% of the limit used with this order.</span>
            <span v-if="creditAge"> Checked {{ creditAge }}.</span>
          </p>
        </template>
        <p v-else class="cnote">
          {{ creditOffline
            ? 'This shop’s credit has not reached this phone yet. Take the order — the office will see where it lands.'
            : 'No credit limit is recorded for this shop, so nothing is holding this order.' }}
        </p>
      </section>

      <p v-if="notice" class="flag" :class="notice.tone" role="status">
        <Icon :name="notice.tone === 'ok' ? 'check' : 'alert'" size="20" />
        <span>{{ notice.message }}</span>
      </p>

      <!-- The repeat order, and the way out of it. -->
      <p v-if="prefilled" class="flag ok">
        <Icon name="refresh" size="20" />
        <span class="tnum">
          Filled from the last order<template v-if="prefilled.order_date">,
          {{ shortDate(prefilled.order_date) }}</template>. {{ prefilled.filled }}
          {{ prefilled.filled === 1 ? 'line' : 'lines' }}. Change what is different.
          <template v-if="prefilled.skipped.length">
            {{ prefilled.skipped.length }} could not come across &mdash; off the list, or no price yet.
          </template>
          <button type="button" class="link" @click="undoPrefill">Start empty instead</button>
        </span>
      </p>

      <!-- The highest commercial value on the screen. Obvious, not garish: one tinted card with
           one button, and only where the gap can actually be closed. -->
      <section v-for="nudge in nudges" :key="nudge.key" class="nudge">
        <p class="nhead">
          <Icon name="tag" size="20" />
          <b>Nearly at the next slab</b>
        </p>
        <p class="nbody">
          Add <b class="tnum">{{ qtyWords(nudge.add_display, nudge.add_uom) }}</b> of
          {{ nudge.item_name }} to reach <b class="tnum">{{ nudge.threshold }}</b> and earn
          <b>{{ nudge.earns }}</b><template v-if="nudge.instead_of"> instead of
          {{ nudge.instead_of }}</template>.
        </p>
        <p class="ncost tnum">
          Costs the shop {{ money(nudge.cost_paise) }} more
          <template v-if="nudge.scheme_name">&middot; {{ nudge.scheme_name }}</template>
        </p>
        <button type="button" class="nbtn" :disabled="busy" @click="takeNudge(nudge)">
          <Icon name="plus" size="20" />
          Add {{ qtyWords(nudge.add_display, nudge.add_uom) }}
        </button>
      </section>

      <!-- Anything standing between this cart and a submit, named with the items at fault. -->
      <p v-for="b in realBlockers" :key="b.code" class="flag crit" role="alert">
        <Icon name="alert" size="20" />
        <span>{{ b.message }} <b>{{ blockerLines(b) }}</b></span>
      </p>

      <p v-for="code in totals.errors" :key="code" class="flag crit" role="alert">
        <Icon name="alert" size="20" />
        <span>{{ totalErrorWords(code) }}</span>
      </p>

      <!-- States -->
      <div v-if="loading && !catalogue" class="state">
        <Icon name="cart" size="36" />
        <b>Opening this order</b>
        <p>One moment.</p>
      </div>

      <div v-else-if="loadError && !catalogue && isEmpty" class="state crit" role="alert">
        <Icon name="cloud-off" size="36" />
        <b>No item list for this shop yet</b>
        <p>{{ loadError }}</p>
      </div>

      <div v-else-if="isEmpty" class="state">
        <Icon name="cart" size="36" />
        <b>Nothing in this order yet</b>
        <p>
          Open the item list and add what the shopkeeper wants. Everything is saved on this phone
          as you go, signal or not.
        </p>
        <RouterLink class="ghost" :to="{ name: 'order-catalogue', params: { outlet }, query: keepParty }">
          <Icon name="store" size="20" /> Open the item list
        </RouterLink>
      </div>

      <!-- The lines -->
      <template v-else>
        <div class="section">
          <h3>This order</h3>
          <span class="muted tnum">
            {{ lineCount }} {{ lineCount === 1 ? 'line' : 'lines' }} &middot; {{ baseUnitCount }} units
          </span>
        </div>

        <article v-for="line in lines" :key="line.item_code" class="line"
                 :class="{ bad: line.unpriceable }">
          <div class="lhead">
            <div class="idn">
              <b class="name">{{ line.item_name }}</b>
              <p class="meta tnum">
                {{ line.item_code }}
                <template v-if="line.conversion_factor > 1">
                  &middot; {{ qtyWords(line.conversion_factor, line.base_uom) }} per
                  {{ line.display_uom }}
                </template>
              </p>
            </div>
            <button type="button" class="drop" :aria-label="`Remove ${line.item_name}`"
                    @click="confirming = confirming === line.item_code ? null : line.item_code">
              <Icon name="close" size="22" />
            </button>
          </div>

          <!-- An item nobody has priced is refused, never shown at zero. Zero books a pallet of
               soap for nothing and nobody finds out until the distributor reads his own invoice. -->
          <p v-if="line.unpriceable" class="noprice">
            <Icon name="alert" size="20" />
            <span>
              {{ line.off_catalogue
                ? 'This has come off this shop’s list since it was added, so it has no price.'
                : 'No price on this shop’s list yet, so this cannot be totalled.' }}
            </span>
          </p>

          <div v-else class="lrow">
            <div class="stepper">
              <button type="button" class="step"
                      :aria-label="line.display_qty <= floorFor(line)
                        ? `Remove ${line.item_name}` : `One ${line.display_uom} less`"
                      @click="bump(line, -1)">
                <Icon name="minus" size="22" />
              </button>
              <label class="qtybox">
                <input class="qty tnum" type="text" inputmode="decimal" :value="line.display_qty"
                       :aria-label="`${line.display_uom} of ${line.item_name}`"
                       @change="onTyped(line, $event)" />
                <span class="qtyuom">{{ uomLabel(line.display_qty, line.display_uom) }}</span>
              </label>
              <button type="button" class="step" :aria-label="`One more ${line.display_uom}`"
                      @click="bump(line, 1)">
                <Icon name="plus" size="22" />
              </button>
            </div>
            <div class="amounts">
              <span class="meta tnum">
                {{ symbol }}{{ line.display_rate }} per {{ line.display_uom }}
              </span>
              <b class="amount tnum">{{ symbol }}{{ line.gross }}</b>
              <span class="meta tnum">{{ qtyWords(line.qty, line.base_uom) }}</span>
            </div>
          </div>

          <p v-if="line.uom_fallback" class="flag warn small">
            <Icon name="alert" size="20" />
            <span class="tnum">
              This is being ordered in {{ line.base_uom }}, not cases &mdash; no pack size is set
              for it. Check the quantity.
            </span>
          </p>

          <div v-if="confirming === line.item_code" class="confirm">
            <span>Take {{ line.item_name }} off this order?</span>
            <div class="crow2">
              <button type="button" class="ghost" @click="confirming = null">Keep it</button>
              <button type="button" class="danger" @click="remove(line)">Remove</button>
            </div>
          </div>
        </article>
      </template>

      <!-- What the offers did, in words, and what came off the bill because of them. -->
      <template v-if="!isEmpty">
        <div class="section">
          <h3>Bill</h3>
          <span v-if="dataAge.schemes.stale" class="muted">Offers saved on this phone</span>
        </div>

        <section class="bill">
          <div class="brow">
            <span>Gross</span>
            <b class="tnum">{{ symbol }}{{ totals.gross }}</b>
          </div>

          <div v-for="row in billRows" :key="row.scheme" class="brow scheme">
            <span class="bwords">
              <b>{{ row.label }}</b>
              <em v-if="row.words">{{ row.words }}</em>
              <em v-if="row.budget_warning" class="warnword">
                This offer's budget is spent. It is still being applied &mdash; tell your manager.
              </em>
            </span>
            <b v-if="row.discount_paise" class="tnum off">-{{ money(row.discount_paise) }}</b>
            <span v-else class="tnum muted">free stock</span>
          </div>

          <div class="brow total">
            <span>Net payable</span>
            <b class="tnum big">{{ symbol }}{{ totals.net }}</b>
          </div>

          <!-- The distributor's GST on the distributor's invoice. Shown because the number the
               rep says out loud has to be the number on the bill that arrives this evening, and
               a net-only quote is short by all of it. Absent where no tax template covers the
               cart, which is most sites - a zero row would read as "no GST", which is a claim. -->
          <template v-if="totals.tax_paise">
            <div class="brow">
              <span>GST</span>
              <b class="tnum">{{ symbol }}{{ totals.tax }}</b>
            </div>
            <div class="brow total">
              <span>Bill total</span>
              <b class="tnum big">{{ symbol }}{{ totals.grand }}</b>
            </div>
          </template>

          <!-- Free goods are their own lines at zero. Their value is what the shop received, and
               it is never subtracted from anything. -->
          <div v-if="freeGoods.length" class="free">
            <p class="fhead"><Icon name="gift" size="20" /> <b>Free with this order</b></p>
            <div v-for="row in freeGoods" :key="`${row.scheme}:${row.item_code}`" class="frow">
              <span class="tnum">{{ qtyWords(row.qty, row.uom) }} {{ row.item_name }}</span>
              <span class="tnum muted">worth {{ symbol }}{{ row.value }}</span>
            </div>
            <p class="fnote">
              Shipped free, in addition to the order. Not taken off the bill.
            </p>
          </div>

          <div v-if="totals.incentive_paise" class="brow yours">
            <span>Your incentive</span>
            <b class="tnum">{{ money(totals.incentive_paise) }}</b>
          </div>
          <p v-if="totals.incentive_paise" class="fnote">
            Yours, not the shop's. It is not on this bill and does not change what they pay.
          </p>

          <p v-if="marginNote" class="fnote tnum">
            If sold at MRP this shop makes about {{ money(marginNote.earns_paise) }} on
            {{ marginNote.covered }} of {{ marginNote.total }}
            {{ marginNote.total === 1 ? 'line' : 'lines' }}, before the offers above.
          </p>
        </section>

        <!-- An offer that was taken away is said out loud, never swallowed - and with the reason
             the engine already sent. This used to hardcode "is not being applied to this order",
             which told a rep nothing they could act on: an empty budget, a better offer winning
             and too few pieces all read identically. The sentence comes from `droppedWords` so
             this screen and the offers screen say the same words about the same state. -->
        <p v-for="d in droppedSchemes" :key="d.scheme" class="flag warn small">
          <Icon name="alert" size="20" />
          <span class="why">
            <b>{{ d.scheme_name || d.scheme }}</b>
            <em>{{ droppedWords(d.reason) }}</em>
          </span>
        </p>
      </template>
    </div>

    <div class="bottom">
      <p v-if="!isEmpty" class="sum">
        <span class="tnum">{{ lineCount }} {{ lineCount === 1 ? 'line' : 'lines' }}</span>
        <b class="grand tnum">{{ symbol }}{{ totals.tax_paise ? totals.grand : totals.net }}</b>
      </p>
      <!-- One primary, and it follows what the rep is actually doing: with nothing in the cart the
           only useful action is the item list, so that is the primary rather than a dead button
           next to it. -->
      <div class="acts">
        <RouterLink :class="isEmpty ? 'btn-primary' : 'ghost'"
                    :to="{ name: 'order-catalogue', params: { outlet }, query: keepParty }">
          <Icon name="plus" size="20" /> Add products
        </RouterLink>
        <RouterLink v-if="!isEmpty" class="btn-primary"
                    :to="{ name: 'order-schemes', params: { outlet }, query: keepParty }">
          <Icon name="tag" size="20" /> See what this earns
        </RouterLink>
      </div>
      <p class="assurance">
        <Icon name="cloud-off" size="18" />
        <span>Saved on this phone as you go. Nothing is sent until you book it.</span>
      </p>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: grid; gap: 12px; align-content: start; }

.head { display: flex; align-items: flex-start; gap: 8px; margin-top: 8px; }
.back { width: 48px; height: 48px; flex: none; display: grid; place-items: center;
        margin-left: -12px; color: var(--primary); border-radius: 6px; }
.who { min-width: 0; flex: 1; }
h2 { margin: 0; font-size: 20px; overflow-wrap: anywhere; }
h3 { margin: 0; font-size: 16px; }
.sub { margin: 2px 0 0; color: var(--muted); font-size: 16px; overflow-wrap: anywhere; }
.badges { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.tag { display: inline-flex; align-items: center; gap: 4px; font-size: 16px; font-weight: 600;
       padding: 3px 8px; border-radius: 4px; background: var(--primary-soft); color: var(--primary); }
.tag.ok { background: var(--ok-soft); color: var(--ok); }
.tag.crit { background: var(--crit-soft); color: var(--crit); }

.credit { border: 1px solid var(--line); border-radius: 6px; padding: 12px;
          background: var(--surface); display: grid; gap: 8px; }
.credit.ok { background: var(--ok-soft); border-color: var(--ok); color: var(--ok); }
.credit.warn { background: var(--warn-soft); border-color: var(--warn); color: var(--warn); }
.credit.crit { background: var(--crit-soft); border-color: var(--crit); color: var(--crit); }
.crow { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
        font-size: 16px; }
.crow b { font-size: 18px; }
.cnote { margin: 0; font-size: 16px; }
.credit:not(.ok):not(.warn):not(.crit) .cnote { color: var(--muted); }

/* Two segments on one track: what the shop already owes, then what this order adds. The brand
   green is used as a fill here, which is the only place DESIGN.md allows it. */
.bar { display: flex; height: 10px; border-radius: 5px; overflow: hidden;
       background: var(--surface); border: 1px solid var(--line); }
.seg { display: block; height: 100%; }
.seg.owed { background: var(--primary); }
.seg.now { background: var(--accent); }

.figures { display: flex; flex-wrap: wrap; gap: 8px 16px; margin: 0; }
.figures div { display: grid; gap: 0; }
.figures dt { font-size: 16px; opacity: 0.9; }
.figures dd { margin: 0; font-size: 16px; font-weight: 700; }

.flag { display: flex; gap: 8px; align-items: flex-start; margin: 0; padding: 10px 12px;
        border-radius: 6px; font-size: 16px; border: 1px solid; }
.flag.ok { background: var(--ok-soft); color: var(--ok); border-color: var(--ok); }
.flag.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
.flag.crit { background: var(--crit-soft); color: var(--crit); border-color: var(--crit); }
.flag.small { padding: 8px 10px; }
/* Name over reason, the same shape the offers screen uses for the same fact. */
.why { display: grid; gap: 1px; }
.why em { font-style: normal; font-size: 15px; }
.link { background: none; border: 0; padding: 0; min-height: 0; color: inherit; font-size: 16px;
        font-weight: 700; text-decoration: underline; display: block; margin-top: 6px; }

.nudge { border: 1px solid var(--ok); background: var(--ok-soft); color: var(--ok);
         border-radius: 6px; padding: 12px; display: grid; gap: 8px; }
.nhead { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 16px; }
.nbody { margin: 0; font-size: 16px; color: var(--ink); }
.ncost { margin: 0; font-size: 16px; }
.nbtn { min-height: 48px; display: inline-flex; align-items: center; justify-content: center;
        gap: 6px; background: var(--ok); color: var(--on-primary); border: 0; border-radius: 6px;
        font-weight: 700; font-size: 16px; }

.section { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
           margin-top: 4px; }
.muted { color: var(--muted); font-size: 16px; }

.line { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 12px; display: grid; gap: 10px; }
.line.bad { border-color: var(--warn); }
.lhead { display: flex; gap: 8px; align-items: flex-start; }
.idn { flex: 1; min-width: 0; }
.name { font-size: 16px; font-weight: 600; overflow-wrap: anywhere; }
.meta { margin: 2px 0 0; color: var(--muted); font-size: 16px; overflow-wrap: anywhere; }
.drop { width: 48px; height: 48px; flex: none; margin: -6px -6px 0 0; display: grid;
        place-items: center; background: none; border: 0; color: var(--muted); }

.noprice { display: flex; gap: 8px; align-items: flex-start; margin: 0; color: var(--warn);
           font-size: 16px; }

.lrow { display: flex; align-items: flex-start; gap: 8px; flex-wrap: wrap; }
.stepper { display: flex; align-items: center; gap: 8px; }
.step { width: 48px; height: 48px; flex: none; display: grid; place-items: center;
        background: var(--surface); border: 1px solid var(--primary); color: var(--primary);
        border-radius: 6px; }
.step:disabled { border-color: var(--line); color: var(--muted); }
.qtybox { display: grid; justify-items: center; }
.qty { width: 72px; min-height: 48px; text-align: center; font-size: 18px; font-weight: 600;
       padding: 0 4px; }
.qtyuom { font-size: 16px; color: var(--muted); }
.amounts { margin-left: auto; display: grid; justify-items: end; gap: 1px; }
.amount { font-size: 18px; }

.confirm { border-top: 1px solid var(--line); padding-top: 10px; display: grid; gap: 8px;
           font-size: 16px; }
.crow2 { display: flex; gap: 8px; }
.crow2 > * { flex: 1; }
.danger { min-height: 48px; background: var(--surface); color: var(--crit);
          border: 1px solid var(--crit); border-radius: 6px; font-weight: 700; font-size: 16px; }

.bill { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 12px; display: grid; gap: 10px; }
.brow { display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
        font-size: 16px; }
.brow.scheme { align-items: flex-start; }
.bwords { display: grid; gap: 2px; min-width: 0; }
.bwords em { font-style: normal; color: var(--muted); font-size: 16px; }
.warnword { color: var(--warn); font-weight: 600; }
.off { color: var(--ok); }
.brow.total { border-top: 1px solid var(--line); padding-top: 10px; }
.big { font-size: 20px; }
.brow.yours { border-top: 1px solid var(--line); padding-top: 10px; color: var(--muted); }

.free { border-top: 1px solid var(--line); padding-top: 10px; display: grid; gap: 6px; }
.fhead { display: flex; align-items: center; gap: 8px; margin: 0; color: var(--ok);
         font-size: 16px; }
.frow { display: flex; justify-content: space-between; gap: 12px; font-size: 16px; }
.fnote { margin: 0; color: var(--muted); font-size: 16px; }

.state { display: grid; justify-items: center; gap: 8px; text-align: center; padding: 28px 16px;
         color: var(--muted); font-size: 16px; }
.state b { color: var(--ink); font-size: 18px; }
.state p { margin: 0; max-width: 300px; }
.state.crit { color: var(--crit); }

.ghost { display: inline-flex; align-items: center; justify-content: center; gap: 6px;
         min-height: 48px; padding: 0 12px; background: var(--surface); color: var(--primary);
         border: 1px solid var(--primary); border-radius: 6px; font-weight: 600; font-size: 16px;
         text-decoration: none; }

.bottom { position: sticky; bottom: 0; margin-top: 12px; padding: 12px 0 4px; display: grid;
          gap: 8px; background: var(--bg); border-top: 1px solid var(--line); }
.sum { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; margin: 0;
       font-size: 16px; }
.grand { font-size: 20px; }
.acts { display: flex; gap: 8px; }
.acts > * { flex: 1; }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 8px;
               min-height: 52px; padding: 14px; border-radius: 6px; text-decoration: none;
               font-size: 16px; }
.assurance { display: flex; align-items: center; justify-content: center; gap: 6px; margin: 0;
             color: var(--muted); font-size: 16px; text-align: center; }
</style>
