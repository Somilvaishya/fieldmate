<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api/client'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const day = ref(null)
const trend = ref([])
const loading = ref(true)
const error = ref('')

const visits = computed(() => day.value?.visits || {})
const orders = computed(() => day.value?.orders || {})
const money = computed(() => day.value?.money || {})
const travel = computed(() => day.value?.travel || {})

// The bar is three segments and they have to add to the whole, so "open" is whatever is left
// rather than a number of its own. A planned figure smaller than what was actually done is
// ordinary - a rep covering for somebody - and then the bar is simply full.
const bar = computed(() => {
  const planned = Math.max(visits.value.planned || 0, visits.value.made || 0, 1)
  const done = visits.value.productive || 0
  const dry = Math.max((visits.value.made || 0) - done, 0)
  const open = Math.max(planned - (visits.value.made || 0), 0)
  return {
    planned,
    done: (done / planned) * 100,
    dry: (dry / planned) * 100,
    open: (open / planned) * 100,
    openCount: open,
    dryCount: dry,
  }
})

// Fourteen days of value, as a sparkline. Read from the snapshot, unlike everything above it.
const spark = computed(() => {
  const rows = trend.value
  if (rows.length < 2) return null
  const values = rows.map((r) => Number(r.order_value || 0))
  const top = Math.max(...values, 1)
  const step = 100 / (rows.length - 1)
  const points = values.map((v, i) => `${(i * step).toFixed(2)},${(100 - (v / top) * 100).toFixed(2)}`)
  return { path: 'M' + points.join(' L'), top, best: Math.max(...values) }
})

function short(rupees) {
  const n = Number(rupees || 0)
  if (n >= 1_00_000) return '₹' + (n / 1_00_000).toFixed(n >= 10_00_000 ? 0 : 1) + 'L'
  if (n >= 1_000) return '₹' + (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + 'K'
  return formatRupees(n)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    day.value = await api.dayCockpit()
    // The trend is a nicety. A failure there must not take the day's own figures with it.
    try {
      trend.value = (await api.kpiTrend(14)).days || []
    } catch {
      trend.value = []
    }
  } catch (e) {
    error.value = e instanceof ApiError
      ? e.message
      : t('Could not load today. These figures are counted on the server, so this needs signal.')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="wrap">

    <header class="head">
      <div>
        <h1>{{ t('Today') }}</h1>
        <p v-if="day" class="sub">
          {{ day.beat || t('No beat planned') }} · {{ day.full_name }}
        </p>
      </div>
      <button class="quiet" :disabled="loading" @click="load">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <p v-if="loading" class="note">{{ t('Loading…') }}</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else-if="day">
      <div v-if="!day.day_started" class="note warn">
        {{ t('Your day has not started yet.') }}
        {{ t('Nothing below will move until it does.') }}
      </div>

      <!-- The three that matter -->
      <section class="strip">
        <div class="tile">
          <div class="label">{{ t('Booked') }}</div>
          <div class="num tnum">{{ orders.count }}</div>
          <div class="value tnum">{{ short(orders.value) }}</div>
          <div class="dim">
            {{ orders.shops === 1
                ? t('{n} shop', { n: orders.shops })
                : t('{n} shops', { n: orders.shops }) }}
          </div>
        </div>
        <div class="tile">
          <div class="label">{{ t('Calls') }}</div>
          <div class="num tnum">{{ visits.made }}<small> / {{ visits.planned || '–' }}</small></div>
          <div class="value tnum">{{ Math.round(visits.strike_rate) }}%</div>
          <div class="dim">{{ t('struck') }}</div>
        </div>
        <div class="tile">
          <div class="label">{{ t('Collected') }}</div>
          <div class="num tnum ok">{{ short(money.collected) }}</div>
          <div class="value tnum">{{ short(money.deposited) }}</div>
          <div class="dim">{{ t('handed over') }}</div>
        </div>
      </section>

      <!-- Where the day has reached -->
      <section class="card">
        <div class="row">
          <b>{{ t('{made} of {planned} calls',
                 { made: visits.made, planned: bar.planned }) }}</b>
          <span class="dim">{{ t('{n} left', { n: bar.openCount }) }}</span>
        </div>
        <div class="bar">
          <i class="done" :style="{ width: bar.done + '%' }"></i>
          <i class="dry" :style="{ width: bar.dry + '%' }"></i>
          <i class="open" :style="{ width: bar.open + '%' }"></i>
        </div>
        <div class="legend">
          <span>
            <i class="dot done"></i>{{ t('{n} sold', { n: visits.productive }) }}
          </span>
          <span>
            <i class="dot dry"></i>{{ t('{n} no order', { n: bar.dryCount }) }}
          </span>
          <span>
            <i class="dot open"></i>{{ t('{n} to go', { n: bar.openCount }) }}
          </span>
        </div>
      </section>

      <!-- Money still in the satchel. The figure the rep is answerable for. -->
      <RouterLink v-if="money.in_hand > 0" to="/deposit" class="card hand">
        <Icon name="tag" size="20" />
        <span>
          <b>{{ t('{amount} still with you',
                 { amount: formatRupees(money.in_hand) }) }}</b>
          <em>
            {{ money.receipts === 1
                ? t('{n} receipt · hand it in', { n: money.receipts })
                : t('{n} receipts · hand it in', { n: money.receipts }) }}
          </em>
        </span>
        <Icon name="chevron" size="18" class="go" />
      </RouterLink>

      <!-- Fourteen days, from the snapshot -->
      <section v-if="spark" class="card">
        <div class="row">
          <b>{{ t('Last 14 days') }}</b>
          <span class="dim">{{ t('best {amount}', { amount: short(spark.best) }) }}</span>
        </div>
        <svg class="spark" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          <path :d="spark.path" fill="none" stroke="currentColor" stroke-width="2.5"
                vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round" />
        </svg>
        <p class="dim fine">
          {{ t("Counted overnight, so today's own bar is the live one above.") }}
        </p>
      </section>

      <div class="grid">
        <div class="mini">
          <div class="dim">{{ t('Distance') }}</div>
          <b class="tnum">
            {{ t('{n} km', { n: Number(travel.distance_km || 0).toFixed(1) }) }}
          </b>
        </div>
        <div class="mini">
          <div class="dim">{{ t('Hours out') }}</div>
          <b class="tnum">{{ Number(travel.hours || 0).toFixed(1) }}</b>
        </div>
      </div>

      <div class="links">
        <RouterLink to="/performance" class="btn-flat">
          <Icon name="target" size="18" /> {{ t('My performance') }}
        </RouterLink>
        <RouterLink to="/expense" class="btn-flat">
          <Icon name="receipt" size="18" /> {{ t('Claim expenses') }}
        </RouterLink>
      </div>
    </template>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.head h1 { font-size: 20px; margin: 0; }
.sub { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.quiet { border: 0; background: none; color: var(--muted); min-height: 44px; padding: 0 6px; }

.strip { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 10px; display: flex; flex-direction: column; gap: 2px; }
.label { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); }
.num { font-size: 19px; font-weight: 700; line-height: 1.2; }
.num small { font-size: 13px; font-weight: 400; color: var(--muted); }
.num.ok { color: var(--ok); }
.value { font-size: 15px; font-weight: 600; }
.dim { color: var(--muted); font-size: 12px; }
.fine { font-size: 12px; margin: 0; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 14px; display: flex; flex-direction: column; gap: 10px; color: var(--primary); }
.row { display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
       color: var(--ink); }
.bar { display: flex; height: 12px; border-radius: 999px; overflow: hidden;
       background: var(--line); }
.bar i { display: block; height: 100%; }
.bar i.done { background: var(--ok); }
.bar i.dry { background: var(--warn); }
.bar i.open { background: var(--line); }
.legend { display: flex; justify-content: space-between; gap: 8px; font-size: 12px;
          color: var(--muted); }
.legend span { display: flex; align-items: center; gap: 5px; }
.dot { width: 9px; height: 9px; border-radius: 999px; display: inline-block; }
.dot.done { background: var(--ok); }
.dot.dry { background: var(--warn); }
.dot.open { background: var(--line); }

.card.hand { flex-direction: row; align-items: center; gap: 10px; text-decoration: none;
             background: var(--warn-soft); border-color: transparent; color: var(--warn); }
.card.hand span { flex: 1; display: flex; flex-direction: column; }
.card.hand em { font-style: normal; font-size: 13px; color: var(--muted); }
.go { margin-left: auto; }

.spark { width: 100%; height: 56px; color: var(--primary); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.mini { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 10px 12px; display: flex; flex-direction: column; gap: 2px; }
.links { display: flex; gap: 8px; }
.btn-flat { flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
            min-height: 48px; background: var(--surface); border: 1px solid var(--line);
            border-radius: 8px; text-decoration: none; color: var(--primary); font-weight: 600; }
.note { border-radius: 8px; padding: 10px 12px; font-size: 14px; color: var(--muted);
        text-align: center; }
.note.crit { background: var(--crit-soft); color: var(--crit); text-align: left; }
.note.warn { background: var(--warn-soft); color: var(--warn); text-align: left; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
