<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid, getMeta, setMeta } from '../db'
import { pull, drain, pendingCount } from '../sync/outbox'
import { pendingPings, configure as configurePinger, resumeIfDayOpen } from '../sync/pinger'
import * as dayStore from '../stores/day'
import * as visitStore from '../stores/visit'
import * as photoQueue from '../sync/photos'
import Icon from '../components/Icon.vue'

const router = useRouter()
const boot = ref(null)
const beat = ref(null)
const error = ref('')
const stale = ref(false)
const queued = ref(0)
const pings = ref(0)
const syncing = ref(false)
const online = ref(navigator.onLine)
const photosWaiting = ref(0)
const doneToday = ref([])
const loading = ref(true)

const openVisit = visitStore.activeVisit

/** Shops already visited today, so a rep can see their progress down the route. */
const visitedOutlets = computed(
  () => new Set(doneToday.value.filter((v) => v.state === 'closed').map((v) => v.outlet))
)

const shops = computed(() => beat.value?.outlets || [])
const doneCount = computed(
  () => shops.value.filter((o) => visitedOutlets.value.has(o.name)).length
)
const percent = computed(
  () => (shops.value.length ? Math.round((doneCount.value / shops.value.length) * 100) : 0)
)

/** The next shop down the route that has not been visited yet. */
const nextShop = computed(
  () => shops.value.find((o) => !visitedOutlets.value.has(o.name)) || null
)

/** Everything waiting to leave this phone - records and photos both. */
const waiting = computed(() => queued.value + photosWaiting.value)

const onOnline = () => (online.value = true)
const onOffline = () => (online.value = false)

const openDay = dayStore.openDay
const started = computed(() =>
  openDay.value?.started_at ? openDay.value.started_at.slice(11, 16) : null
)

function handle(e) {
  if (e instanceof ApiError && ['AUTH_REQUIRED', 'LOGIN_FAILED'].includes(e.code)) {
    router.replace('/login')
    return true
  }
  if (!(e instanceof ApiError && e.code === 'OFFLINE')) error.value = e.message
  return false
}

async function showCached() {
  const cached = await getMeta('profile')
  if (cached) {
    boot.value = cached
    stale.value = true
  }
}

async function load() {
  error.value = ''
  try {
    const profile = await api.bootstrap()
    await setMeta('profile', profile)
    boot.value = profile
    stale.value = false
    configurePinger(profile.settings || {})

    await api.registerDevice(await deviceUuid(), {
      platform: 'Web', app_version: '0.0.1',
      device_name: navigator.userAgent.slice(0, 60),
    })

    await dayStore.refresh()
    if (openDay.value) {
      beat.value = await api.todayBeat()
      // Kept, or the route vanishes the moment the rep reloads with no signal - and the
      // primary action silently becomes "Finish day" halfway through the morning.
      await setMeta('todayBeat', beat.value)
    }
    await pull()
    // Survey definitions and no-order reasons are cached whole: a rep in a basement market
    // still has to be able to open the form and say why no order came of the visit.
    await visitStore.refreshForms()
    await visitStore.refreshReasons()
  } catch (e) {
    if (handle(e)) return
    // Only fall back to the cached profile if the live one never arrived. A failure in a
    // later step used to overwrite a profile that had just been fetched successfully and
    // flip the screen into its stale state for no reason.
    if (!boot.value) await showCached()
    await dayStore.refresh().catch(() => {})
    if (!beat.value) beat.value = await getMeta('todayBeat')
  }
  await visitStore.resume()
  doneToday.value = await visitStore.todaysVisits()
  queued.value = await pendingCount()
  pings.value = await pendingPings()
  photosWaiting.value = await photoQueue.pendingCount()
  loading.value = false
}

async function syncNow() {
  if (!online.value) {
    error.value = 'Still offline. Everything you captured is saved and will sync on its own.'
    return
  }
  syncing.value = true
  // Records first, photos after. A day of coverage must not sit behind one shelf photo
  // crawling up a slow link.
  await drain().catch(() => {})
  await photoQueue.drain().catch(() => {})
  await load()
  syncing.value = false
}

onMounted(async () => {
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  await resumeIfDayOpen()
  await load()
})
onUnmounted(() => {
  window.removeEventListener('online', onOnline)
  window.removeEventListener('offline', onOffline)
})
</script>

<template>
  <div class="wrap screen">
    <div class="top">
      <h2>Today</h2>
      <p v-if="error" class="err">{{ error }}</p>

      <!-- Who you are, and whether this is live or remembered -->
      <div v-if="boot" class="who">
        <b>{{ boot.full_name }}</b>
        <span class="muted">{{ (boot.roles || []).join(', ') || 'No FieldMate role' }}</span>
        <span v-if="stale" class="muted">Showing your last saved details. Reconnect to refresh.</span>
      </div>

      <!-- A visit left open. Top of the screen, because it is the only thing that matters
           until it is closed: an open visit blocks the next check-in. -->
      <RouterLink v-if="openVisit" class="card resume"
                  :to="{ name: 'visit', params: { uuid: openVisit.clientUuid } }">
        <span class="line">
          <span class="dot live" aria-hidden="true"></span>
          <b>Still in {{ openVisit.outletName }}</b>
        </span>
        <span class="muted">Tap to carry on, or to finish the visit.</span>
        <Icon class="go" name="chevron" size="26" />
      </RouterLink>

      <!-- Loading has its own state. Showing "Day not started" with a Start day button
           while the day is still being fetched told a rep the opposite of the truth. -->
      <div v-if="loading" class="card">
        <b>Loading your day…</b>
        <p class="muted">One moment.</p>
      </div>

      <!-- The day -->
      <div v-else-if="openDay" class="card open">
        <div class="row">
          <span class="line">
            <span class="dot live" aria-hidden="true"></span>
            <b>Day running<span v-if="started" class="tnum"> since {{ started }}</span></b>
          </span>
          <span class="badge">Active</span>
        </div>
        <p class="muted" v-if="openDay.planned_beat">
          {{ openDay.planned_beat_name || openDay.planned_beat }}
        </p>
        <p class="muted" v-else>No beat planned for today.</p>

        <template v-if="shops.length">
          <div class="row progress-head">
            <b class="tnum">{{ doneCount }} of {{ shops.length }} shops done</b>
            <span class="muted tnum">{{ percent }}% complete</span>
          </div>
          <div class="track" role="progressbar" :aria-valuenow="percent"
               aria-valuemin="0" aria-valuemax="100">
            <div class="fill" :style="{ width: percent + '%' }"></div>
          </div>
        </template>

        <p class="muted tnum" v-if="pings">{{ pings }} location points waiting to upload</p>
      </div>

      <div v-else class="card">
        <b>Day not started</b>
        <p class="muted" v-if="dayStore.plannedToday.value?.beat">
          Planned: {{ dayStore.plannedToday.value.beat }}
          ({{ dayStore.plannedToday.value.outlet_count }} shops)
        </p>
        <p class="muted" v-else-if="dayStore.plannedToday.value?.status === 'Holiday'">
          Today is a holiday.
        </p>
        <p class="muted" v-else>Start your day to load your route.</p>
      </div>

      <!-- Today's shops -->
      <template v-if="openDay && shops.length">
        <div class="section">
          <h3>Today's shops</h3>
          <span class="muted tnum">{{ shops.length }} in walking order</span>
        </div>
        <RouterLink v-for="o in shops" :key="o.name" :to="`/outlet/${o.name}`"
                    class="shop" :class="{ visited: visitedOutlets.has(o.name) }">
          <span class="seq tnum">{{ o.sequence }}</span>
          <span class="info">
            <b>{{ o.outlet_name }}</b>
            <span class="muted">{{ o.city || '—' }}<em v-if="o.is_mandatory"> · must visit</em></span>
          </span>
          <span v-if="visitedOutlets.has(o.name)" class="pill done">
            <Icon name="check" size="18" /> Visited
          </span>
          <span v-else-if="o.approval_status !== 'Approved'" class="pill">
            <Icon name="alert" size="18" /> Pending
          </span>
          <Icon v-else class="go" name="chevron" size="22" />
        </RouterLink>
      </template>
    </div>

    <!-- Primary action in the bottom third, where a thumb reaches. It follows what the rep
         is actually doing: carry on with an open visit, else walk to the next shop, else
         close the day. Finish day stays reachable throughout - a rep who cannot end their
         day is stuck. -->
    <div class="bottom">
      <RouterLink v-if="openVisit" class="btn-primary"
                  :to="{ name: 'visit', params: { uuid: openVisit.clientUuid } }">
        Carry on in {{ openVisit.outletName }}
      </RouterLink>
      <button v-else-if="loading" class="btn-primary" disabled>Loading…</button>
      <RouterLink v-else-if="!openDay" to="/day/start" class="btn-primary">Start day</RouterLink>
      <RouterLink v-else-if="nextShop" class="btn-primary"
                  :to="{ name: 'visit-start', params: { name: nextShop.name } }">
        Start next visit &middot; {{ nextShop.outlet_name }}
      </RouterLink>
      <RouterLink v-else to="/day/end" class="btn-primary">Finish day</RouterLink>

      <div class="also">
        <RouterLink v-if="openDay && (nextShop || openVisit)" to="/day/end" class="ghost">
          Finish day
        </RouterLink>
        <button class="ghost" :disabled="syncing" @click="syncNow">
          {{ syncing ? 'Syncing…' : waiting ? `Sync now (${waiting})` : 'Sync now' }}
        </button>
      </div>

      <!-- Honest about where the work is. It is saved on this phone, not encrypted -
           nothing in the app encrypts the Dexie store, and SECURITY.md calls mirrored
           device data a disclosure surface. Claiming otherwise would be a lie to a rep. -->
      <p class="assurance" v-if="waiting">
        <Icon name="cloud-off" size="18" />
        <span class="tnum">{{ waiting }} saved on this phone, waiting to sync</span>
      </p>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; }
.bottom { padding-top: 16px; display: grid; gap: 8px; }
h2 { margin: 8px 0 12px; }
h3 { margin: 20px 0 8px; font-size: 1rem; }
.muted { color: var(--muted); font-size: 14px; }
.err { color: var(--crit); }
.who { display: grid; gap: 2px; margin-bottom: 12px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
        padding: 12px; margin-bottom: 12px; }
.card.open { border-color: var(--ok); }
.card.resume { display: grid; gap: 2px; border-color: var(--primary); text-decoration: none;
               color: inherit; }
/* A tinted ground, not opacity. `opacity: 0.72` composited the whole row against the page
   and pulled its secondary text to 3.68:1 and its pill to 2.82:1 - under the 4.5:1 floor
   the whole palette was derived to guarantee. The row still reads as done; it stays
   legible in sunlight. */
.shop.visited { background: var(--bg); }
.pill.done { border-color: var(--ok); color: var(--ok); }
.card p { margin: 4px 0 0; }
.row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }

.line { display: flex; align-items: center; gap: 8px; min-width: 0; }
/* A steady dot, not a pulsing one. Decorative motion that never stops costs frames on a
   four-year-old Android, and DESIGN.md rules it out. */
.dot { width: 10px; height: 10px; border-radius: 50%; flex: none; background: var(--muted); }
.dot.live { background: var(--accent); }
.badge { font-size: 14px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
         color: var(--ok); }

.progress-head { margin-top: 8px; }
.track { height: 6px; border-radius: 3px; background: var(--primary-soft); margin-top: 8px;
         overflow: hidden; }
.fill { height: 100%; background: var(--primary); border-radius: 3px; transition: width 150ms; }
@media (prefers-reduced-motion: reduce) { .fill { transition: none; } }

.section { display: flex; justify-content: space-between; align-items: baseline;
           margin: 20px 0 8px; gap: 8px; }
.section h3 { margin: 0; font-size: 16px; }

.shop { display: flex; align-items: center; gap: 10px; padding: 12px; margin-bottom: 8px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        text-decoration: none; color: inherit; min-height: 56px; }
.seq { width: 22px; color: var(--muted); font-size: 14px; flex: none; }
.info { flex: 1; display: grid; gap: 1px; min-width: 0; }
/* The shop name wraps rather than truncating. It is how a rep identifies the row, and
   "5. Anand Super …" identifies nothing. */
.info b { overflow-wrap: anywhere; }
.info .muted { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
em { font-style: normal; }
.go { color: var(--muted); flex: none; }
.resume .go { color: var(--primary); align-self: center; }

.pill { display: inline-flex; align-items: center; gap: 4px; flex: none;
        font-size: 14px; font-weight: 600; padding: 4px 8px; border-radius: 4px;
        border: 1px solid var(--warn); color: var(--warn); background: var(--warn-soft); }
.pill.done { border-color: var(--ok); color: var(--ok); background: var(--ok-soft); }

/* Sticky, not fixed. The app already has a tab bar below this; a fixed bar would sit on
   top of it. Sticking to the bottom of the scroll container puts it above the tabs. */
.bottom { position: sticky; bottom: 0; padding: 12px 0 4px; display: grid; gap: 8px;
          background: var(--bg); border-top: 1px solid var(--line); margin-top: 8px; }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               text-align: center; text-decoration: none; padding: 14px; min-height: 52px;
               border-radius: 6px; }
.also { display: flex; gap: 8px; }
.ghost { flex: 1; background: var(--surface); color: var(--primary);
         border: 1px solid var(--primary); border-radius: 6px; font-weight: 600;
         display: flex; align-items: center; justify-content: center; text-decoration: none;
         min-height: 48px; padding: 0 8px; }
.assurance { display: flex; align-items: center; justify-content: center; gap: 6px;
             margin: 0; color: var(--muted); font-size: 14px; }
</style>
