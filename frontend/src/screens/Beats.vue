<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api/client'
import { db, setMeta, getMeta } from '../db'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'

const beats = ref([])
const note = ref('')
const loading = ref(true)
const visited = ref(new Set())

const sheet = ref(null)      // the beat whose walking order is open
const shops = ref([])
const shopsLoading = ref(false)
// Whether the list we have is the real walking order, or an offline stand-in.
const ordered = ref(true)

onMounted(async () => {
  const today = await visitStore.todaysVisits()
  visited.value = new Set(today.filter((v) => v.state === 'closed').map((v) => v.outlet))

  try {
    const data = await api.myBeats()
    beats.value = data.beats || []
    await setMeta('myBeats', beats.value)
  } catch (e) {
    if (e instanceof ApiError && e.code === 'OFFLINE') {
      beats.value = (await getMeta('myBeats', [])) || []
      note.value = 'Showing the routes saved on this phone.'
    } else {
      note.value = e.message
    }
  } finally {
    loading.value = false
  }
})

const todayBeat = computed(() => beats.value.find((b) => b.runs_today) || null)

function when(beat) {
  if (beat.runs_today) return 'Today'
  if (beat.days_away === 1) return 'Tomorrow'
  if (beat.days_away === null) return 'Not scheduled'
  return `In ${beat.days_away} days`
}

function nextLabel(beat) {
  if (!beat.next_run) return 'No upcoming date'
  const d = new Date(beat.next_run + 'T00:00:00')
  return d.toLocaleDateString('en-IN', { weekday: 'long', day: 'numeric', month: 'short' })
}

const cache = ref({})
function shopsFor(beat) { return cache.value[beat.name] || [] }

/** How far through today's route the rep is.
 *
 * Counted from today's visits directly, not from the beat's shop list: that list is only
 * fetched when the rep opens the walking-order sheet, so reading it here reported
 * "0 visited (0%)" on every card until the sheet had been opened at least once.
 */
function progress(beat) {
  if (!beat.runs_today || !beat.outlet_count) return null
  const known = shopsFor(beat)
  const done = known.length
    ? known.filter((o) => visited.value.has(o.name)).length
    : visited.value.size
  return { done, pct: Math.min(100, Math.round((done / beat.outlet_count) * 100)) }
}

async function open(beat) {
  sheet.value = beat
  shops.value = cache.value[beat.name] || []
  if (shops.value.length) return

  shopsLoading.value = true
  ordered.value = true
  try {
    const data = await api.beatOutlets(beat.name)
    shops.value = data.outlets || []
    cache.value = { ...cache.value, [beat.name]: shops.value }
  } catch {
    // The mirror holds the shops but not the order they are walked in - `sequence` lives on
    // the beat's own child table, which only the route call returns. So the list is shown
    // alphabetically and says so, rather than presenting an arbitrary order as the route.
    const rows = await db.records.where('doctype').equals('FieldMate Outlet').toArray()
    shops.value = rows
      .filter((o) => o.primary_beat === beat.name)
      .sort((a, b) => (a.outlet_name || '').localeCompare(b.outlet_name || ''))
      .map((o) => ({ ...o, sequence: null }))
    ordered.value = false
  } finally {
    shopsLoading.value = false
  }
}

function close() {
  sheet.value = null
}

/** The first shop on the open route that has not been visited today. */
const nextStop = computed(() => {
  // Only meaningful when the list really is the route. Offline the order is alphabetical,
  // and calling an arbitrary shop "next stop" would send a rep the wrong way.
  if (!sheet.value?.runs_today || !ordered.value) return null
  return shops.value.find((o) => !visited.value.has(o.name))?.name || null
})
</script>

<template>
  <div class="wrap screen">
    <h2>My routes</h2>
    <p class="muted sub" v-if="!loading">
      {{ beats.length }} {{ beats.length === 1 ? 'route' : 'routes' }} assigned to you
      <span v-if="note"> · {{ note }}</span>
    </p>

    <div v-if="loading" class="card skeleton">
      <b>Loading your routes…</b>
      <span class="muted">One moment.</span>
    </div>

    <div class="list" v-else-if="beats.length">
      <button v-for="b in beats" :key="b.name" type="button" class="card"
              :class="{ today: b.runs_today }" @click="open(b)">
        <div class="row">
          <span class="line">
            <span class="dot" :class="{ live: b.runs_today }" aria-hidden="true"></span>
            <span class="muted day">Every {{ b.visit_day || b.frequency }}</span>
          </span>
          <span class="when" :class="{ now: b.runs_today }">{{ when(b) }}</span>
        </div>

        <b class="name">{{ b.beat_name }}</b>

        <div class="meta">
          <span class="tnum"><Icon name="store" size="18" /> {{ b.outlet_count }} shops</span>
          <span class="tnum sep" v-if="progress(b)">
            · {{ progress(b).done }} visited ({{ progress(b).pct }}%)
          </span>
          <span class="muted sep" v-else>· {{ b.frequency }}</span>
        </div>

        <div class="track" v-if="progress(b)">
          <div class="fill" :style="{ width: progress(b).pct + '%' }"></div>
        </div>

        <span class="muted next">Next: {{ nextLabel(b) }}</span>

        <span class="open" :class="{ primary: b.runs_today }">
          <span>View {{ b.outlet_count }} shops in walking order</span>
          <Icon name="chevron" size="20" />
        </span>
      </button>
    </div>

    <div v-else-if="!loading" class="empty">
      <Icon name="pin" size="36" />
      <b>You have no route yet</b>
      <p class="muted">
        Ask your manager to assign a route to your FieldMate profile. You can still visit any
        shop in your area from the Shops tab.
      </p>
      <RouterLink to="/outlets" class="ghost">Open shops</RouterLink>
    </div>

    <div class="bottom" v-if="todayBeat">
      <button class="btn-primary" @click="open(todayBeat)">
        Open today's route · {{ todayBeat.beat_name }}
      </button>
    </div>

    <!-- Walking order. A sheet, not a centre modal: it is read one-handed while standing. -->
    <div v-if="sheet" class="scrim" @click.self="close">
      <div class="panel" role="dialog" aria-modal="true" aria-labelledby="sheettitle">
        <button class="grab" aria-label="Close" @click="close"></button>
        <div class="phead">
          <div>
            <span class="eyebrow">{{ sheet.runs_today ? 'Running today' : 'Scheduled route' }}</span>
            <h3 id="sheettitle">{{ sheet.beat_name }}</h3>
            <p class="muted tnum">
              {{ sheet.outlet_count }} shops{{ ordered ? ' in walking order' : ', listed A–Z' }}
            </p>
          </div>
          <button class="x" aria-label="Close" @click="close"><Icon name="close" size="22" /></button>
        </div>

        <div class="stops">
          <p v-if="shopsLoading" class="muted pad">Loading the route…</p>
          <p v-else-if="!shops.length" class="muted pad">
            No shops on this route yet.
          </p>
          <RouterLink v-for="(o, i) in shops" :key="o.name" :to="`/outlet/${o.name}`"
                      class="stop" :class="{ done: visited.has(o.name), next: o.name === nextStop }">
            <span class="seq tnum" :class="{ done: visited.has(o.name) }">{{ o.sequence || i + 1 }}</span>
            <span class="info">
              <span class="title">
                <b>{{ o.outlet_name }}</b>
                <span v-if="o.name === nextStop" class="tag">Next stop</span>
              </span>
              <span class="muted" v-if="visited.has(o.name)">
                <Icon name="check" size="16" /> Visited today
              </span>
              <span class="muted" v-else>{{ o.city || 'No area recorded' }}</span>
            </span>
            <Icon name="chevron" size="20" class="go" />
          </RouterLink>
        </div>

        <div class="pfoot">
          <button class="ghost" @click="close">Close</button>
          <RouterLink v-if="nextStop" class="btn-primary"
                      :to="{ name: 'visit-start', params: { name: nextStop } }" @click="close">
            Start next visit
          </RouterLink>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
h2 { margin: 8px 0 4px; }
.sub { margin: 0 0 12px; }
.muted { color: var(--muted); font-size: 14px; }

.list { display: grid; gap: 10px; }
.card { display: grid; gap: 4px; text-align: left; width: 100%; padding: 14px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        min-height: 48px; }
.card.today { border-color: var(--primary); border-width: 2px; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.line { display: flex; align-items: center; gap: 8px; min-width: 0; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--line); flex: none; }
.dot.live { background: var(--accent); }
.day { font-weight: 600; }
.when { flex: none; font-size: 14px; font-weight: 700; color: var(--muted); }
.when.now { background: var(--primary); color: var(--on-primary); border-radius: 4px;
            padding: 3px 10px; }
.name { font-size: 18px; overflow-wrap: anywhere; }
.meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; font-size: 14px;
        color: var(--ink); }
.meta span { display: inline-flex; align-items: center; gap: 5px; }
.sep { color: var(--ok); font-weight: 600; }
.track { height: 6px; border-radius: 3px; background: var(--primary-soft); overflow: hidden;
         margin: 4px 0 2px; }
.fill { height: 100%; background: var(--ok); }
.next { }
.open { display: flex; align-items: center; justify-content: space-between; gap: 8px;
        margin-top: 8px; min-height: 48px; padding: 0 12px; border-radius: 6px;
        background: var(--primary-soft); color: var(--primary); font-weight: 600; }
.open.primary { background: var(--primary); color: var(--on-primary); }

.skeleton { display: grid; gap: 4px; }
.empty { display: grid; justify-items: center; gap: 6px; text-align: center;
         padding: 40px 16px; color: var(--muted); }
.empty b { color: var(--ink); font-size: 16px; }
.empty p { margin: 0; max-width: 280px; }
.empty .ghost { margin-top: 10px; }

.bottom { position: sticky; bottom: 0; margin-top: auto; padding: 12px 0 4px;
          background: var(--bg); border-top: 1px solid var(--line); }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               padding: 14px; min-height: 52px; border-radius: 6px; text-decoration: none; }
.ghost { display: flex; align-items: center; justify-content: center; min-height: 48px;
         background: var(--surface); color: var(--primary); border: 1px solid var(--primary);
         border-radius: 6px; font-weight: 600; padding: 0 16px; }

.scrim { position: fixed; inset: 0; z-index: 30; display: flex; align-items: flex-end;
         background: rgba(5, 23, 46, 0.6); }
.panel { width: 100%; max-height: 86vh; display: flex; flex-direction: column;
         background: var(--surface); border-top: 1px solid var(--line);
         border-radius: 16px 16px 0 0; }
.grab { width: 100%; min-height: 48px; background: none; border: 0; display: grid;
        place-items: center; padding: 8px 0; }
.grab::before { content: ''; width: 40px; height: 4px; border-radius: 2px;
                background: var(--line); }
.phead { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;
         padding: 0 16px 12px; border-bottom: 1px solid var(--line); }
.eyebrow { display: block; font-size: 14px; font-weight: 700; letter-spacing: 0.04em;
           text-transform: uppercase; color: var(--ok); }
.phead h3 { margin: 2px 0; font-size: 20px; overflow-wrap: anywhere; }
.phead p { margin: 0; }
.x { width: 48px; height: 48px; flex: none; display: grid; place-items: center;
     border-radius: 6px; background: var(--primary-soft); color: var(--primary); border: 0; }

.stops { flex: 1; overflow-y: auto; padding: 12px 16px; display: grid; gap: 8px; }
.pad { padding: 20px 0; text-align: center; }
.stop { display: flex; align-items: center; gap: 10px; padding: 10px 12px; min-height: 64px;
        border: 1px solid var(--line); border-radius: 6px; text-decoration: none;
        color: inherit; background: var(--surface); }
.stop.done { background: var(--bg); }
.stop.next { border-color: var(--primary); border-width: 2px; }
.seq { width: 28px; height: 28px; flex: none; display: grid; place-items: center;
       border-radius: 50%; background: var(--primary-soft); color: var(--primary);
       font-size: 14px; font-weight: 700; }
.seq.done { background: var(--ok); color: var(--surface); }
.info { flex: 1; display: grid; gap: 2px; min-width: 0; }
.title { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
/* Struck-through text is hard to read in sunlight, so a visited stop is marked by its
   green number and its own label instead. */
.info .muted { display: inline-flex; align-items: center; gap: 4px; }
.tag { font-size: 14px; font-weight: 700; padding: 2px 8px; border-radius: 4px;
       background: var(--ok-soft); color: var(--ok); }
.go { color: var(--muted); flex: none; }

.pfoot { display: flex; gap: 8px; padding: 12px 16px;
         padding-bottom: calc(12px + env(safe-area-inset-bottom, 0px));
         border-top: 1px solid var(--line); }
.pfoot > * { flex: 1; }
</style>
