<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { getPosition } from '../lib/geo'
import { pendingCount } from '../sync/outbox'
import { pendingPings } from '../sync/pinger'
import * as photoQueue from '../sync/photos'
import * as dayStore from '../stores/day'
import * as role from '../stores/role'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const router = useRouter()
const summary = ref(null)

// The app only reports its position while it is open, so a day worked with the phone in a
// pocket has no trail and the server measures the route instead - day start, then each shop.
// Both are honest figures; captioning the second one "from your GPS trail" is not, and the
// odometer hint is the line a rep reads before typing a number against it.
const distanceSource = computed(() => ({
  trail: t('from your GPS trail'),
  route: t('shop to shop'),
}[summary.value?.distance_basis] || t('nothing recorded')))

const distanceNote = computed(() => {
  const km = summary.value?.distance_km
  if (summary.value?.distance_basis === 'trail') {
    return t('Your GPS trail recorded {km} km today.', { km })
  }
  if (summary.value?.distance_basis === 'route') {
    return [
      t('No GPS trail today, so {km} km is the straight line from where you started through the shops you visited.',
        { km }),
      t('The road is usually longer.'),
    ].join(' ')
  }
  return t('Nothing was recorded for today, so your odometer is the only figure there is.')
})
const odometer = ref('')
const busy = ref(false)
const error = ref('')
const note = ref('')
const queued = ref(0)
const pings = ref(0)

onMounted(async () => {
  try {
    summary.value = await api.daySummary()
  } catch (e) {
    note.value = e instanceof ApiError && e.code === 'OFFLINE'
      ? t('Offline. Your figures are counted on the server when this syncs.')
      : e.message
  }
  queued.value = (await pendingCount()) + (await photoQueue.pendingCount())
  pings.value = await pendingPings()
})

const started = computed(() =>
  summary.value?.started_at ? summary.value.started_at.slice(11, 16) : null
)

const onRoute = computed(() => {
  const m = summary.value?.minutes_on_route
  if (!m && m !== 0) return null
  return t('{h}h {m}m', {
    h: Math.floor(m / 60),
    m: String(m % 60).padStart(2, '0'),
  })
})

// Counted against the route, not against every visit of the day. Using the raw visit total
// let this read 100% while the card below still named planned shops that were missed.
const coverage = computed(() => {
  const s = summary.value
  if (!s?.planned_visits) return null
  const onRoute = Math.min(s.planned_covered ?? s.actual_visits, s.planned_visits)
  return Math.round((onRoute / s.planned_visits) * 100)
})
const covered = computed(() => {
  const s = summary.value
  if (!s) return 0
  return Math.min(s.planned_covered ?? s.actual_visits, s.planned_visits)
})

// "On track" is only a claim worth making when there is a plan to be on track against.
const standing = computed(() => {
  if (coverage.value === null) return null
  if (coverage.value >= 90) return { label: t('On track'), tone: 'good' }
  if (coverage.value >= 70) return { label: t('Nearly there'), tone: 'warn' }
  return { label: t('Behind plan'), tone: 'warn' }
})

function rupees(v) {
  return '₹' + Number(v || 0).toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

const today = computed(() =>
  new Date().toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' })
)

async function finish() {
  error.value = ''
  busy.value = true
  try {
    const fix = await getPosition().catch(() => ({}))
    await dayStore.end({
      ...fix,
      odometer_end: odometer.value ? Number(odometer.value) : null,
    })
    router.replace(role.homeRoute.value)
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t('Could not finish your day. Try again.')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap screen">
    <div class="top">
      <div class="head">
        <div>
          <span class="eyebrow">{{ t('Day summary') }}</span>
          <h2>{{ today }}</h2>
        </div>
        <span v-if="standing" class="badge" :class="standing.tone">{{ standing.label }}</span>
      </div>
      <p class="muted when" v-if="started">
        {{ t('Started at {time}', { time: started }) }}
        <span v-if="onRoute"> · {{ t('{time} on route', { time: onRoute }) }}</span>
      </p>
      <p v-if="note" class="muted">{{ note }}</p>

      <!-- What is still on this phone. The one thing a rep must know before they walk away. -->
      <div class="sync" :class="queued || pings ? 'waiting' : 'clear'">
        <Icon :name="queued || pings ? 'cloud-off' : 'check'" size="20" />
        <span v-if="queued || pings" class="tnum">
          {{ t('{records} records and {points} location points still to send',
               { records: queued, points: pings }) }}
        </span>
        <span v-else>{{ t('Everything on this phone has synced') }}</span>
      </div>

      <template v-if="summary">
        <div class="card" v-if="summary.planned_visits">
          <div class="row">
            <b class="tnum">
              {{ t('{covered} of {planned} planned shops',
                   { covered, planned: summary.planned_visits }) }}
            </b>
            <b class="tnum" :class="coverage >= 90 ? 'good' : 'warnt'">{{ coverage }}%</b>
          </div>
          <div class="track">
            <div class="fill" :style="{ width: Math.min(100, coverage) + '%' }"></div>
          </div>
          <!-- Named, not counted. "2 shops pending" tells a rep nothing they can act on. -->
          <p class="pending" v-if="summary.pending_shops.length">
            <Icon name="alert" size="18" />
            <span>
              <b>{{ t('{n} not visited:',
                       { n: summary.pending_shops.length }) }}</b>
              {{ summary.pending_shops.map((s) => s.outlet_name).join(', ') }}
            </span>
          </p>
        </div>

        <div class="tiles">
          <div class="tile">
            <span class="muted">{{ t('Shops visited') }}</span>
            <b class="tnum">{{ summary.actual_visits }}</b>
            <span class="muted tnum" v-if="summary.productive_visits">
              {{ t('{n} took an order', { n: summary.productive_visits }) }}
            </span>
          </div>
          <div class="tile">
            <span class="muted">{{ t('Distance') }}</span>
            <b class="tnum">{{ summary.distance_km }} <small>{{ t('km') }}</small></b>
            <span class="muted">{{ distanceSource }}</span>
          </div>
          <!-- Orders and collections arrive in later phases. Shown once they exist rather
               than as a permanent row of zeros, which reads as a bad day, not a missing one. -->
          <div class="tile" v-if="summary.orders_count">
            <span class="muted">{{ t('Orders taken') }}</span>
            <b class="tnum">{{ summary.orders_count }}</b>
            <span class="muted tnum">{{ rupees(summary.order_value) }}</span>
          </div>
          <div class="tile" v-if="summary.collection_amount">
            <span class="muted">{{ t('Collected') }}</span>
            <b class="tnum">{{ rupees(summary.collection_amount) }}</b>
            <span class="muted">{{ t('ready to deposit') }}</span>
          </div>
          <div class="tile" v-if="summary.new_outlets">
            <span class="muted">{{ t('New shops') }}</span>
            <b class="tnum">{{ summary.new_outlets }}</b>
            <span class="muted">{{ t('awaiting approval') }}</span>
          </div>
        </div>

        <div class="card">
          <label class="lbl" for="odo">
            {{ t('Closing odometer') }} <span class="muted">{{ t('(optional)') }}</span>
          </label>
          <div class="odo">
            <input id="odo" v-model="odometer" inputmode="numeric" class="tnum"
                   :placeholder="t('e.g. 14272')" />
            <span class="unit">{{ t('km') }}</span>
          </div>
          <p class="muted hint tnum">{{ distanceNote }}</p>
        </div>
      </template>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>
    </div>

    <div class="bottom">
      <button class="btn-primary" :disabled="busy" @click="finish">
        {{ busy ? t('Finishing…') : t('Finish day') }}
      </button>
      <p class="muted foot">
        {{ t('Your location stops being recorded as soon as you finish.') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: grid; gap: 12px; align-content: start; }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;
        margin: 8px 0 0; }
.eyebrow { display: block; font-size: 14px; font-weight: 700; letter-spacing: 0.05em;
           text-transform: uppercase; color: var(--muted); }
h2 { margin: 2px 0 0; font-size: 20px; }
.when { margin: 0; }
.muted { color: var(--muted); font-size: 14px; font-weight: 400; }

.badge { flex: none; font-size: 14px; font-weight: 700; padding: 4px 10px; border-radius: 4px; }
.badge.good { background: var(--ok-soft); color: var(--ok); }
.badge.warn { background: var(--warn-soft); color: var(--warn); }

.sync { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 6px;
        font-size: 14px; font-weight: 600; border: 1px solid; }
.sync.clear { background: var(--ok-soft); color: var(--ok); border-color: var(--ok); }
.sync.waiting { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; }
.row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.good { color: var(--ok); }
.warnt { color: var(--warn); }
.track { height: 8px; border-radius: 4px; background: var(--primary-soft); overflow: hidden;
         margin: 10px 0 0; }
.fill { height: 100%; background: var(--ok); border-radius: 4px; }
.pending { display: flex; align-items: flex-start; gap: 8px; margin: 12px 0 0; font-size: 14px;
           color: var(--warn); }
.pending b { color: var(--warn); }

.tiles { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; display: grid; gap: 2px; align-content: start; }
.tile b { font-size: 26px; line-height: 1.1; }
.tile small { font-size: 15px; font-weight: 600; }

.lbl { display: block; font-weight: 600; font-size: 16px; margin-bottom: 6px; }
.odo { position: relative; display: flex; align-items: center; }
.odo input { padding-right: 52px; }
.unit { position: absolute; right: 14px; font-weight: 700; color: var(--muted);
        pointer-events: none; }
.hint { margin: 6px 0 0; }

.err { display: flex; align-items: flex-start; gap: 8px; margin: 0; font-size: 14px;
       background: var(--crit-soft); color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.bottom { position: sticky; bottom: 0; padding: 12px 0 4px; margin-top: 16px;
          background: var(--bg); border-top: 1px solid var(--line); }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               padding: 14px; min-height: 52px; border-radius: 6px; }
.foot { text-align: center; margin: 8px 0 0; }
</style>
