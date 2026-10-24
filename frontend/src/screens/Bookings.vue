<script setup>
/**
 * The season book — what this rep has booked, and what each one is waiting for.
 *
 * A booking is not an order a rep forgets about the moment it is sent. It is a commitment taken
 * months before delivery, and between the counter and the lorry there is one thing a rep has to
 * keep going back for: **the advance**. Nothing is reserved and nothing is planned until that
 * money is in hand, so a booking list that showed a status and no figure would be a list nobody
 * could act on.
 *
 * So every row says three numbers: what has to be collected, what has arrived, and what is still
 * short. And it keeps the fourth one apart on purpose — a post-dated cheque is allocated to the
 * booking and shown against it, and it is **not** money until its date. A rep who reads a PDC as
 * paid walks away from a booking that is still held, and tells the party their stock is coming.
 *
 * Read from the server every time. These figures move because somebody else banked a cheque or
 * the office confirmed a deposit, so a cached copy is a figure that is wrong in the one direction
 * that matters. The list says so when there is no signal rather than drawing a stale one.
 */
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api/client'
import { formatRupees } from '../lib/money'
import { AWAITING_ADVANCE } from '../lib/season'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const bookings = ref([])
const loading = ref(true)
const error = ref('')
const filter = ref('')

// What the office has done with it, in the rep's words. "Awaiting Advance" is what the field is
// called; "Waiting for your advance" is what the rep has to do about it.
// `computed`, for the same reason as on the orders list. `AWAITING_ADVANCE` is imported
// rather than spelled out so the key cannot drift from the server's own value.
const WORDS = computed(() => ({
  Draft: t('Not sent'),
  'Pending Approval': t('Waiting on your manager'),
  [AWAITING_ADVANCE]: t('Waiting for the advance'),
  Approved: t('Approved'),
  'Sent To Distributor': t('With the depot'),
  Accepted: t('Accepted'),
  Invoiced: t('Billed'),
  Delivered: t('Delivered'),
  Rejected: t('Refused'),
  Cancelled: t('Cancelled'),
}))
const TONE = {
  [AWAITING_ADVANCE]: 'warn',
  'Pending Approval': 'warn',
  Rejected: 'crit',
  Cancelled: 'crit',
  Delivered: 'ok',
  Invoiced: 'ok',
  Accepted: 'ok',
  Approved: 'ok',
}

const TABS = computed(() => [
  { key: '', label: t('All') },
  { key: 'held', label: t('Need advance') },
  { key: 'moving', label: t('Going ahead') },
])

const shown = computed(() => {
  if (filter.value === 'held') return bookings.value.filter((b) => b.advance_short > 0)
  if (filter.value === 'moving') return bookings.value.filter((b) => !b.advance_short)
  return bookings.value
})

/** The money still to collect across what is on screen. The one figure a day plan comes off. */
const toCollect = computed(() =>
  shown.value.reduce((sum, b) => sum + Number(b.advance_short || 0), 0)
)

/** What the party is billed. The net is the goods; the bill carries GST on top. */
function billTotal(b) {
  return Number(b.grand_total || 0) || Number(b.net_total || 0)
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function day(value) {
  if (!value) return ''
  const [y, m, d] = String(value).slice(0, 10).split('-')
  const month = MONTHS[Number(m) - 1]
  return `${Number(d)} ${month ? t(month) : ''} ${String(y).slice(2)}`.replace(/\s+/g, ' ')
}

/** How far the advance has got, for a bar. Full where the season asks for none. */
function pctPaid(b) {
  const need = Number(b.advance_required || 0)
  if (!need) return 100
  return Math.min(100, Math.round((Number(b.advance_in_hand || 0) / need) * 100))
}

const PAGE = 50
const bookingCount = ref(0)
const hasMore = ref(false)
const loadingMore = ref(false)

async function load({ more = false } = {}) {
  loading.value = true
  error.value = ''
  try {
    const data = await api.orderBookings(PAGE, { start: more ? bookings.value.length : 0 })
    const rows = data.bookings || []
    bookings.value = more ? [...bookings.value, ...rows] : rows
    bookingCount.value = Number(data.total ?? bookings.value.length)
    hasMore.value = !!data.has_more
  } catch (e) {
    error.value =
      e instanceof ApiError
        ? e.message
        : t('Could not load the season book. These figures move on the office side, so this list needs signal.')
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="wrap">
    <header class="head">
      <div>
        <h1>{{ t('Season book') }}</h1>
        <p class="dim">{{ t('What you have booked, and what each one is waiting for') }}</p>
      </div>
      <button class="quiet" :disabled="loading" @click="load" :aria-label="t('Refresh')">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <div class="tabs">
      <button v-for="tab in TABS" :key="tab.key" class="chip"
              :class="{ on: filter === tab.key }" @click="filter = tab.key">
        {{ tab.label }}
      </button>
    </div>

    <p v-if="loading" class="note">{{ t('Loading…') }}</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else-if="shown.length">
      <!-- The day's actual job, at the top. A rep opens this screen to find out whose office to
           walk into, not to admire a list. -->
      <div class="sum">
        <span>
          {{ shown.length === 1
              ? t('{n} booking', { n: shown.length })
              : t('{n} bookings', { n: shown.length }) }}
        </span>
        <b v-if="toCollect" class="tnum warn-text">
          {{ t('{amount} to collect', { amount: formatRupees(toCollect) }) }}
        </b>
        <b v-else class="tnum ok-text">{{ t('Nothing outstanding') }}</b>
      </div>

      <div v-for="b in shown" :key="b.name" class="card">
        <div class="row">
          <div class="left">
            <b>{{ b.customer }}</b>
            <span class="dim mono">{{ b.name }} · {{ b.season_name || b.season }}</span>
          </div>
          <div class="right">
            <b class="tnum">{{ formatRupees(billTotal(b)) }}</b>
            <span class="pill" :class="TONE[b.order_status] || 'flat'">
              {{ WORDS[b.order_status] || b.order_status }}
            </span>
          </div>
        </div>

        <!-- The advance, which is the whole reason this screen is not just the orders list. -->
        <div v-if="b.advance_required" class="adv">
          <div class="track" role="img"
               :aria-label="t('Advance {paid} of {due}', {
                            paid: formatRupees(b.advance_in_hand),
                            due: formatRupees(b.advance_required) })">
            <span class="seg paid" :style="{ width: pctPaid(b) + '%' }"></span>
          </div>
          <div class="srow tnum">
            <span>{{ t('Advance') }}</span>
            <b>{{ t('{paid} of {due}', {
                 paid: formatRupees(b.advance_in_hand),
                 due: formatRupees(b.advance_required) }) }}</b>
          </div>
          <div v-if="b.advance_short" class="srow tnum">
            <span class="warn-text">{{ t('Still to collect') }}</span>
            <b class="warn-text">{{ formatRupees(b.advance_short) }}</b>
          </div>

          <!-- Kept apart from the figure above it, deliberately. A cheque dated next month is
               allocated to this booking and is not money until its date, and a rep who reads it
               as paid tells the party their stock is coming when nothing has been reserved. -->
          <p v-if="b.pdc_total" class="foot">
            <Icon name="info" size="15" />
            <span class="tnum">
              <b>{{ formatRupees(b.pdc_total) }}</b>
              {{ t('of post-dated cheques is held against this booking.') }}
              {{ t('It does not count until it falls due.') }}
            </span>
          </p>

          <p v-if="b.advance_short" class="foot strong">
            {{ t('Nothing is reserved or dispatched until the advance is in hand.') }}
          </p>

          <!-- The depot collection form, not the shop one. A booking advance comes from the
               distributor, and `/collect/:outlet` records against a FieldMate Outlet - which
               this party is not. The query carries the booking so the form opens on it, with
               the depot and the shortfall already filled in. -->
          <RouterLink v-if="b.advance_short" class="go"
                      :to="{ name: 'money', query: { order: b.name } }">
            {{ t('Collect {amount}',
                 { amount: formatRupees(b.advance_short) }) }}
          </RouterLink>
        </div>

        <p v-else class="foot">{{ t('This season asks for no advance.') }}</p>

        <div class="meta tnum">
          <span>{{ t('Booked {date}', { date: day(b.order_date) }) }}</span>
          <span v-if="b.delivery_from">
            {{ t('Delivers {from}–{to}',
                 { from: day(b.delivery_from), to: day(b.delivery_to) }) }}
          </span>
          <!-- The promise the party was given at the counter, and the one thing a rep is asked
               about most: has the price moved. -->
          <span v-if="b.rates_locked">{{ t('Rates held') }}</span>
          <span v-if="b.tops_up">{{ t('Adds to {name}', { name: b.tops_up }) }}</span>
        </div>
      </div>

      <!-- A button rather than an infinite scroll: on a market uplink a scroll that fetches
           silently is a scroll that silently fails. -->
      <button v-if="hasMore && !loading" class="more" type="button"
              :disabled="loadingMore" @click="load({ more: true })">
        {{ loadingMore
            ? t('Loading…')
            : t('Show more ({n} left)', { n: bookingCount - bookings.length }) }}
      </button>
    </template>

    <div v-else class="empty">
      <Icon name="timer" size="34" />
      <b>{{ filter ? t('Nothing here') : t('No bookings yet') }}</b>
      <p class="dim">
        {{ filter
          ? t('Try another tab.')
          : t('A primary order dated inside an open season books it. There is nothing open, or nothing booked yet.') }}
      </p>
      <RouterLink to="/parties" class="ghost">{{ t('Order on a distributor') }}</RouterLink>
    </div>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.head h1 { font-size: 20px; margin: 0; }
.dim { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.quiet { border: 0; background: none; color: var(--muted); min-height: 44px; padding: 0 6px; }

.tabs { display: flex; gap: 8px; overflow-x: auto; }
.chip { flex: none; padding: 0 16px; min-height: 44px; border: 1px solid var(--line);
        background: var(--surface); border-radius: 999px; color: var(--ink); font-weight: 600;
        font-size: 14px; }
.chip.on { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }

.sum { display: flex; justify-content: space-between; align-items: baseline;
       color: var(--muted); font-size: 13px; padding: 0 2px; }
.warn-text { color: var(--warn); }
.ok-text { color: var(--ok); }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: flex; flex-direction: column; gap: 10px; }
.row { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }

.adv { display: flex; flex-direction: column; gap: 6px; border-top: 1px solid var(--line);
       padding-top: 10px; }
.track { height: 8px; border-radius: 4px; overflow: hidden; background: var(--primary-soft); }
.seg { display: block; height: 100%; }
.seg.paid { background: var(--ok); }
.srow { display: flex; justify-content: space-between; gap: 10px; font-size: 14px; }
.foot { display: flex; align-items: flex-start; gap: 6px; margin: 0; font-size: 13px;
        color: var(--muted); }
.foot.strong { color: var(--warn); font-weight: 600; }

.go { align-self: flex-start; min-height: 44px; display: inline-flex; align-items: center;
      padding: 0 14px; border-radius: 8px; border: 1px solid var(--primary);
      color: var(--primary); text-decoration: none; font-weight: 600; font-size: 14px; }

.meta { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--muted);
        border-top: 1px solid var(--line); padding-top: 8px; }

.pill { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px;
        white-space: nowrap; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.crit { background: var(--crit-soft); color: var(--crit); }
.pill.flat { background: var(--primary-soft); color: var(--primary); }

.note { color: var(--muted); font-size: 14px; text-align: center; padding: 20px 0; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.empty { text-align: center; padding: 40px 16px; color: var(--muted); display: flex;
         flex-direction: column; gap: 6px; align-items: center; }
.empty b { color: var(--ink); }
.empty p { margin: 0; }
.ghost { min-height: 44px; display: inline-flex; align-items: center; padding: 0 14px;
         margin-top: 6px; border-radius: 8px; border: 1px solid var(--line);
         color: var(--primary); text-decoration: none; font-weight: 600; }
.tnum { font-variant-numeric: tabular-nums; }
.more { width: 100%; min-height: 48px; border-radius: 8px; font-weight: 600; font-size: 15px;
        border: 1px solid var(--primary); background: var(--surface); color: var(--primary); }
.more:disabled { color: var(--muted); border-color: var(--line); }
</style>
