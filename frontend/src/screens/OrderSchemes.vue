<script setup>
/**
 * What this order earns, in the words the rep says across the counter.
 *
 * "Why did I get this discount?" is the single most common support call from the field, and this
 * screen exists to end it. Every figure on it comes out of the local engine, so it re-prices with
 * no signal - which is exactly where a rep is standing when a shopkeeper asks.
 *
 * **The one correctness rule this screen is built around.** Free goods are given IN ADDITION and
 * bill at zero. Their value is never subtracted from the bill. `SCHEME_SPEC.md` S9 names two
 * figures that keep getting confused:
 *
 *   discount_paise  what comes OFF THE BILL          <- the only thing a total may subtract
 *   benefit_paise   what the shop RECEIVES in total  <- bill cut PLUS the value of free stock
 *
 * The supplied mock-up showed a benefit of 313.68 and then took all 313.68 off the total, which
 * pays the shop twice: once in stock and once in cash, and the distributor settles a claim for the
 * half nobody authorised. So every card here carries both numbers, labelled, and the totals line
 * only ever subtracts the first. The sentence a rep reads out is "19.68 off, and two free packs" -
 * never "313.68 off".
 *
 * Incentive is the rep's own money and is kept off the shop-facing benefit list for the same
 * reason: a rep reading this aloud must not read out what the shopkeeper was never given.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as role from '../stores/role'

import { t } from '../lib/i18n'
import { db } from '../db'
import { formatPaise } from '../lib/money'
import { isPosmItem } from '../lib/posm'
// The cart screen narrates the same schemes from this file. Anywhere the two screens could put
// different words - or a different quantity - on the same thing, the sentence comes from here, so
// a rep cannot be told one thing on the cart and another one tap later.
import {
  billDiscountPaise,
  droppedWords,
  moneyLabel,
  percentWords,
  planNudge,
  qtyWords,
  slabWords,
  symbolFor,
  totalErrorWords,
} from '../lib/schemeWords'
import * as cart from '../stores/order'
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

// Top-level bindings so the template unwraps them. A module namespace (`cart.totals`) is not
// unwrapped by Vue's template compiler and renders as "[object Object]".
const loading = cart.loading
const storeError = cart.error
const catalogue = cart.catalogue
const lines = cart.lines
const lineCount = cart.lineCount
const isEmpty = cart.isEmpty
const totals = cart.totals
const appliedSchemes = cart.appliedSchemes
const freeGoods = cart.freeGoods
const nearMisses = cart.nearMisses
const droppedSchemes = cart.droppedSchemes
const dataAge = cart.dataAge
const blockers = cart.blockers
const catalogueItems = cart.catalogueItems
const outletName = cart.outletName
const specs = cart.specs

const tier = ref(null)
const refreshing = ref(false)
const adding = ref(null)
const actionError = ref('')

const cartRoute = computed(() => ({ name: 'order-cart', params: { outlet: outlet.value }, query: keepParty.value }))
const catalogueRoute = computed(() => ({ name: 'order-catalogue', params: { outlet: outlet.value }, query: keepParty.value }))
const reviewRoute = computed(() => ({ name: 'order-review', params: { outlet: outlet.value }, query: keepParty.value }))

// -------------------------------------------------------------------------------------- money

// money.js carries no currency symbol on purpose - the catalogue payload names the outlet's own
// currency, and a helper that hard-coded a rupee sign would be wrong the first time this ships
// anywhere it is not one. `schemeWords` is the display layer where the symbol belongs.
const sym = computed(() => symbolFor(totals.value.currency))
function money(paise) {
  return moneyLabel(paise, totals.value.currency)
}

// ------------------------------------------------------------------------------------ lookups

const itemIndex = computed(() => new Map(catalogueItems.value.map((i) => [i.item_code, i])))
const specIndex = computed(() => new Map((specs.value || []).map((s) => [s.scheme, s])))

function specFor(scheme) {
  return specIndex.value.get(scheme) || null
}
function slabOf(spec, idx) {
  if (!spec) return null
  return (spec.slabs || []).find((s) => Number(s.idx) === Number(idx)) || null
}
function itemName(code) {
  return itemIndex.value.get(code)?.item_name || code || t('item')
}
function freeUomFor(code) {
  return itemIndex.value.get(code)?.stock_uom || null
}

/** The shared narration helpers all take the same context. Built once, here. */
const words = computed(() => ({
  currency: totals.value.currency,
  nameFor: itemName,
  freeUomFor,
}))

/**
 * The unit a Qty slab is counted in, named rather than left as a bare "units".
 *
 * Slabs are stored in base units (SCHEME_SPEC S3), so a scheme scoped to one brand of flour reads
 * out as "15 Bags" rather than "15 units". Where the qualifying items disagree about their base
 * unit - or the scheme measures the whole order - there is no honest single name for it and it
 * stays "units".
 */
function unitFor(spec) {
  if (!spec || spec.basis === 'Value') return t('units')
  if (spec.measured_over === 'Order') return t('units')
  const uoms = new Set()
  for (const code of spec.qualifying_items || []) {
    const item = itemIndex.value.get(code)
    if (item && item.stock_uom) uoms.add(item.stock_uom)
  }
  // The unit itself is an ERPNext master value and stays as the server names it. Only the
  // fallback word is ours.
  return uoms.size === 1 ? [...uoms][0] : t('units')
}

function measureText(spec, basis, value) {
  return basis === 'Value'
    ? money(value)
    : t('{n} {unit}', { n: value, unit: unitFor(spec) })
}

// ------------------------------------------------------------------------------------ applied

const DISCOUNT_KINDS = ['Percent Discount', 'Value Discount', 'Rate Off']

/**
 * One applied scheme, spelled out.
 *
 * `off` and `benefit` stay separate all the way to the template. `off` is the only figure the bill
 * may subtract; `benefit` is what the shop walks away with, free stock included.
 */
const earned = computed(() =>
  appliedSchemes.value.map((entry) => {
    const spec = specFor(entry.scheme)
    const slab = slabOf(spec, entry.slab_idx)
    const basis = entry.basis || (spec && spec.basis) || 'Qty'
    const raw = (slab && slab.benefits) || []
    const percents = raw.filter((b) => b.kind === 'Percent Discount')

    // `billDiscountPaise` is shared with the cart screen so the two cannot disagree about what
    // comes off this bill. The phrases below are this screen's own: a card the rep reads aloud
    // names the rupees the scheme actually produced, where the cart's badge names the offer.
    const off = billDiscountPaise(entry)
    const gets = []
    const mine = []
    for (const b of entry.benefits || []) {
      if (b.kind === 'Incentive') {
        mine.push(t('{amount} incentive for you',
                    { amount: money(b.amount_paise) }))
        continue
      }
      if (b.kind === 'Free Goods') {
        gets.push({
          text: t('{qty} {item} free', {
            qty: qtyWords(b.qty, freeUomFor(b.item)),
            item: itemName(b.item),
          }),
          free: true,
        })
        continue
      }
      if (DISCOUNT_KINDS.includes(b.kind)) {
        // The rate is named beside the rupees only when the slab carries exactly one percentage.
        // The engine skips benefit kinds it does not know, so positions in the two arrays can
        // diverge, and matching by index would eventually put the wrong rate on the wrong money.
        const named = b.kind === 'Percent Discount' && percents.length === 1
        gets.push({
          text: named
            ? t('{amount} off the bill ({pct})', {
                amount: money(b.amount_paise),
                pct: percentWords(percents[0].pct_bp),
              })
            : t('{amount} off the bill', { amount: money(b.amount_paise) }),
          free: false,
        })
      }
    }

    let slabText = null
    if (slab) {
      const from = basis === 'Value' ? money(slab.from) : String(slab.from)
      const open = slab.to === null || slab.to === undefined
      const unit = basis === 'Value' ? '' : ` ${unitFor(spec)}`
      slabText = open
        ? t('Slab met: {from}+{unit}', { from, unit })
        : t('Slab met: {from} to {to}{unit}', {
            from,
            to: basis === 'Value' ? money(slab.to) : slab.to,
            unit,
          })
    }

    return {
      ...entry,
      gets,
      mine,
      off,
      slabText,
      have: measureText(spec, basis, entry.measure),
      freeUnits: (entry.benefits || [])
        .filter((b) => b.kind === 'Free Goods')
        .reduce((sum, b) => sum + (b.qty || 0), 0),
    }
  })
)

/**
 * The cards, and the schemes that never belonged on them.
 *
 * A scheme whose only benefit is an Incentive applied, and gave the shopkeeper nothing. Under a
 * heading that says "what the shop has earned" it rendered as a card reading "off this bill 0.00,
 * benefit value 0.00" - which invites a rep to read out a benefit that does not exist and buries
 * the schemes that do. It belongs with the rep's own money, which is the banner below.
 */
const shopEarned = computed(() => earned.value.filter((s) => s.gets.length > 0))
const repOnly = computed(() =>
  earned.value.filter((s) => s.gets.length === 0 && s.mine.length > 0)
)

// -------------------------------------------------------------------------------- near misses

/**
 * The next rung, and the exact quantity that reaches it.
 *
 * SCHEME_SPEC S10 only emits a near miss that can actually be reached, and never for a scheme that
 * was dropped for budget or stacking - so everything in this list is a nudge the rep can act on
 * and collect. What the rung *gives* is described rather than priced: on a Qty slab the qualifying
 * gross at that point is unknown, and quoting a rupee figure we cannot compute is the one mistake
 * that has a rep taking a number back across a counter.
 */
const rungs = computed(() =>
  nearMisses.value.map((nm) => {
    const spec = specFor(nm.scheme)
    const slab = slabOf(spec, nm.slab_idx)
    const target = slab ? Number(slab.from) : null
    const pct =
      target && target > 0
        ? Math.max(2, Math.min(100, Math.round((nm.measure / target) * 100)))
        : null

    // The rung is described, not priced. `slabWords` is the same sentence the cart screen puts on
    // this offer, and the incentive is pulled back out of it so it is never read to a shopkeeper.
    const mine = ((slab && slab.benefits) || [])
      .filter((b) => b.kind === 'Incentive')
      .map((b) => `${money(b.amount_paise)} incentive for you`)
    const shopSlab = slab
      ? { ...slab, benefits: (slab.benefits || []).filter((b) => b.kind !== 'Incentive') }
      : null
    const gives = shopSlab ? slabWords(spec, shopSlab, words.value) : null

    return {
      ...nm,
      target,
      pct,
      gives,
      mine,
      have: measureText(spec, nm.basis, nm.measure),
      need: target === null ? null : measureText(spec, nm.basis, target),
      short: nm.basis === 'Value'
        ? money(nm.gap_paise)
        : t('{n} {unit}', { n: nm.gap_units, unit: unitFor(spec) }),
      // Shared with the cart screen, deliberately. Two screens that each worked out "how much more"
      // for themselves would eventually offer a rep two different quantities for the same nudge -
      // and this is the one number on the screen a rep acts on without checking. It also buys the
      // whole case rather than a part of one, and returns null rather than a button that would
      // push the line past what this shop may order.
      add: planNudge(nm, spec, lines.value),
    }
  })
)

async function addTheGap(rung) {
  if (!rung.add || adding.value) return
  actionError.value = ''
  adding.value = rung.scheme
  try {
    await cart.bumpQty(rung.add.item_code, rung.add.add_base, { unit: 'base' })
  } catch (e) {
    actionError.value =
      (e && e.message)
      || t('Could not add that here. Open the cart and change the quantity there.')
  } finally {
    adding.value = null
  }
}

// --------------------------------------------------------------------------------- free goods

// Display material is dispatched and it costs money, but it is not a sale. `lib/posm.js` owns the
// rule so this screen and the review screen cannot disagree about it - they did, and the same
// order read as "1 free unit" here and "3 free units" one screen later.
function isPosm(row) {
  return isPosmItem(itemIndex.value.get(row.item_code))
}

const freeSaleable = computed(() => freeGoods.value.filter((row) => !isPosm(row)))
const freePosm = computed(() => freeGoods.value.filter((row) => isPosm(row)))
const freeUnitCount = computed(() =>
  freeSaleable.value.reduce((sum, row) => sum + (row.qty || 0), 0)
)

// ------------------------------------------------------------------------------------ dropped

// The reason is spoken by `schemeWords.droppedWords`, not by a table in here: the cart screen says
// the same thing about the same scheme, and two sentences for one state is how a rep decides the
// app is guessing.
const notApplied = computed(() =>
  droppedSchemes.value.map((row) => ({ ...row, why: droppedWords(row.reason) }))
)

// ---------------------------------------------------------------------------------- freshness

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

const schemesAge = computed(() => ago(dataAge.value.schemes.ageMs))
const schemesStale = computed(() => dataAge.value.schemes.stale)
const hasSpecs = computed(() => (specs.value || []).length > 0)

// Only the blockers a rep can act on. EMPTY has its own designed state below.
const warnings = computed(() => blockers.value.filter((b) => b.code !== 'EMPTY'))

async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  actionError.value = ''
  try {
    await cart.refreshAll()
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  if (!outlet.value) return router.replace(role.homeRoute.value)
  // Already open on this shop: the rep walked in from the cart and everything is priced. Opening
  // again would spend a round trip and re-read a cart that is already on the screen.
  if (cart.outlet.value !== outlet.value || !catalogue.value) {
    await cart.openOutlet(outlet.value, { type: partyType.value })
  }
  const shop = await db.records.get(['FieldMate Outlet', outlet.value])
  tier.value = (shop && shop.outlet_class) || null
  if (!outletName.value) outletName.value = (shop && shop.outlet_name) || outlet.value
})
</script>

<template>
  <div class="wrap screen">
    <div class="top">
      <RouterLink class="crumb" :to="cartRoute">
        <Icon name="back" size="18" /> <span>{{ t('Back to the cart') }}</span>
      </RouterLink>

      <header>
        <div class="idline">
          <h2>{{ outletName || outlet }}</h2>
          <span v-if="tier" class="tag">{{ tier }}</span>
        </div>
        <p class="sub">
          <span>{{ t('What this order earns') }}</span>
          <button type="button" class="linkbtn" @click="refresh" :disabled="refreshing">
            <Icon name="refresh" size="16" />
            <span>{{ refreshing ? t('Refreshing…') : t('Refresh offers') }}</span>
          </button>
        </p>
      </header>

      <!-- Loading is a designed state, not a blank screen. -->
      <div v-if="loading && !catalogue" class="card">
        <b>{{ t('Working out what this order earns…') }}</b>
        <p class="muted">{{ t('One moment.') }}</p>
      </div>

      <template v-else>
        <p v-if="storeError" class="note crit" role="alert">
          <Icon name="alert" size="18" /><span>{{ storeError }}</span>
        </p>

        <!-- An empty cart is not an error. There is simply nothing to price yet. -->
        <div v-if="isEmpty" class="card empty">
          <b>{{ t('Nothing in this order yet') }}</b>
          <p class="muted">
            {{ t('Schemes are worked out from what is in the cart.') }}
            {{ t('Add a few items and every discount and free pack this shop has earned appears here.') }}
          </p>
        </div>

        <template v-else>
          <!-- The four figures. The two that keep getting confused are kept apart on purpose:
               "Off this bill" is the only one the total subtracts. -->
          <div class="tiles">
            <div class="tile">
              <span class="label">{{ t('Order value') }}</span>
              <b class="value tnum">{{ sym }}{{ totals.gross }}</b>
            </div>
            <div class="tile">
              <span class="label">{{ t('Items') }}</span>
              <b class="value tnum">{{ lineCount }}</b>
            </div>
            <div class="tile good">
              <span class="label">{{ t('Off this bill') }}</span>
              <b class="value tnum">{{ sym }}{{ totals.discount }}</b>
            </div>
            <div class="tile">
              <span class="label">{{ t('Free stock') }}</span>
              <b class="value tnum">{{ freeUnitCount }}</b>
              <span class="label">
                {{ freeUnitCount === 1
                    ? t('unit, billed at zero')
                    : t('units, billed at zero') }}
              </span>
            </div>
          </div>

          <p v-if="totals.incentive_paise > 0" class="note mine">
            <Icon name="person" size="18" />
            <span>
              {{ t('This order pays you') }}
              <b class="tnum">{{ sym }}{{ totals.incentive }}</b>
              <template v-if="repOnly.length">
                ({{ repOnly.map((s) => s.scheme_name || s.scheme).join(', ') }})</template>.
              {{ t('It is not on the shop’s bill and is not read out to them.') }}
            </span>
          </p>

          <p v-for="code in totals.errors" :key="code" class="note crit" role="alert">
            <Icon name="alert" size="18" />
            <span class="tnum">{{ totalErrorWords(code) }}</span>
          </p>

          <p v-if="schemesStale" class="note warn">
            <Icon name="cloud-off" size="18" />
            <span>
              {{ t('These offers were last updated') }}
              <b>{{ schemesAge || t('a while ago') }}</b>.
              {{ t('They still price the order.') }}
              {{ t('Connect once to bring in anything new.') }}
            </span>
          </p>

          <RouterLink v-if="warnings.length" class="note warn" :to="cartRoute">
            <Icon name="alert" size="18" />
            <span>{{ warnings[0].message }} <b>{{ t('Open the cart to fix it.') }}</b></span>
          </RouterLink>

          <p v-if="actionError" class="note crit" role="alert">
            <Icon name="alert" size="18" /><span>{{ actionError }}</span>
          </p>

          <!-- ------------------------------------------------------------------ applied -->
          <div class="section">
            <h3>{{ t('What the shop has earned') }}</h3>
            <span class="muted tnum">{{ shopEarned.length }}</span>
          </div>

          <div v-if="!shopEarned.length" class="card empty">
            <b v-if="!hasSpecs">
              {{ t('No offers have reached this phone for this shop') }}
            </b>
            <b v-else>{{ t('This order has not earned a scheme yet') }}</b>
            <p class="muted" v-if="!hasSpecs">
              {{ t('Connect once and the shop’s offers download for good.') }}
              {{ t('The order can still be taken and sent without them.') }}
            </p>
            <p class="muted" v-else-if="rungs.length">
              {{ t('Nothing has crossed a slab yet.') }}
              {{ t('The next rung, and exactly how much it takes, is just below.') }}
            </p>
            <p class="muted" v-else>
              {{ t('Nothing in this order qualifies for one of this shop’s offers.') }}
            </p>
          </div>

          <article v-for="s in shopEarned" :key="s.scheme" class="card scheme">
            <div class="crown">
              <span class="stamp">
                <Icon name="check" size="18" /> <span>{{ t('Applied') }}</span>
              </span>
              <span v-if="s.budget_warning" class="pill warn">{{ t('Past its budget') }}</span>
            </div>

            <h4>{{ s.scheme_name || s.scheme }}</h4>
            <p v-if="s.rep_pitch" class="pitch">&ldquo;{{ s.rep_pitch }}&rdquo;</p>

            <p v-if="s.slabText" class="slab tnum">
              {{ s.slabText }} &middot; {{ t('you have {have}', { have: s.have }) }}
            </p>

            <ul class="gets">
              <li v-for="(g, i) in s.gets" :key="i" :class="{ free: g.free }">
                <Icon :name="g.free ? 'plus' : 'check'" size="18" />
                <span class="tnum">{{ g.text }}</span>
              </li>
            </ul>

            <!-- The two numbers side by side, because collapsing them into one "saved" figure is
                 the mistake that pays the shop twice. -->
            <div class="split">
              <div>
                <span class="label">{{ t('Off this bill') }}</span>
                <b class="tnum ok">{{ sym }}{{ formatPaise(s.off) }}</b>
              </div>
              <div>
                <span class="label">{{ t('Benefit value') }}</span>
                <b class="tnum">{{ sym }}{{ s.benefit }}</b>
              </div>
            </div>
            <p class="foot" v-if="s.freeUnits">
              {{ t('The free stock ships in addition at zero. Only the') }}
              <b class="tnum">{{ sym }}{{ formatPaise(s.off) }}</b>
              {{ t('comes off the total.') }}
            </p>

            <p v-for="(m, i) in s.mine" :key="'m' + i" class="foot mineline">
              <Icon name="person" size="16" />
              <span class="tnum">{{ m }} &middot; {{ t('not the shop’s') }}</span>
            </p>
          </article>

          <!-- -------------------------------------------------------------- near misses -->
          <div class="section">
            <h3>{{ t('One more step') }}</h3>
            <span class="muted tnum">{{ rungs.length }}</span>
          </div>

          <!-- A near miss is only ever emitted when it can actually be reached, so an empty list
               is real news rather than a missing box. -->
          <div v-if="!rungs.length" class="card empty">
            <b v-if="shopEarned.length">{{ t('Nothing more to unlock') }}</b>
            <b v-else-if="hasSpecs">{{ t('No slab is within reach on this order') }}</b>
            <b v-else>{{ t('No offers on this phone to work towards') }}</b>
            <p class="muted" v-if="shopEarned.length">
              {{ t('Every offer this order qualifies for is already at its top slab.') }}
              {{ t('Adding more will not change the discount.') }}
            </p>
            <p class="muted" v-else-if="hasSpecs">
              {{ t('None of this shop’s offers cover what is in the cart.') }}
              {{ t('Check the catalogue for items that carry one.') }}
            </p>
          </div>

          <article v-for="r in rungs" :key="r.scheme" class="card rung">
            <h4>{{ r.scheme_name || r.scheme }}</h4>
            <p class="short tnum">
              <Icon name="alert" size="18" />
              <span><b>{{ r.short }}</b> {{ t('short of the next slab') }}</span>
            </p>

            <ul class="gets" v-if="r.gives">
              <li>
                <Icon name="chevron" size="18" /><span class="tnum">{{ r.gives }}</span>
              </li>
            </ul>

            <div v-if="r.pct !== null" class="track" role="progressbar"
                 :aria-valuenow="r.pct" aria-valuemin="0" aria-valuemax="100"
                 :aria-label="t('{scheme} progress to the next slab',
                                { scheme: r.scheme_name || r.scheme })">
              <div class="fill" :style="{ width: r.pct + '%' }"></div>
            </div>
            <p v-if="r.need" class="meter tnum">
              {{ t('{have} of {need}', { have: r.have, need: r.need }) }}
            </p>

            <template v-if="r.add">
              <button type="button" class="btn-add"
                      :disabled="adding === r.scheme" @click="addTheGap(r)">
                <Icon name="plus" size="20" />
                <span class="tnum">
                  {{ adding === r.scheme
                     ? t('Adding…')
                     : t('Add {qty} of {item}', {
                         qty: qtyWords(r.add.add_display, r.add.add_uom),
                         item: r.add.item_name }) }}
                </span>
              </button>
              <p class="foot tnum">
                {{ t('Adds {amount} to the order.',
                     { amount: sym + formatPaise(r.add.cost_paise) }) }}
              </p>
            </template>
            <!-- No honest one-tap: nothing qualifying in the cart to add to, or every candidate
                 already at the most this shop may order. Said, rather than a dead button. -->
            <p v-else class="foot">
              {{ t('Add more of the items this offer covers to reach it.') }}
            </p>

            <p v-for="(m, i) in r.mine" :key="'rm' + i" class="foot mineline">
              <Icon name="person" size="16" />
              <span class="tnum">{{ m }} &middot; {{ t('not the shop’s') }}</span>
            </p>
          </article>

          <!-- --------------------------------------------------------------- free goods -->
          <template v-if="freeSaleable.length || freePosm.length">
            <div class="section"><h3>{{ t('Going with the order, free') }}</h3></div>
            <p class="lead">
              {{ t('Dispatched at {zero} in addition to what is billed.',
                   { zero: sym + '0.00' }) }}
              {{ t('Their value is') }} <b>{{ t('not') }}</b>
              {{ t('taken off the total.') }}
            </p>

            <div v-if="freeSaleable.length" class="card frees">
              <div v-for="row in freeSaleable" :key="'f' + row.item_code + row.scheme" class="frow">
                <span class="qty tnum">{{ row.qty }}</span>
                <span class="fbody">
                  <b>{{ row.item_name }}</b>
                  <span class="muted tnum">
                    {{ row.uom || 'units' }}
                    <template v-if="row.scheme_name"> &middot; {{ row.scheme_name }}</template>
                  </span>
                </span>
                <span class="fval muted tnum">
                  {{ t('value {amount}', { amount: sym + row.value }) }}
                </span>
              </div>
            </div>

            <!-- POSM is dispatched and it costs money, but it is not a sale. Kept apart so it is
                 never read as volume. -->
            <div v-if="freePosm.length" class="card frees posm">
              <p class="posmhead">
                <Icon name="shelves" size="18" />
                <span>
                  {{ t('Display material — dispatched, never billed, never counted as a sale.') }}
                </span>
              </p>
              <div v-for="row in freePosm" :key="'p' + row.item_code + row.scheme" class="frow">
                <span class="qty tnum">{{ row.qty }}</span>
                <span class="fbody">
                  <b>{{ row.item_name }}</b>
                  <span class="muted tnum">
                    {{ row.uom || 'units' }}
                    <template v-if="row.scheme_name"> &middot; {{ row.scheme_name }}</template>
                  </span>
                </span>
                <span class="fval muted">POSM</span>
              </div>
            </div>
          </template>

          <!-- ------------------------------------------------------------------ dropped -->
          <template v-if="notApplied.length">
            <div class="section"><h3>{{ t('Not applied') }}</h3></div>
            <div class="card quiet">
              <div v-for="d in notApplied" :key="d.scheme" class="drow">
                <b>{{ d.scheme_name || d.scheme }}</b>
                <span class="muted">{{ d.why }}</span>
              </div>
            </div>
          </template>

          <p class="muted age tnum" v-if="schemesAge">
            {{ t('Offers refreshed {age}.', { age: schemesAge }) }}
          </p>
        </template>
      </template>
    </div>

    <!-- The commitment line. Two figures, never one: what comes off the bill, and what ships
         free beside it. -->
    <div class="bottom">
      <template v-if="!isEmpty">
        <div class="tally">
          <span class="tnum">
            <b class="ok">{{ sym }}{{ totals.discount }}</b> {{ t('off the bill') }}
            <template v-if="freeUnitCount">
              &middot; <b>{{ freeUnitCount }}</b>
              {{ freeUnitCount === 1 ? t('free unit') : t('free units') }}
            </template>
          </span>
        </div>
        <div class="payline">
          <span>{{ t('Net payable') }}</span>
          <b class="net tnum">{{ sym }}{{ totals.net }}</b>
        </div>
        <button class="btn-primary" @click="router.push(reviewRoute)">
          {{ t('Review the order') }}
        </button>
        <button class="btn-plain" @click="router.push(cartRoute)">
          {{ t('Back to the cart') }}
        </button>
      </template>
      <button v-else class="btn-primary" @click="router.push(catalogueRoute)">
        {{ t('Add items to this order') }}
      </button>
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
h4 { margin: 0 0 2px; font-size: 18px; overflow-wrap: anywhere; }
.idline { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sub { display: flex; align-items: center; justify-content: space-between; gap: 8px;
       margin: 4px 0 0; color: var(--muted); font-size: 14px; }
.tag { font-size: 14px; font-weight: 600; padding: 3px 8px; border-radius: 4px;
       background: var(--primary-soft); color: var(--primary); }
.linkbtn { display: inline-flex; align-items: center; gap: 6px; background: none; border: 0;
           color: var(--primary); font-weight: 600; font-size: 14px; padding: 0 4px;
           min-height: 48px; }
.linkbtn:disabled { color: var(--muted); }

.muted { color: var(--muted); font-size: 14px; }
.lead { margin: 0; font-size: 16px; }
.age { margin: 4px 0 0; }
.ok { color: var(--ok); }
.warn-text { color: var(--warn); }

.section { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
           margin-top: 8px; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; display: grid; gap: 8px; }
.card.empty { gap: 4px; }
.card.empty b { font-size: 16px; }
.card.empty p { font-size: 16px; }
.card.quiet { background: var(--bg); }

/* Two across at 360px. Four columns would put an eight-character total in 82px. */
.tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 10px 12px; display: grid; gap: 2px; align-content: start; }
.tile.good { background: var(--ok-soft); border-color: var(--ok); }
.tile.good .value { color: var(--ok); }
.label { font-size: 14px; color: var(--muted); }
.value { font-size: 20px; line-height: 1.25; overflow-wrap: anywhere; }

 /* An error or a warning is copy the rep has to act on, so it holds the 16px floor even
    though labels and captions around it sit at the house 14px. */
.note { display: flex; gap: 8px; align-items: flex-start; margin: 0; padding: 12px;
        border-radius: 6px; font-size: 16px; text-decoration: none; }
.note.warn { background: var(--warn-soft); color: var(--warn); border: 1px solid var(--warn); }
.note.crit { background: var(--crit-soft); color: var(--crit); border: 1px solid var(--crit); }
.note.mine { background: var(--primary-soft); color: var(--primary); }
.note svg { flex: none; margin-top: 2px; }

.scheme { border-left: 4px solid var(--ok); }
.rung { border-left: 4px solid var(--warn); }
.crown { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.stamp { display: inline-flex; align-items: center; gap: 6px; font-size: 14px; font-weight: 600;
         color: var(--ok); }
.pill { font-size: 14px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.pill.warn { background: var(--warn-soft); color: var(--warn); border: 1px solid var(--warn); }
.pitch { margin: 0; font-size: 16px; }
.slab { margin: 0; font-size: 14px; color: var(--muted); }

.gets { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.gets li { display: flex; gap: 8px; align-items: flex-start; font-size: 16px; }
.gets li svg { margin-top: 3px; flex: none; color: var(--muted); }
.gets li.free svg { color: var(--ok); }

.split { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding-top: 8px;
         border-top: 1px solid var(--line); }
.split b { font-size: 18px; display: block; }
.foot { margin: 0; font-size: 14px; color: var(--muted); }
.mineline { display: flex; align-items: center; gap: 6px; }

.short { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 16px;
         color: var(--warn); }
.short svg { flex: none; }
.track { height: 10px; border-radius: 5px; background: var(--primary-soft); overflow: hidden; }
.fill { display: block; height: 100%; background: var(--accent); transition: width 120ms linear; }
.meter { margin: 0; font-size: 14px; color: var(--muted); }

.btn-add { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%;
           min-height: 48px; padding: 0 12px; border-radius: 6px; font-weight: 600;
           background: var(--primary-soft); border: 1px solid var(--primary);
           color: var(--primary); }
.btn-add:disabled { opacity: 0.6; }

.frees { gap: 0; }
.frow { display: flex; align-items: center; gap: 10px; padding: 10px 0;
        border-top: 1px solid var(--line); }
.frow:first-of-type { border-top: 0; }
.qty { flex: none; min-width: 40px; height: 40px; display: grid; place-items: center;
       border-radius: 6px; background: var(--ok-soft); color: var(--ok); font-weight: 600;
       font-size: 18px; padding: 0 6px; }
.fbody { flex: 1; display: grid; gap: 2px; min-width: 0; }
.fbody b { font-size: 16px; overflow-wrap: anywhere; }
.fval { flex: none; font-size: 14px; }
.posm { background: var(--bg); }
.posm .qty { background: var(--primary-soft); color: var(--primary); }
.posmhead { display: flex; gap: 8px; align-items: flex-start; margin: 0 0 4px;
            font-size: 14px; color: var(--muted); }
.posmhead svg { flex: none; margin-top: 2px; }

.drow { display: grid; gap: 2px; padding: 10px 0; border-top: 1px solid var(--line); }
.drow:first-of-type { border-top: 0; padding-top: 0; }
.drow b { font-size: 16px; }

.bottom { position: sticky; bottom: 0; padding: 10px 0 4px; margin-top: 16px;
          background: var(--bg); border-top: 1px solid var(--line); display: grid; gap: 8px; }
.tally { font-size: 14px; color: var(--muted); }
.payline { display: flex; align-items: baseline; justify-content: space-between; gap: 8px;
           font-size: 16px; }
.net { font-size: 20px; font-weight: 700; }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               padding: 14px; min-height: 52px; border-radius: 6px; width: 100%; }
.btn-plain { background: none; border: 1px solid var(--line); color: var(--ink); width: 100%;
             min-height: 48px; }

@media (prefers-reduced-motion: reduce) {
  .fill { transition: none; }
}
</style>
