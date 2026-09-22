<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { getPosition } from '../lib/geo'
import { compress } from '../lib/image'
import { getMeta } from '../db'
import * as dayStore from '../stores/day'

const router = useRouter()
const fix = ref(null)
const selfie = ref(null)
const selfieKb = ref(0)
const odometer = ref('')
const busy = ref(false)
const locating = ref(false)
const error = ref('')

async function locate() {
  error.value = ''
  locating.value = true
  try {
    fix.value = await getPosition()
  } catch (e) {
    error.value = e.message
  } finally {
    locating.value = false
  }
}

async function onSelfie(event) {
  const file = event.target.files?.[0]
  if (!file) return
  error.value = ''
  try {
    const settings = (await getMeta('profile'))?.settings || {}
    const out = await compress(file, {
      maxKb: settings.photo_max_kb || 120,
      maxPx: settings.photo_max_dimension_px || 1280,
    })
    selfie.value = out.dataUrl
    selfieKb.value = out.kb
  } catch {
    error.value = 'Could not read that photo. Try taking it again.'
  }
}

async function begin() {
  error.value = ''
  if (!selfie.value) return (error.value = 'Take the start-of-day photo first.')
  busy.value = true
  try {
    await dayStore.start({
      ...(fix.value || {}),
      selfie: selfie.value,
      odometer_start: odometer.value ? Number(odometer.value) : null,
    })
    router.replace('/today')
  } catch (e) {
    error.value = e instanceof ApiError
      ? e.message
      : 'Could not start your day. Try again in a moment.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap screen">
    <div class="top">
      <h2>Start your day</h2>
      <p class="muted">A photo and a location fix, then you are on the road.</p>

      <button type="button" class="tile" :class="{ done: fix }" @click="locate" :disabled="locating">
        <b>{{ locating ? 'Getting a fix…' : fix ? 'Location captured' : 'Capture location' }}</b>
        <span v-if="fix" class="muted tnum">±{{ fix.accuracy_m }} m · {{ fix.location_provider }}</span>
        <span v-else class="muted">Needed so your day starts where you are</span>
      </button>

      <label class="tile" :class="{ done: selfie }">
        <b>{{ selfie ? 'Photo taken' : 'Take start-of-day photo' }}</b>
        <span v-if="selfie" class="muted tnum">{{ selfieKb }} KB</span>
        <span v-else class="muted">Required</span>
        <input id="selfie" type="file" accept="image/*" capture="user" hidden @change="onSelfie" />
      </label>

      <label class="odo" for="odo">Odometer <span class="muted">(optional)</span></label>
      <input id="odo" v-model="odometer" inputmode="numeric" placeholder="e.g. 45120" />

      <p v-if="error" class="err">{{ error }}</p>
    </div>

    <div class="bottom">
      <button class="btn-primary" :disabled="busy" @click="begin">
        {{ busy ? 'Starting…' : 'Start day' }}
      </button>
      <p class="muted note">Your location is recorded through the day and stops when you finish.</p>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; }
.bottom { padding-top: 16px; }
h2 { margin: 8px 0 4px; }
.muted { color: var(--muted); font-size: 14px; }
.tile { display: block; width: 100%; text-align: left; margin-top: 12px; padding: 14px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
        min-height: 48px; cursor: pointer; }
.tile b { display: block; }
.tile.done { border-color: var(--ok); }
.odo { display: block; margin: 20px 0 6px; font-weight: 600; }
.err { color: var(--crit); margin-top: 14px; }
.note { margin-top: 10px; text-align: center; }
</style>
