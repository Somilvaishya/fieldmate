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

const openVisit = visitStore.activeVisit

/** Shops already visited today, so a rep can see their progress down the route. */
const visitedOutlets = computed(
  () => new Set(doneToday.value.filter((v) => v.state === 'closed').map((v) => v.outlet))
)

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
    if (openDay.value) beat.value = await api.todayBeat()
    await pull()
    // Survey definitions and no-order reasons are cached whole: a rep in a basement market
    // still has to be able to open the form and say why no order came of the visit.
    await visitStore.refreshForms()
    await visitStore.refreshReasons()
  } catch (e) {
    if (handle(e)) return
    await showCached()
    await dayStore.refresh().catch(() => {})
  }
  await visitStore.resume()
  doneToday.value = await visitStore.todaysVisits()
  queued.value = await pendingCount()
  pings.value = await pendingPings()
  photosWaiting.value = await photoQueue.pendingCount()
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
        <b>Still in {{ openVisit.outletName }}</b>
        <span class="muted">Tap to carry on, or to finish the visit.</span>
      </RouterLink>

      <!-- The day -->
      <div v-if="openDay" class="card open">
        <div class="row">
          <b>Day running</b>
          <span class="muted tnum" v-if="started">since {{ started }}</span>
        </div>
        <p class="muted" v-if="openDay.planned_beat">Beat: {{ openDay.planned_beat }}</p>
        <p class="muted" v-else>No beat planned for today.</p>
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
      <template v-if="openDay && beat?.outlets?.length">
        <h3 class="tnum">
          {{ visitedOutlets.size }} of {{ beat.outlets.length }} shops done
        </h3>
        <RouterLink v-for="o in beat.outlets" :key="o.name" :to="`/outlet/${o.name}`"
                    class="shop" :class="{ visited: visitedOutlets.has(o.name) }">
          <span class="seq tnum">{{ o.sequence }}</span>
          <span class="info">
            <b>{{ o.outlet_name }}</b>
            <span class="muted">{{ o.city || '—' }}<em v-if="o.is_mandatory"> · must visit</em></span>
          </span>
          <span v-if="visitedOutlets.has(o.name)" class="pill done">Visited</span>
          <span v-else-if="o.approval_status !== 'Approved'" class="pill">Pending</span>
        </RouterLink>
      </template>
    </div>

    <!-- Primary action in the bottom third, where a thumb reaches -->
    <div class="bottom">
      <RouterLink v-if="!openDay" to="/day/start" class="btn-primary">Start day</RouterLink>
      <RouterLink v-else to="/day/end" class="btn-primary">Finish day</RouterLink>
      <button class="ghost" :disabled="syncing" @click="syncNow">
        {{ syncing ? 'Syncing…' : `Sync now (${queued + photosWaiting} queued)` }}
      </button>
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
.shop.visited { opacity: 0.72; }
.pill.done { border-color: var(--ok); color: var(--ok); }
.card p { margin: 4px 0 0; }
.row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.shop { display: flex; align-items: center; gap: 10px; padding: 12px; margin-bottom: 8px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
        text-decoration: none; color: inherit; min-height: 48px; }
.seq { width: 24px; color: var(--muted); font-size: 14px; }
.info { flex: 1; display: grid; gap: 1px; min-width: 0; }
.info b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
em { font-style: normal; }
.pill { font-size: 12px; padding: 2px 6px; border-radius: 3px; border: 1px solid var(--warn);
        color: var(--warn); }
.btn-primary { display: block; text-align: center; text-decoration: none; padding: 14px; }
.ghost { width: 100%; background: transparent; color: var(--primary);
         border: 1px solid var(--primary); }
</style>
