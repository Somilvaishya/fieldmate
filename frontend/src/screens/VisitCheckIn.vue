<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { getPosition } from '../lib/geo'
import * as outletStore from '../stores/outlets'
import * as dayStore from '../stores/day'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'

const REASONS = [
  'Shop has moved',
  'Met the owner elsewhere',
  'Shutter down, met outside',
  'GPS drifting here',
]

const route = useRoute()
const router = useRouter()

const outlet = ref(null)
const fix = ref(null)
const locating = ref(true)
const busy = ref(false)
const error = ref('')
const note = ref('')

// Checked before the rep touches anything, not after they tap. The old screen let them take a
// fix, type a note and press a live button that silently refused - the one reading of a dead
// control is that the app is broken.
const dayOpen = computed(() => !!dayStore.openDay.value)

const distance = computed(() => {
  if (!fix.value || !outlet.value?.latitude || !outlet.value?.longitude) return null
  return Math.round(haversineM(
    outlet.value.latitude, outlet.value.longitude,
    fix.value.latitude, fix.value.longitude,
  ))
})

const fenceRadius = computed(() => outlet.value?.geo_fence_radius_m || 0)
const outsideFence = computed(
  () => distance.value !== null && fenceRadius.value > 0 && distance.value > fenceRadius.value
)

function haversineM(lat1, lon1, lat2, lon2) {
  const R = 6371000
  const toRad = (d) => (d * Math.PI) / 180
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}

onMounted(async () => {
  // Read from the mirror, not the network: a rep standing at the counter with no bars must
  // still be able to check in.
  outlet.value = await outletStore.localOutlet(route.params.name)
  await locate()
})

async function locate() {
  locating.value = true
  error.value = ''
  try {
    fix.value = await getPosition()
  } catch (e) {
    error.value = e.message
  } finally {
    locating.value = false
  }
}

async function begin() {
  error.value = ''
  if (!dayOpen.value) return router.push('/day/start')
  busy.value = true
  try {
    const visit = await visitStore.checkIn(outlet.value, {
      fix: fix.value || {},
      deviationNote: note.value || null,
    })
    router.replace({ name: 'visit', params: { uuid: visit.clientUuid } })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not check in. Try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap screen" v-if="outlet">
    <div class="top">
      <h2>{{ outlet.outlet_name }}</h2>
      <p class="muted">{{ outlet.city || '' }}<span v-if="outlet.mobile_no"> · {{ outlet.mobile_no }}</span></p>

      <button type="button" class="tile" :class="{ done: fix }" @click="locate" :disabled="locating">
        <b>{{ locating ? 'Getting a fix…' : fix ? 'Location captured' : 'Capture location' }}</b>
        <span v-if="fix" class="muted tnum">±{{ fix.accuracy_m }} m</span>
        <span v-else-if="!locating" class="muted">Tap to try again</span>
      </button>

      <!-- Being far away is recorded, never refused. This card has to read as a fact being
           logged, not a door being closed - a rep who reads it as a rejection stops checking
           in at all, and then there is no coverage data to act on. -->
      <div v-if="outsideFence" class="dist far">
        <b class="tnum">You are {{ distance }} m from this shop, outside its
          {{ fenceRadius }} m range.</b>
        <p>You can still check in. Your manager will see the distance saved with this visit.</p>
        <div class="facts">
          <span class="tnum"><Icon name="pin" size="16" /> Now: {{ distance }} m away</span>
          <span class="tnum"><Icon name="check" size="16" /> Usual range: {{ fenceRadius }} m
            or less</span>
        </div>
      </div>
      <p v-else-if="distance !== null" class="dist tnum">
        <b>{{ distance }} m</b> from the shop.
      </p>
      <p v-else-if="fix && !outlet.latitude" class="muted">
        This shop has no saved location, so distance cannot be checked.
      </p>

      <label class="lbl" for="note">
        {{ outsideFence ? 'Reason for the distance' : 'Note' }}
        <span class="muted">(optional)</span>
      </label>
      <input id="note" v-model="note"
             :placeholder="outsideFence
               ? 'e.g. shop has moved, met the owner elsewhere'
               : 'Why this shop, if it is off your route'" />
      <!-- Typed one-handed at a doorstep, so the common answers are one tap. -->
      <div class="chips" v-if="outsideFence">
        <button v-for="r in REASONS" :key="r" type="button" class="chip" @click="note = r">
          + {{ r }}
        </button>
      </div>

      <p v-if="!dayOpen" class="notice">
        <Icon name="alert" />
        <span>Your day has not started yet. Start it and this shop will be waiting.</span>
      </p>
      <p v-if="error" class="err">{{ error }}</p>
    </div>

    <div class="bottom">
      <button class="btn-primary" :disabled="busy" @click="begin">
        {{ busy ? 'Checking in…'
           : !dayOpen ? 'Start my day'
           : outsideFence ? 'Check in with the distance logged'
           : 'Check in' }}
      </button>
      <button class="btn-plain" @click="router.back()">Cancel</button>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; }
.bottom { padding-top: 16px; display: grid; gap: 8px; }
h2 { margin: 8px 0 4px; }
.muted { color: var(--muted); font-size: 14px; }
.tile { display: block; width: 100%; text-align: left; margin-top: 12px; padding: 14px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
        min-height: 48px; cursor: pointer; }
.tile b { display: block; }
.tile.done { border-color: var(--ok); }
.dist { margin-top: 12px; padding: 12px; border-radius: 6px; background: var(--surface);
        border: 1px solid var(--line); }
.dist.far { border-color: var(--warn); background: var(--warn-soft); color: var(--warn); }
.dist.far b { display: block; font-size: 16px; line-height: 1.4; }
.dist.far p { margin: 6px 0 0; font-size: 14px; }
.facts { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.facts span { display: inline-flex; align-items: center; gap: 6px; font-size: 14px;
              font-weight: 600; padding: 5px 10px; border-radius: 4px;
              background: var(--surface); border: 1px solid var(--warn); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.chip { min-height: 48px; padding: 0 12px; border-radius: 6px; font-size: 14px;
        font-weight: 600; background: var(--primary-soft); border: 0; color: var(--primary); }
.lbl { display: block; margin: 20px 0 6px; font-weight: 600; }
.err { color: var(--crit); margin-top: 14px; }
.notice { display: flex; align-items: flex-start; gap: 8px; margin-top: 14px;
          background: var(--warn-soft); color: var(--warn);
          border-radius: 6px; padding: 10px 12px; font-size: 14px; line-height: 1.45; }
.notice :deep(.icon) { margin-top: 1px; flex-shrink: 0; }
.btn-plain { background: none; border: 1px solid var(--line); color: var(--ink); width: 100%; }
</style>
