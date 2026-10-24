<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api/client'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const orders = ref([])
const loading = ref(true)
const error = ref('')
const filter = ref('')

// What the depot has done with it, in the rep's words rather than the document's. "Sent To
// Distributor" is what the field is called; "With the depot" is what the rep would say.
// `computed`, so a language change redraws the pills. The keys are the server's own status
// values and stay English - `TONE` is keyed on the same spelling.
const WORDS = computed(() => ({
  'Draft': t('Not sent'),
  'Pending Approval': t('Waiting on your manager'),
  // A season booking held for its advance. Nobody is deciding anything - it is waiting for
  // money - so it must not read like an approval the rep can chase a manager about.
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

const TABS = computed(() => [
  { key: '', label: t('All') },
  { key: 'Sent To Distributor', label: t('With depot') },
  { key: 'Pending Approval', label: t('Waiting') },
  { key: 'Delivered', label: t('Delivered') },
])

const shown = computed(() =>
  filter.value ? orders.value.filter((o) => o.order_status === filter.value) : orders.value
)

/** What the party is billed, not what the goods come to.
 *
 * `net_total` is the goods. The bill carries the distributor's GST on top, and a rep reading this
 * list to a shopkeeper or to their own manager has to read the number that will arrive on the
 * invoice. `grand_total` is net plus tax and is zero on a site holding no tax templates, so the
 * net stands in there rather than printing a blank.
 *
 * A queued order has neither: the phone's own tax figure is not part of the order document and
 * the server's is the figure of record, so it shows the net until it syncs. `pending` is already
 * on the card to say the order has not landed yet.
 */
function billTotal(o) {
  return Number(o.grand_total || 0) || Number(o.net_total || 0)
}

/** Is this a season booking? Then its advance, not its status, is what the rep has to act on. */
function isBooking(o) {
  return o.order_kind === 'Booking'
}

/** Who the order is for. A primary order has no outlet - it has a party (ADR-033). */
/** The shop or the party, in words. The server sends both the name and the id now - a list of
 *  `FM-OUT-00041` made a rep work out which shop each row was. */
function partyName(o) {
  return o.outlet_name || o.customer_name || o.outlet || o.customer || o.name
}

/** The id under the name, and nothing when the name *is* the id - a code printed twice is
 *  a row that looks broken. */
function partyId(o) {
  const id = o.outlet || o.customer || ''
  return id === partyName(o) ? '' : id
}

const total = computed(() =>
  shown.value.reduce((sum, o) => sum + billTotal(o), 0)
)

function day(value) {
  if (!value) return ''
  const [y, m, d] = String(value).slice(0, 10).split('-')
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const month = months[Number(m) - 1]
  return `${d} ${month ? t(month) : ''}`.trim()
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await api.orderList()
    orders.value = data.orders || data || []
  } catch (e) {
    error.value = e instanceof ApiError
      ? e.message
      : t('Could not load your orders. This list lives on the server, so it needs signal.')
  } finally {
    loading.value = false
  }
}

// Cancelling lives on the order's own screen, not here. It is the one destructive action in
// this app and it used to sit under the thumb on every row of a list a rep scrolls all day.

onMounted(load)
</script>

<template>
  <div class="wrap">
    <header class="head">
      <div>
        <h1>{{ t('My orders') }}</h1>
        <p class="dim">{{ t('What you booked, and where each one has reached') }}</p>
        <!-- The way into a primary order. It lives here rather than on the tab bar because a
             rep books one a week of these and twenty shop orders a day, and a sixth tab would
             cost the twenty to serve the one.

             Drawn as buttons, not as the underlined links they used to be: three sentences
             underlined in a row read as body text somebody had turned blue, and a rep has to be
             able to see at a glance that these are the three things this screen can do. -->
      </div>
      <button class="quiet" :disabled="loading" @click="load" :aria-label="t('Refresh')">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <nav class="ways">
      <RouterLink to="/parties" class="way">
        <Icon name="cart" size="18" /><span>{{ t('Order on a distributor') }}</span>
      </RouterLink>
      <RouterLink to="/bookings" class="way">
        <Icon name="tag" size="18" /><span>{{ t('Season book') }}</span>
      </RouterLink>
      <RouterLink to="/showcase" class="way">
        <Icon name="store" size="18" /><span>{{ t('Share the range') }}</span>
      </RouterLink>
    </nav>

    <div class="tabs">
      <button v-for="tab in TABS" :key="tab.key" class="chip"
              :class="{ on: filter === tab.key }" @click="filter = tab.key">
        {{ tab.label }}
      </button>
    </div>

    <p v-if="loading" class="note">{{ t('Loading…') }}</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else-if="shown.length">
      <div class="sum">
        <span>
          {{ shown.length === 1
              ? t('{n} order', { n: shown.length })
              : t('{n} orders', { n: shown.length }) }}
        </span>
        <b class="tnum">{{ formatRupees(total) }}</b>
      </div>

      <RouterLink v-for="o in shown" :key="o.name" class="card"
                  :to="{ name: 'order-detail', params: { name: o.name } }">
        <div class="row">
          <div class="left">
            <b class="pname">{{ partyName(o) }}</b>
            <span class="dim mono">{{ partyId(o) }}</span>
            <span class="dim mono">{{ o.name }} · {{ day(o.order_date) }}</span>
          </div>
          <div class="right">
            <b class="tnum">{{ formatRupees(billTotal(o)) }}</b>
            <span class="pill" :class="TONE[o.order_status] || 'flat'">
              {{ WORDS[o.order_status] || o.order_status }}
            </span>
            <!-- Marked, because a booking is not an order the rep forgets about: it is held
                 until its advance is in, and the season book is where that figure lives. -->
            <span v-if="isBooking(o)" class="pill book">
              {{ o.season || t('Booking') }}
            </span>
          </div>
        </div>
        <Icon name="chevron" size="20" class="go" />
      </RouterLink>

    </template>

    <div v-else class="empty">
      <Icon name="cart" size="34" />
      <b>{{ filter ? t('Nothing here') : t('No orders yet') }}</b>
      <p class="dim">
        {{ filter
            ? t('Try another tab.')
            : t('Book one from a shop and it will show up here.') }}
      </p>
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
/* The card is the way in. Tapping a row opens the order; it used to carry a Cancel button
   instead, which put the one destructive action in the app under the thumb on every row of a
   list a rep scrolls all day. */
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: grid; grid-template-columns: minmax(0, 1fr) auto;
        align-items: center; gap: 10px; color: inherit; text-decoration: none; }
.card:active { background: var(--primary-soft); }
.card .go { color: var(--muted); flex: none; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 10px;
       min-width: 0; }
.pname { font-size: 16px; line-height: 1.3; overflow-wrap: anywhere; }

.left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }
.pill { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px;
        white-space: nowrap; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.crit { background: var(--crit-soft); color: var(--crit); }
.pill.flat { background: var(--primary-soft); color: var(--primary); }
.pill.book { background: var(--primary); color: var(--on-primary); text-decoration: none; }
/* The three things this screen can do, as buttons. They were underlined links in a sentence
   row, which read as body text somebody had turned blue. Equal width so the row is a row, and
   they wrap to two lines on a narrow handset rather than scrolling off. */
.ways { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
.way { display: inline-flex; align-items: center; justify-content: center; gap: 6px;
       min-height: 48px; padding: 0 10px; border-radius: 8px; text-align: center;
       border: 1px solid var(--primary); background: var(--surface); color: var(--primary);
       font-weight: 600; font-size: 14px; text-decoration: none; line-height: 1.2; }
.way:active { background: var(--primary-soft); }
.note { color: var(--muted); font-size: 14px; text-align: center; padding: 20px 0; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.empty { text-align: center; padding: 40px 16px; color: var(--muted); display: flex;
         flex-direction: column; gap: 6px; align-items: center; }
.empty b { color: var(--ink); }
.empty p { margin: 0; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
