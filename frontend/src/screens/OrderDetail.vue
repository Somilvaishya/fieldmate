<script setup>
/**
 * One order, in full.
 *
 * The list used to carry everything: the lines count, the status, and a Cancel button on every
 * card. Two things were wrong with that. A rep scanning their day read a wall of controls instead
 * of a list, and the one destructive action in the app sat under the thumb on every row. And the
 * list could never answer the question a rep actually opens it with - *what was in that order?* -
 * because `list_mine` sends a count and not the lines.
 *
 * So the list is a list, and this is the record. Everything the server knows about the order is
 * here, and cancelling lives at the bottom behind its own confirmation, where a thumb reaches it
 * on purpose rather than by brushing past.
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const route = useRoute()
const router = useRouter()

const order = ref(null)
const loading = ref(true)
const error = ref('')

const name = computed(() => route.params.name)

const WORDS = computed(() => ({
  'Draft': t('Not sent'),
  'Pending Approval': t('Waiting on your manager'),
  'Awaiting Advance': t('Waiting for the advance'),
  'Approved': t('Approved'),
  'Sent To Distributor': t('With the depot'),
  'Accepted': t('Depot accepted'),
  'Invoiced': t('Depot billed it'),
  'Delivered': t('Delivered'),
  'Rejected': t('Refused'),
  'Cancelled': t('Cancelled'),
}))
const TONE = {
  'Pending Approval': 'warn',
  'Awaiting Advance': 'warn',
  'Rejected': 'crit',
  'Cancelled': 'crit',
  'Delivered': 'ok',
  'Invoiced': 'ok',
  'Accepted': 'ok',
}

/** Who it was for. A primary order has no outlet at all, which is not missing data. */
const partyName = computed(() => {
  const o = order.value
  if (!o) return ''
  return o.outlet_name || o.customer_name || o.outlet || o.customer || o.name
})
const partyId = computed(() => order.value?.outlet || order.value?.customer || '')

/** What the party is billed. The net is the goods; the bill carries the tax on top. */
const billTotal = computed(() => {
  const o = order.value
  if (!o) return 0
  return Number(o.grand_total) || Number(o.net_total) || 0
})

const isBooking = computed(() => order.value?.order_kind === 'Booking')

function day(value) {
  if (!value) return ''
  const [y, m, d] = String(value).slice(0, 10).split('-')
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${Number(d)} ${months[Number(m) - 1]} ${y}`
}

function qtyWords(line) {
  const shown = Number(line.qty_display) || Number(line.qty) || 0
  const unit = line.display_uom || line.uom || line.stock_uom || ''
  const base = Number(line.qty) || 0
  const baseUnit = line.stock_uom || ''
  // Only where the two differ: "2 Cases" with "24 Nos" under it says something, "2 Nos" with
  // "2 Nos" under it is noise.
  const same = !unit || !baseUnit || unit === baseUnit
  return { shown: `${shown} ${unit}`.trim(), base: same ? '' : `${base} ${baseUnit}`.trim() }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.orderDetail(name.value)
    order.value = data.order || data
  } catch (e) {
    error.value = e instanceof ApiError
      ? e.message
      : t('Could not open this order. It lives on the server, so it needs signal.')
  } finally {
    loading.value = false
  }
}

// ------------------------------------------------------------------------------- cancelling

// A rep may withdraw their own order right up to the point the depot bills it. After that the
// goods and the paperwork have moved and it is a return, not a cancellation - the server refuses
// those too, so this screen and that rule have to agree.
const DEPOT_HAS_ACTED = ['Invoiced', 'Delivered']
const DONE = ['Cancelled', 'Rejected']

const canCancel = computed(() => {
  const s = order.value?.order_status
  return !!s && !DEPOT_HAS_ACTED.includes(s) && !DONE.includes(s)
})

const confirming = ref(false)
const reason = ref('')
const cancelling = ref(false)
const cancelError = ref('')

function askCancel() {
  confirming.value = true
  reason.value = ''
  cancelError.value = ''
}

function keepIt() {
  confirming.value = false
  reason.value = ''
  cancelError.value = ''
}

async function doCancel() {
  cancelling.value = true
  cancelError.value = ''
  try {
    await api.orderCancel(order.value.name, reason.value.trim() || null)
    keepIt()
    // Re-read rather than patching the record here: cancelling also hands scheme budget back,
    // and the server is the only thing that knows what the order looks like afterwards.
    await load()
  } catch (e) {
    cancelError.value = e instanceof ApiError
      ? e.message
      : t('Could not cancel it. This needs signal — try again when you have some.')
  } finally {
    cancelling.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="wrap screen">
    <header class="head">
      <button class="back" type="button" @click="router.back()" :aria-label="t('Back to orders')">
        <Icon name="back" size="24" />
      </button>
      <div class="who">
        <h1>{{ t('Order') }}</h1>
        <p class="dim mono">{{ name }}</p>
      </div>
      <button class="quiet" :disabled="loading" @click="load" :aria-label="t('Refresh')">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <p v-if="loading" class="note">{{ t('Loading…') }}</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else-if="order">
      <!-- Who, what it comes to, and where it has reached. The three facts a rep opens an
           order to check, before anything else on the screen. -->
      <section class="card lead">
        <div class="leadtop">
          <div class="party">
            <b class="pname">{{ partyName }}</b>
            <span v-if="partyId && partyId !== partyName" class="dim mono">{{ partyId }}</span>
          </div>
          <span class="pill" :class="TONE[order.order_status] || 'flat'">
            {{ WORDS[order.order_status] || order.order_status }}
          </span>
        </div>
        <div class="leadsum">
          <b class="big tnum">{{ formatRupees(billTotal) }}</b>
          <span class="dim">{{ day(order.order_date) }}</span>
        </div>
        <RouterLink v-if="isBooking" class="pill book" to="/bookings">
          <Icon name="tag" size="16" /> {{ order.season || t('Booking') }}
        </RouterLink>
      </section>

      <!-- The lines. The whole reason this screen exists: the list could only ever say how
           many there were. -->
      <section class="card">
        <h2>{{ t('What was ordered') }}</h2>
        <ul class="lines">
          <li v-for="(line, i) in order.items || []" :key="line.item_code + i" class="line">
            <div class="lname">
              <b>{{ line.item_name || line.item_code }}</b>
              <span class="dim mono">{{ line.item_code }}</span>
              <span v-if="line.is_free_item" class="pill ok small">{{ t('Free') }}</span>
              <span v-if="line.scheme_name" class="dim">{{ line.scheme_name }}</span>
            </div>
            <div class="lqty">
              <span class="tnum">{{ qtyWords(line).shown }}</span>
              <span v-if="qtyWords(line).base" class="dim tnum">{{ qtyWords(line).base }}</span>
            </div>
            <div class="lamt">
              <b class="tnum">{{ formatRupees(line.amount) }}</b>
              <span v-if="Number(line.discount_amount)" class="dim tnum">
                {{ t('less {amount}', { amount: formatRupees(line.discount_amount) }) }}
              </span>
            </div>
          </li>
        </ul>
        <p v-if="!(order.items || []).length" class="dim">{{ t('No lines on this order.') }}</p>
      </section>

      <!-- Free goods are listed apart from the money, never folded into it. Stock the depot
           supplies and claims back is not a discount on this bill. -->
      <section v-if="(order.free_goods || []).length" class="card">
        <h2>{{ t('Free goods') }}</h2>
        <ul class="lines">
          <li v-for="(f, i) in order.free_goods" :key="f.item + i" class="line">
            <div class="lname"><b>{{ f.item }}</b></div>
            <div class="lqty tnum">{{ f.qty }}</div>
            <div class="lamt dim">{{ t('at no charge') }}</div>
          </li>
        </ul>
      </section>

      <section v-if="(order.schemes || []).length" class="card">
        <h2>{{ t('Offers applied') }}</h2>
        <ul class="lines">
          <li v-for="(s, i) in order.schemes" :key="(s.scheme || '') + i" class="line">
            <div class="lname">
              <b>{{ s.name || s.scheme }}</b>
              <span v-if="s.description" class="dim">{{ s.description }}</span>
            </div>
            <div class="lamt"><b class="tnum">{{ formatRupees(s.benefit) }}</b></div>
          </li>
        </ul>
      </section>

      <section class="card">
        <h2>{{ t('What the party pays') }}</h2>
        <div class="kv"><span>{{ t('Goods') }}</span><b class="tnum">{{ formatRupees(order.gross_total) }}</b></div>
        <div v-if="Number(order.discount_total)" class="kv">
          <span>{{ t('Offers') }}</span>
          <b class="tnum ok">− {{ formatRupees(order.discount_total) }}</b>
        </div>
        <div class="kv"><span>{{ t('Net') }}</span><b class="tnum">{{ formatRupees(order.net_total) }}</b></div>
        <div v-if="Number(order.tax_total)" class="kv">
          <span>{{ t('GST') }}</span><b class="tnum">{{ formatRupees(order.tax_total) }}</b>
        </div>
        <div class="kv total">
          <span>{{ t('Bill total') }}</span><b class="tnum">{{ formatRupees(billTotal) }}</b>
        </div>
      </section>

      <section class="card">
        <h2>{{ t('Where it has reached') }}</h2>
        <div class="kv"><span>{{ t('Booked on') }}</span><b>{{ day(order.order_date) }}</b></div>
        <div v-if="order.sent_to_distributor_on" class="kv">
          <span>{{ t('Sent to the depot') }}</span><b>{{ day(order.sent_to_distributor_on) }}</b>
        </div>
        <div v-if="order.distributor" class="kv">
          <span>{{ t('Depot') }}</span><b>{{ order.distributor }}</b>
        </div>
        <div v-if="order.expected_delivery_date" class="kv">
          <span>{{ t('Delivery expected') }}</span><b>{{ day(order.expected_delivery_date) }}</b>
        </div>
        <div v-if="order.credit_status" class="kv">
          <span>{{ t('Credit') }}</span><b>{{ order.credit_status }}</b>
        </div>
        <div v-if="order.approval_required" class="kv">
          <span>{{ t('Approval') }}</span>
          <b>{{ order.approval_status || t('Pending') }}</b>
        </div>
      </section>

      <!-- Cancelling. At the bottom, behind a confirmation, and gone entirely once the depot
           has billed it - at which point it is a return and not this rep's to undo. -->
      <section v-if="canCancel" class="card danger">
        <template v-if="!confirming">
          <h2>{{ t('Cancel this order') }}</h2>
          <p class="dim">
            {{ t("This takes it out of the depot's queue and gives back any offer it earned.") }}
          </p>
          <button class="undo" type="button" @click="askCancel">
            {{ t('Cancel this order') }}
          </button>
        </template>

        <template v-else>
          <h2>{{ t('Cancel this order?') }}</h2>
          <p class="dim">{{ t('It cannot be undone.') }}</p>
          <input v-model="reason" type="text" :disabled="cancelling"
                 :placeholder="t('Why? (optional, the depot sees this)')" />
          <p v-if="cancelError" class="note crit">{{ cancelError }}</p>
          <div class="pair">
            <button class="keep" type="button" :disabled="cancelling" @click="keepIt">
              {{ t('Keep it') }}
            </button>
            <button class="go" type="button" :disabled="cancelling" @click="doCancel">
              {{ cancelling ? t('Cancelling…') : t('Yes, cancel') }}
            </button>
          </div>
        </template>
      </section>
    </template>
  </div>
</template>

<style scoped>
.wrap { padding: 16px 16px 90px; display: grid; gap: 12px; }

.head { display: flex; align-items: flex-start; gap: 10px; }
.back, .quiet { min-width: 44px; min-height: 44px; display: grid; place-items: center;
                background: none; border: 0; color: var(--ink); flex: none; }
.quiet { margin-left: auto; color: var(--muted); }
.who { min-width: 0; }
h1 { font-size: 20px; margin: 0; line-height: 1.2; }
h2 { font-size: 13px; font-weight: 600; margin: 0 0 8px; color: var(--muted);
     text-transform: uppercase; letter-spacing: .06em; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
        padding: 12px; display: grid; gap: 8px; }
.card.lead { gap: 10px; }
.leadtop { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.party { display: grid; gap: 2px; min-width: 0; }
.pname { font-size: 17px; line-height: 1.25; overflow-wrap: anywhere; }
.leadsum { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.big { font-size: 24px; }

.lines { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
.line { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px;
        align-items: start; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
.line:last-child { border-bottom: 0; padding-bottom: 0; }
.lname { display: grid; gap: 2px; min-width: 0; }
.lname b { font-size: 15px; line-height: 1.3; overflow-wrap: anywhere; }
.lqty, .lamt { display: grid; gap: 2px; justify-items: end; text-align: right; }
.lqty { font-size: 14px; }
.lamt b { font-size: 15px; }

.kv { display: flex; align-items: baseline; justify-content: space-between; gap: 12px;
      font-size: 15px; }
.kv.total { border-top: 1px solid var(--line); padding-top: 8px; font-size: 16px; }
.kv .ok { color: var(--ok); }

.pill { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border-radius: 999px;
        font-size: 13px; font-weight: 600; background: var(--primary-soft); color: var(--primary);
        white-space: nowrap; }
.pill.small { font-size: 12px; padding: 1px 7px; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.crit { background: var(--crit-soft); color: var(--crit); }
.pill.flat { background: var(--line); color: var(--muted); }
.pill.book { justify-self: start; text-decoration: none; }

.dim { color: var(--muted); font-size: 13px; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; }
.tnum { font-variant-numeric: tabular-nums; }
.note { margin: 0; padding: 12px; background: var(--surface); border: 1px solid var(--line);
        border-radius: 8px; color: var(--muted); }
.note.crit { color: var(--crit); border-color: var(--crit); background: var(--crit-soft); }

.card.danger { border-color: var(--crit); }
.card.danger h2 { color: var(--crit); }
input { width: 100%; min-height: 48px; padding: 0 12px; border: 1px solid var(--line);
        border-radius: 6px; background: var(--bg); color: var(--ink); font-size: 16px; }
.undo { min-height: 48px; border-radius: 6px; font-size: 15px; font-weight: 600;
        background: var(--surface); color: var(--crit); border: 1px solid var(--crit); }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.keep, .go { min-height: 48px; border-radius: 6px; font-size: 15px; font-weight: 600; }
.keep { background: var(--surface); border: 1px solid var(--line); color: var(--ink); }
.go { background: var(--crit); border: 1px solid var(--crit); color: #fff; }
</style>
