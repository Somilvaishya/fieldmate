<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getMeta } from '../db'
import { compress } from '../lib/image'
import { getPosition } from '../lib/geo'
import * as visitStore from '../stores/visit'
import * as photoQueue from '../sync/photos'

const router = useRouter()
const visit = visitStore.activeVisit
const elapsed = ref(0)
const photos = ref(0)
const error = ref('')
const busy = ref(false)

const answered = computed(() => {
  if (!visit.value) return { done: 0, total: 0 }
  const shown = visitStore.visibleQuestions(visit.value)
  return { done: shown.filter((q) => q.is_answered).length, total: shown.length }
})

const short = computed(
  () => visit.value?.minVisitMinutes > 0 && elapsed.value < visit.value.minVisitMinutes
)

onMounted(async () => {
  if (!visit.value) await visitStore.resume()
  if (!visit.value) return router.replace('/today')
  photos.value = await photoQueue.pendingCount(visit.value.clientUuid)
  tick()
  setInterval(tick, 20000)
})

function tick() {
  if (!visit.value?.checkInTime) return
  const started = new Date(visit.value.checkInTime.replace(' ', 'T'))
  elapsed.value = Math.max(0, Math.round((Date.now() - started.getTime()) / 60000))
}

async function onPhoto(event) {
  const file = event.target.files?.[0]
  if (!file) return
  error.value = ''
  busy.value = true
  try {
    const settings = (await getMeta('profile'))?.settings || {}
    const out = await compress(file, {
      maxKb: settings.photo_max_kb || 120,
      maxPx: settings.photo_max_dimension_px || 1280,
    })
    const fix = await getPosition().catch(() => ({}))
    await visitStore.addPhoto({
      dataUrl: out.dataUrl, purpose: 'Shelf', kb: out.kb, fix,
    })
    photos.value = await photoQueue.pendingCount(visit.value.clientUuid)
    photoQueue.drain().catch(() => {})
  } catch {
    error.value = 'Could not read that photo. Try taking it again.'
  } finally {
    busy.value = false
    event.target.value = ''
  }
}
</script>

<template>
  <div class="wrap screen" v-if="visit">
    <header class="head">
      <h2>{{ visit.outletName }}</h2>
      <p class="muted tnum">
        In the shop {{ elapsed }} min
        <span v-if="visit.distanceM !== null"> · {{ Math.round(visit.distanceM) }} m away</span>
        <span v-if="visit.createdOffline"> · saved on this phone</span>
      </p>
      <p v-if="visit.isGeoFenceBreach" class="flag">
        Checked in outside this shop's range. Your manager will see it.
      </p>
    </header>

    <ul class="jobs">
      <li>
        <RouterLink class="job" :to="{ name: 'visit-checklist' }">
          <b>Checklist</b>
          <span class="muted tnum" v-if="answered.total">
            {{ answered.done }} of {{ answered.total }} answered
          </span>
          <span class="muted" v-else>No questions for this shop</span>
        </RouterLink>
      </li>
      <li>
        <RouterLink class="job" :to="{ name: 'visit-merchandising' }">
          <b>Shelf check</b>
          <span class="muted">What is on the shelf, and the competition</span>
        </RouterLink>
      </li>
      <li>
        <label class="job">
          <b>{{ busy ? 'Saving photo…' : 'Add a photo' }}</b>
          <span class="muted tnum" v-if="photos">{{ photos }} waiting to send</span>
          <span class="muted" v-else>Shelf, board, damage</span>
          <input type="file" accept="image/*" capture="environment" hidden @change="onPhoto" />
        </label>
      </li>
    </ul>

    <label class="lbl" for="remarks">Remarks</label>
    <textarea id="remarks" v-model="visit.remarks" rows="3"
              placeholder="Anything worth telling your manager" @blur="visitStore.saveProgress()" />

    <p v-if="error" class="err">{{ error }}</p>

    <div class="bottom">
      <p v-if="short" class="muted note">
        A visit here usually takes at least {{ visit.minVisitMinutes }} minutes.
      </p>
      <button class="btn-primary" @click="router.push({ name: 'visit-checkout' })">
        Finish visit
      </button>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.head { margin-bottom: 8px; }
h2 { margin: 8px 0 4px; }
.muted { color: var(--muted); font-size: 14px; }
.flag { margin: 10px 0 0; padding: 10px 12px; border-radius: 8px; color: var(--warn);
        border: 1px solid var(--warn); background: var(--surface); font-size: 14px; }
.jobs { list-style: none; padding: 0; margin: 16px 0 0; display: grid; gap: 8px; }
.job { display: block; width: 100%; text-align: left; padding: 14px; min-height: 48px;
       background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
       text-decoration: none; color: var(--ink); cursor: pointer; }
.job b { display: block; }
.lbl { display: block; margin: 20px 0 6px; font-weight: 600; }
textarea { width: 100%; font: inherit; padding: 10px 12px; border: 1px solid var(--line);
           border-radius: 6px; background: var(--surface); color: var(--ink); }
.bottom { margin-top: auto; padding-top: 16px; }
.note { text-align: center; margin-bottom: 8px; }
.err { color: var(--crit); margin-top: 14px; }
</style>
