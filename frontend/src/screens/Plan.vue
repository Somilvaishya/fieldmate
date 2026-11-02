<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { isSignedOut } from '../lib/session'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

// The manager's month. Two halves of one job: the beats are the routes, the journey plan is which
// route runs on which day. A manager opens this at the end of a month to build and approve the
// next one, and in between to change a beat when a market changes.
const route = useRoute()
const router = useRouter()

const view = ref(route.query.view === 'beats' ? 'beats' : 'month')
watch(view, (v) => router.replace({ query: { ...route.query, view: v } }))

/** "2026-11-01" for this month plus `offset`. Local time: the month the manager is living in. */
function monthStart(offset) {
  const d = new Date()
  const m = new Date(d.getFullYear(), d.getMonth() + offset, 1)
  return `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, '0')}-01`
}
const MONTHS = computed(() => [
  { key: monthStart(0), label: t('This month') },
  { key: monthStart(1), label: t('Next month') },
])
const month = ref(route.query.month || monthStart(0))
watch(month, (m) => { router.replace({ query: { ...route.query, month: m } }); loadMonth() })

const overview = ref(null)
const beats = ref([])
const loading = ref(true)
const error = ref('')

// The territories this manager may plan in - their Territory User Permission, and what sits under
// it. One territory needs no picker; two or more narrow both halves of the screen.
const territories = ref([])
const territory = ref(route.query.territory || '')
watch(territory, (v) => { router.replace({ query: { ...route.query, territory: v || undefined } }); load() })

async function loadTerritories() {
  try {
    territories.value = (await api.planTerritories()).territories || []
  } catch {
    territories.value = []
  }
}

async function loadMonth() {
  loading.value = true
  error.value = ''
  try {
    overview.value = await api.planOverview(month.value, territory.value || undefined)
  } catch (e) {
    if (isSignedOut(e)) return router.replace('/login')
    error.value = e instanceof ApiError ? e.message : t('Could not load the plans. This needs signal.')
  } finally {
    loading.value = false
  }
}

async function loadBeats() {
  loading.value = true
  error.value = ''
  try {
    beats.value = (await api.planBeats(undefined, territory.value || undefined)).beats || []
  } catch (e) {
    if (isSignedOut(e)) return router.replace('/login')
    error.value = e instanceof ApiError ? e.message : t('Could not load the beats. This needs signal.')
  } finally {
    loading.value = false
  }
}

function load() {
  return view.value === 'beats' ? loadBeats() : loadMonth()
}
watch(view, load)
onMounted(() => { loadTerritories(); load() })

const members = computed(() => overview.value?.members || [])

const STATE = computed(() => ({
  none: { word: t('Not planned'), tone: 'crit' },
  Draft: { word: t('Draft - not approved'), tone: 'warn' },
  Approved: { word: t('Approved'), tone: 'ok' },
}))

// Grouped by rep, because that is how a manager thinks of a route: Ravi's Monday, not FM-BEAT-0012.
const byRep = computed(() => {
  const groups = new Map()
  for (const b of beats.value) {
    if (!groups.has(b.assigned_to)) groups.set(b.assigned_to, { rep: b.rep_name, beats: [] })
    groups.get(b.assigned_to).beats.push(b)
  }
  return [...groups.values()]
})

function when(b) {
  if (b.frequency === 'Weekly') return t('Every {day}', { day: t(b.visit_day) })
  if (b.frequency === 'Fortnightly') return t('{day}, every other week', { day: t(b.visit_day) })
  return t('{day}, week {n} of the month', { day: t(b.visit_day), n: String(b.week_pattern).slice(1) || 1 })
}
</script>

<template>
  <div class="wrap">
    <header class="head">
      <div>
        <h1>{{ t('Plan') }}</h1>
        <p class="dim">{{ t("Your team's routes and their month") }}</p>
      </div>
      <button class="quiet" :disabled="loading" @click="load" :aria-label="t('Refresh')">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <div class="seg" role="tablist">
      <button role="tab" :aria-selected="view === 'month'" :class="{ on: view === 'month' }"
              @click="view = 'month'">{{ t('Journey plans') }}</button>
      <button role="tab" :aria-selected="view === 'beats'" :class="{ on: view === 'beats' }"
              @click="view = 'beats'">{{ t('Beats') }}</button>
    </div>

    <label v-if="territories.length > 1" class="field">
      <span>{{ t('Territory') }}</span>
      <select v-model="territory">
        <option value="">{{ t('All my territories') }}</option>
        <option v-for="name in territories" :key="name" :value="name">{{ name }}</option>
      </select>
    </label>

    <template v-if="view === 'month'">
      <div class="tabs">
        <button v-for="m in MONTHS" :key="m.key" class="chip" :class="{ on: month === m.key }"
                @click="month = m.key">{{ m.label }}</button>
      </div>

      <p v-if="loading && !overview" class="note">{{ t('Loading…') }}</p>
      <p v-else-if="error" class="note crit">{{ error }}</p>
      <template v-else-if="members.length">
        <RouterLink v-for="m in members" :key="m.field_user" class="card"
                    :to="{ name: 'plan-rep', params: { rep: m.field_user }, query: { month } }">
          <div class="top">
            <div class="who">
              <b class="name">{{ m.full_name }}</b>
              <span class="dim">{{ m.beats === 1 ? t('1 beat') : t('{n} beats', { n: m.beats }) }}</span>
            </div>
            <span class="pill" :class="STATE[m.plan ? m.plan.state : 'none'].tone">
              {{ STATE[m.plan ? m.plan.state : 'none'].word }}
            </span>
          </div>
          <span v-if="m.plan" class="dim tnum">
            {{ t('{days} of {working} working days have a beat · {visits} visits', {
                 days: m.plan.planned_days, working: m.plan.working_days, visits: m.plan.planned_visits }) }}
          </span>
          <span v-if="m.plan && m.plan.gaps" class="gap">
            {{ m.plan.gaps === 1 ? t('1 working day with no beat') : t('{n} working days with no beat', { n: m.plan.gaps }) }}
          </span>
          <span v-if="!m.beats" class="gap">{{ t('No beats yet - make one before planning the month.') }}</span>
        </RouterLink>
      </template>
      <div v-else class="empty">
        <Icon name="team" size="34" />
        <b>{{ t('Nobody reports to you yet') }}</b>
      </div>
    </template>

    <template v-else>
      <RouterLink :to="{ name: 'plan-beat', params: { name: 'new' } }" class="new">
        <Icon name="plus" size="18" /><span>{{ t('New beat') }}</span>
      </RouterLink>

      <p v-if="loading && !beats.length" class="note">{{ t('Loading…') }}</p>
      <p v-else-if="error" class="note crit">{{ error }}</p>
      <template v-else-if="byRep.length">
        <section v-for="g in byRep" :key="g.rep" class="group">
          <h2>{{ g.rep }}</h2>
          <RouterLink v-for="b in g.beats" :key="b.name" class="card beat"
                      :class="{ off: !b.is_active }"
                      :to="{ name: 'plan-beat', params: { name: b.name } }">
            <div class="top">
              <div class="who">
                <b class="name">{{ b.beat_name }}</b>
                <span class="dim">{{ when(b) }}</span>
              </div>
              <span class="dim tnum">{{ b.outlet_count === 1 ? t('1 shop') : t('{n} shops', { n: b.outlet_count }) }}</span>
            </div>
            <span v-if="!b.is_active" class="pill flat">{{ t('Switched off') }}</span>
          </RouterLink>
        </section>
      </template>
      <div v-else class="empty">
        <Icon name="route" size="34" />
        <b>{{ t('No beats yet') }}</b>
        <p class="dim">{{ t('A beat is a route: the shops one rep walks on one day.') }}</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.head h1 { font-size: 20px; margin: 0; }
.dim { color: var(--muted); font-size: 13px; margin: 0; }
.quiet { border: 0; background: none; color: var(--muted); min-height: 44px; padding: 0 6px; }

.seg { display: grid; grid-template-columns: 1fr 1fr; border: 1px solid var(--line);
       border-radius: 10px; overflow: hidden; }
.seg button { min-height: 44px; border: 0; background: var(--surface); color: var(--ink);
              font-weight: 600; font-size: 14px; }
.seg button.on { background: var(--primary); color: var(--on-primary); }

.field { display: flex; flex-direction: column; gap: 6px; }
.field > span { font-size: 13px; font-weight: 700; color: var(--muted); }
.tabs { display: flex; gap: 8px; overflow-x: auto; }
.chip { flex: none; padding: 0 16px; min-height: 44px; border: 1px solid var(--line);
        background: var(--surface); border-radius: 999px; color: var(--ink); font-weight: 600;
        font-size: 14px; }
.chip.on { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: flex; flex-direction: column; gap: 4px; color: inherit;
        text-decoration: none; }
.card:active { background: var(--primary-soft); }
.card.off { opacity: .7; }
.top { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.who { display: flex; flex-direction: column; min-width: 0; }
.name { font-size: 16px; overflow-wrap: anywhere; }
.pill { flex: none; align-self: flex-start; font-size: 12px; font-weight: 700; padding: 3px 8px;
        border-radius: 6px; white-space: nowrap; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.crit { background: var(--crit-soft); color: var(--crit); }
.pill.flat { background: var(--primary-soft); color: var(--primary); }
.gap { font-size: 13px; font-weight: 600; color: var(--warn); }

.group { display: flex; flex-direction: column; gap: 8px; }
.group h2 { font-size: 14px; margin: 4px 2px 0; color: var(--muted); font-weight: 700; }
.new { display: inline-flex; align-items: center; justify-content: center; gap: 6px;
       min-height: 48px; border-radius: 8px; border: 1px solid var(--primary);
       color: var(--primary); background: var(--surface); font-weight: 700;
       text-decoration: none; }

.note { color: var(--muted); font-size: 14px; text-align: center; padding: 20px 0; margin: 0; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.empty { text-align: center; padding: 40px 16px; color: var(--muted); display: flex;
         flex-direction: column; gap: 6px; align-items: center; }
.empty b { color: var(--ink); }
.empty p { margin: 0; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
