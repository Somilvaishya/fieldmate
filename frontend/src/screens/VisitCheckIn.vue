<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { getPosition } from '../lib/geo'
import * as outletStore from '../stores/outlets'
import * as dayStore from '../stores/day'
import * as visitStore from '../stores/visit'

const route = useRoute()
const router = useRouter()

const outlet = ref(null)
const fix = ref(null)
const locating = ref(true)
const busy = ref(false)
const error = ref('')
const note = ref('')

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
  if (!dayStore.openDay.value) {
    error.value = 'Start your day before visiting a shop.'
    return
  }
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

      <p v-if="distance !== null" class="dist tnum" :class="{ far: outsideFence }">
        <template v-if="outsideFence">
          You are <b>{{ distance }} m</b> from this shop, outside its {{ fenceRadius }} m range.
          You can still check in — your manager will see the distance.
        </template>
        <template v-else>
          <b>{{ distance }} m</b> from the shop.
        </template>
      </p>
      <p v-else-if="fix && !outlet.latitude" class="muted">
        This shop has no saved location, so distance cannot be checked.
      </p>

      <label class="lbl" for="note">Note <span class="muted">(optional)</span></label>
      <input id="note" v-model="note" placeholder="Why this shop, if it is off your route" />

      <p v-if="error" class="err">{{ error }}</p>
    </div>

    <div class="bottom">
      <button class="btn-primary" :disabled="busy" @click="begin">
        {{ busy ? 'Checking in…' : 'Check in' }}
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
.dist { margin-top: 12px; padding: 12px; border-radius: 8px; background: var(--surface);
        border: 1px solid var(--line); }
.dist.far { border-color: var(--warn); color: var(--warn); }
.lbl { display: block; margin: 20px 0 6px; font-weight: 600; }
.err { color: var(--crit); margin-top: 14px; }
.btn-plain { background: none; border: 1px solid var(--line); color: var(--ink); width: 100%; }
</style>
