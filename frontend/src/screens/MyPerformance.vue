<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api/client'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'
import OfflineStrip from '../components/OfflineStrip.vue'

const data = ref(null)
const actual = ref(null)
const loading = ref(true)
const error = ref('')

const targets = computed(() => data.value?.targets || {})
const incentive = computed(() => data.value?.incentive || {})

// The headline line is the one the rep opens this screen for. Overall value where there is one:
// a category line is a different conversation and gets its own row further down.
const headline = computed(() =>
  (targets.value.lines || []).find((l) => l.target_type === 'Value' && !l.item_group && !l.brand)
)

// The four tiles. Everything except value and the category rows, in the order the screen reads.
const TILE_ORDER = ['Outlet Coverage', 'Productive Calls', 'New Outlets', 'Lines Per Call']
const tiles = computed(() =>
  TILE_ORDER
    .map((type) => (targets.value.lines || []).find((l) => l.target_type === type && !l.item_group))
    .filter(Boolean)
)

const categories = computed(() =>
  (targets.value.lines || []).filter((l) => l.item_group || l.brand)
)

// Phase 8: the nine, measured, as opposed to the targets above. Value, volume and new shops are
// left out here - they already have their own card and their own bar further up, and repeating
// a figure on one screen invites a reader to look for the difference between the two.
const MEASURED = ['coverage_pct', 'productive_pct', 'visit_compliance_pct',
                  'collection_efficiency_pct', 'lines_per_call', 'avg_order_value']
const measured = computed(() =>
  (actual.value?.metrics || []).filter((m) => MEASURED.includes(m.key))
)

// What has to happen each remaining day against what has been happening. The second half is the
// part the target card cannot show: a rep ahead of the required rate is on track whatever the
// percentage says today.
const runRate = computed(() => {
  const totals = actual.value?.totals
  if (!totals || !headline.value) return null
  const worked = totals.days_worked || 0
  const perDay = worked ? totals.order_value / worked : 0
  const left = targets.value.days_left || 0
  return {
    needed: headline.value.per_day_needed || 0,
    current: Math.round(perDay),
    onTrack: left > 0 && perDay > 0 && perDay >= (headline.value.per_day_needed || 0),
    projection: Math.round(headline.value.actual_value + perDay * left),
  }
})

function measuredValue(m) {
  return m.is_pct ? Math.round(m.value) + '%' : Number(m.value).toFixed(m.value < 100 ? 1 : 0)
}

// A month's target is six or seven digits, and a 360px phone cannot show "₹10,00,000 of
// ₹6,40,000" beside a percentage without wrapping into nonsense. Lakh and crore are how the
// figure is said out loud anyway. Kept here rather than in lib/money.js on purpose: money.js is
// the money PATH, audited to the paise, and this is a display shorthand that deliberately
// loses precision. Exact figures still appear everywhere the rep is deciding something.
function lakhs(rupees) {
  const n = Number(rupees || 0)
  if (n >= 1_00_00_000) return '₹' + (n / 1_00_00_000).toFixed(n >= 10_00_00_000 ? 0 : 1) + 'Cr'
  if (n >= 1_00_000) return '₹' + (n / 1_00_000).toFixed(n >= 10_00_000 ? 0 : 1) + 'L'
  if (n >= 1_000) return '₹' + (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + 'K'
  return formatRupees(n)
}

// Currency only where the figure is money. Printing "₹4.2" against lines per call is the kind of
// thing a rep screenshots and sends to their manager.
function show(line) {
  if (line.target_type === 'Value') return lakhs(line.actual_value)
  if (line.target_type === 'Lines Per Call') return line.actual_value.toFixed(1)
  return Math.round(line.actual_value).toLocaleString('en-IN')
}

function showTarget(line) {
  if (line.target_type === 'Value') return lakhs(line.target_value)
  if (line.target_type === 'Lines Per Call') return line.target_value.toFixed(1)
  return Math.round(line.target_value).toLocaleString('en-IN')
}

// Capped for the bar only, never for the number beside it. A rep at 140% has earned the right to
// read 140%, and a bar that ran off the card would just look broken.
function width(pct) {
  return Math.max(0, Math.min(100, pct || 0)) + '%'
}

function tone(pct) {
  if (pct >= 100) return 'ok'
  if (pct >= 75) return 'warn'
  return 'crit'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await api.myPerformance()
    // Phase 8. The targets above say what was asked for; this says how the month actually went,
    // read from the KPI snapshot. A failure here must not take the target figures with it -
    // they are the ones the rep opened the screen for.
    try {
      actual.value = await api.monthDashboard()
    } catch {
      actual.value = null
    }
  } catch (e) {
    error.value = e instanceof ApiError
      ? e.message
      : 'Could not load your numbers. They are on the server, not on this phone, so this needs signal.'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="wrap">
    <OfflineStrip />

    <header class="head">
      <h1>My performance</h1>
      <p v-if="targets.plan_name" class="sub">
        {{ targets.plan_name }} · {{ targets.days_left }} days left
      </p>
    </header>

    <p v-if="loading" class="note">Loading…</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else-if="!targets.has_target">
      <div class="empty">
        <Icon name="target" />
        <p>No target has been set for you this month.</p>
        <p class="dim">Your manager sets these. Nothing you do on the phone changes it.</p>
      </div>
    </template>

    <template v-else>
      <!-- The headline -->
      <section v-if="headline" class="card">
        <div class="label">Monthly target</div>
        <div class="big tnum">
          {{ show(headline) }} <span class="of">of {{ showTarget(headline) }}</span>
          <span class="pct" :class="tone(headline.achievement_pct)">
            {{ Math.round(headline.achievement_pct) }}%
          </span>
        </div>
        <div class="bar"><i :style="{ width: width(headline.achievement_pct) }"></i></div>
        <div v-if="headline.per_day_needed" class="need">
          <Icon name="trend" />
          <span>
            Needed: <b class="tnum">{{ formatRupees(headline.per_day_needed) }} / day</b>
            to get there
          </span>
        </div>
        <!-- Phase 8: what has actually been happening per day, beside what needs to.
             A rep ahead of the required rate is on track whatever today's percentage says. -->
        <div v-if="runRate && runRate.current" class="rate" :class="{ ok: runRate.onTrack }">
          <span>Doing <b class="tnum">{{ formatRupees(runRate.current) }} / day</b> so far</span>
          <span v-if="runRate.onTrack">On course to close at {{ lakhs(runRate.projection) }}</span>
          <span v-else>At this rate, {{ lakhs(runRate.projection) }} by month end</span>
        </div>
        <div v-else-if="headline.achievement_pct >= 100" class="need ok">
          <Icon name="check" /><span>Target met. Everything from here is on top.</span>
        </div>
      </section>

      <!-- Incentive -->
      <section v-if="incentive.measured && incentive.schemes.length" class="card money">
        <div class="row">
          <div class="big tnum">On track for {{ formatRupees(incentive.total) }}</div>
          <span v-if="incentive.schemes[0].slab_label" class="tier">
            {{ incentive.schemes[0].slab_label }}
          </span>
        </div>
        <div v-for="s in incentive.schemes" :key="s.scheme" class="slab">
          <div v-if="s.next" class="next">
            <span>
              Hit <b>{{ s.next.from_pct }}%</b> to earn
              <b>{{ s.next.payout_kind === 'Fixed Amount'
                    ? formatRupees(s.next.payout_amount)
                    : s.next.payout_pct + '% of value' }}</b>
            </span>
            <span class="dim">{{ s.next.gap_pct }}% to the next slab</span>
          </div>
          <div v-else class="next"><span class="dim">Top slab. Nothing above this one.</span></div>
        </div>
        <!-- Said plainly, because it is computed from a figure that moves again tonight. -->
        <p class="dim fine">Worked out from last night's figures. Not a promise.</p>
      </section>

      <!-- The four -->
      <section v-if="tiles.length" class="grid">
        <div v-for="t in tiles" :key="t.target_type" class="tile">
          <div class="label">{{ t.target_type }}</div>
          <div class="num tnum">{{ Math.round(t.achievement_pct) }}%</div>
          <div class="dim">{{ show(t) }} of {{ showTarget(t) }}</div>
          <div class="bar thin"><i :style="{ width: width(t.achievement_pct) }"></i></div>
        </div>
      </section>

      <!-- Phase 8: how the month actually went, from the KPI snapshot rather than from a
           target. These have no target beside them on purpose - a rep is measured on them,
           not asked for them, and inventing a goal for each would be inventing six. -->
      <section v-if="measured.length" class="card">
        <div class="row"><h2>How the month is going</h2><span class="dim">measured</span></div>
        <div class="nine">
          <div v-for="m in measured" :key="m.key" class="cell">
            <div class="dim">{{ m.label }}</div>
            <div class="num tnum">{{ measuredValue(m) }}</div>
            <!-- The base always travels with the ratio. 0% over no calls and 0% over twelve
                 are not the same fact, and a number on its own cannot say which. -->
            <div v-if="m.of" class="dim">
              {{ Math.round(m.got) }} of {{ Math.round(m.of) }}
            </div>
          </div>
        </div>
        <p v-if="actual?.totals" class="dim fine">
          {{ actual.totals.days_worked }} day<span v-if="actual.totals.days_worked !== 1">s</span>
          in the field this month.
        </p>
      </section>

      <!-- Category breakdown -->
      <section v-if="categories.length" class="card">
        <div class="row"><h2>By category</h2><span class="dim">Achieved</span></div>
        <div v-for="c in categories" :key="c.target_type + c.item_group + c.brand" class="cat">
          <div class="row">
            <span class="strong">{{ c.item_group || c.brand }}</span>
            <span class="tnum">{{ show(c) }} of {{ showTarget(c) }}
              ({{ Math.round(c.achievement_pct) }}%)</span>
          </div>
          <div class="bar thin" :class="tone(c.achievement_pct)">
            <i :style="{ width: width(c.achievement_pct) }"></i>
          </div>
        </div>
      </section>

      <p v-if="targets.computed_on" class="note dim">
        Counted {{ targets.computed_on.slice(0, 16).replace('T', ' ') }}.
        Today's orders appear tomorrow.
      </p>
    </template>

    <RouterLink to="/expense" class="btn-primary flat">
      <Icon name="receipt" /> Claim expenses
    </RouterLink>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head h1 { font-size: 20px; margin: 0; }
.sub { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.card.money { background: var(--ok-soft); border-color: transparent; }
.label { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.big { font-size: 22px; font-weight: 700; line-height: 1.2; }
.big .of { font-size: 15px; font-weight: 400; color: var(--muted); }
.pct { margin-left: 6px; font-size: 16px; }
.pct.ok { color: var(--ok); } .pct.warn { color: var(--warn); } .pct.crit { color: var(--crit); }
.bar { background: var(--line); border-radius: 999px; height: 12px; overflow: hidden; }
.bar.thin { height: 6px; }
.bar i { display: block; height: 100%; background: var(--primary); border-radius: 999px; }
.bar.ok i { background: var(--ok); }
.bar.warn i { background: var(--warn); }
.bar.crit i { background: var(--crit); }
.need { display: flex; align-items: center; gap: 8px; background: var(--bg);
        border-radius: 8px; padding: 10px; font-size: 14px; }
.need.ok { color: var(--ok); }
.rate { display: flex; flex-direction: column; gap: 2px; background: var(--bg);
        border-radius: 8px; padding: 10px; font-size: 13px; color: var(--muted); }
.rate.ok { background: var(--ok-soft); color: var(--ok); }
.nine { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
.nine .cell { display: flex; flex-direction: column; gap: 1px; }
.nine .num { font-size: 17px; font-weight: 700; }
.tier { background: var(--ok); color: #fff; font-size: 12px; font-weight: 700;
        padding: 2px 10px; border-radius: 999px; }
.slab .next { display: flex; flex-direction: column; gap: 2px; background: var(--surface);
              border-radius: 8px; padding: 10px; font-size: 14px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.tile { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: flex; flex-direction: column; gap: 4px; }
.tile .num { font-size: 18px; font-weight: 700; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.row h2 { font-size: 15px; margin: 0; }
.cat { display: flex; flex-direction: column; gap: 5px; }
.strong { font-weight: 600; }
.dim { color: var(--muted); font-size: 13px; }
.fine { font-size: 12px; margin: 0; }
.note { color: var(--muted); font-size: 13px; text-align: center; }
.note.crit { color: var(--crit); }
.empty { text-align: center; padding: 32px 16px; color: var(--muted);
         display: flex; flex-direction: column; gap: 6px; align-items: center; }
.empty p { margin: 0; }
.btn-primary.flat { display: flex; align-items: center; justify-content: center; gap: 8px;
                    text-decoration: none; padding: 14px; border-radius: 8px; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
