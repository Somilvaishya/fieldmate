<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { getPosition } from '../lib/geo'
import { compress } from '../lib/image'
import { getMeta } from '../db'
import * as outletStore from '../stores/outlets'
import * as dayStore from '../stores/day'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

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

/**
 * A photo at the counter, where the site has asked for one.
 *
 * **Off unless somebody switched it on.** It is one more thing to do at sixty shops a day and the
 * geo-fence already records where the rep stood, so this is for a territory genuinely in doubt
 * rather than for every site. The visit has carried the field and its storage since Phase 3;
 * nothing ever asked the rep for the photo, so nothing ever sent one.
 *
 * `!== false`, not a truthy test. The server sends a JSON boolean and the day-start screen was
 * once comparing one against 0 - `false !== 0` - so a site that had switched its selfie off still
 * demanded one. Same shape, same trap.
 */
const photo = ref(null)
const photoKb = ref(0)
const requirePhoto = ref(false)

// Checked before the rep touches anything, not after they tap. The old screen let them take a
// fix, type a note and press a live button that silently refused - the one reading of a dead
// control is that the app is broken.
//
// `dayKnown` is the other half, and it was missing. This screen read `openDay` without ever
// asking for it, so a rep arriving from Beats - where nothing loads the day - was told their
// day had not started when it had. Now it says nothing until it knows.
const dayKnown = computed(() => dayStore.loaded.value)
const dayOpen = computed(() => !!dayStore.openDay.value)

/**
 * The shop the rep has not checked out of, if it is not this one.
 *
 * Checked up here with the day rather than on the tap, for the reason above: a live button that
 * refuses reads as a broken app. Checking out is how a visit ends, so this screen leads with the
 * way back to that shop and keeps checking in here behind a second, deliberate tap.
 */
const openElsewhere = computed(() => {
  const open = visitStore.activeVisit.value
  if (!open) return null
  return open.outlet === route.params.name ? null : open
})

// Two taps, never one. Closing the other visit stamps it "No Order" and short, and a visit
// ended that way is one the rep cannot go back and fill in.
const closing = ref(false)

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
  const settings = (await getMeta('profile'))?.settings || {}
  requirePhoto.value = settings.require_visit_selfie === true
  // Ask for the day as well as the shop. Locating takes a second or two anyway, so this costs
  // the rep nothing and removes the window in which the screen could be confidently wrong.
  dayStore.ensure().catch(() => {})
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

function backToOpenVisit() {
  router.replace({ name: 'visit', params: { uuid: openElsewhere.value.clientUuid } })
}

async function onPhoto(event) {
  const file = event.target.files?.[0]
  if (!file) return
  error.value = ''
  try {
    const settings = (await getMeta('profile'))?.settings || {}
    const out = await compress(file, {
      maxKb: settings.photo_max_kb || 120,
      maxPx: settings.photo_max_dimension_px || 1280,
    })
    photo.value = out.dataUrl
    photoKb.value = out.kb
  } catch {
    error.value = 'Could not read that photo. Try taking it again.'
  } finally {
    event.target.value = ''
  }
}

async function begin({ closeOpen = false } = {}) {
  error.value = ''
  if (!dayOpen.value) return router.push('/day/start')
  if (requirePhoto.value && !photo.value) {
    error.value = 'Take the photo at the shop before you check in.'
    return
  }
  if (openElsewhere.value && !closeOpen) return backToOpenVisit()
  busy.value = true
  try {
    const visit = await visitStore.checkIn(outlet.value, {
      fix: fix.value || {},
      deviationNote: note.value || null,
      checkInPhoto: photo.value || null,
      closeOpen,
    })
    router.replace({ name: 'visit', params: { uuid: visit.clientUuid } })
  } catch (e) {
    // The server refuses this one too, and says which shop. Its sentence is better than ours
    // because it read the shop master; ours is what shows when there was no signal to ask.
    if (e instanceof visitStore.OpenVisitError || e?.code === 'VISIT_OPEN_ELSEWHERE') {
      error.value = e.message
      closing.value = true
    } else {
      error.value = e instanceof ApiError ? e.message : 'Could not check in. Try again.'
    }
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
        <b>{{ locating ? t('Getting a fix…') : fix ? t('Location captured') : t('Capture location') }}</b>
        <span v-if="fix" class="muted tnum">±{{ fix.accuracy_m }} m</span>
        <span v-else-if="!locating" class="muted">{{ t(t('Tap to try again')) }}</span>
      </button>

      <!-- Only where the site asked for it. Drawn at all is the signal that it is wanted; a tile
           offering an optional photo at sixty counters a day is sixty chances to be slowed down
           by something nobody reads. -->
      <label v-if="requirePhoto" class="tile photo" :class="{ done: photo }">
        <b v-if="photo" class="tnum">Photo taken · {{ photoKb }} KB</b>
        <b v-else>{{ t(t('Take the photo at this shop')) }}</b>
        <span class="muted">{{ photo ? t('Tap to retake') : t('Required here') }}</span>
        <input type="file" accept="image/*" capture="environment" hidden @change="onPhoto" />
      </label>

      <!-- Being far away is recorded, never refused. This card has to read as a fact being
           logged, not a door being closed - a rep who reads it as a rejection stops checking
           in at all, and then there is no coverage data to act on. -->
      <div v-if="outsideFence" class="dist far">
        <b class="tnum">You are {{ distance }} m from this shop, outside its
          {{ fenceRadius }} m range.</b>
        <p>{{ t(t('You can still check in. Your manager will see the distance saved with this visit.')) }}</p>
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
        {{ outsideFence ? t('Reason for the distance') : t('Note') }}
        <span class="muted">{{ t(t('(optional)')) }}</span>
      </label>
      <input id="note" v-model="note"
             :placeholder="outsideFence
               ? t('e.g. shop has moved, met the owner elsewhere')
               : t('Why this shop, if it is off your route')" />
      <!-- Typed one-handed at a doorstep, so the common answers are one tap. -->
      <div class="chips" v-if="outsideFence">
        <button v-for="r in REASONS" :key="r" type="button" class="chip" @click="note = r">
          + {{ r }}
        </button>
      </div>

      <!-- Only once the day is actually known. Saying "not started" while still finding out
           is the same mistake as saying it when it has. -->
      <p v-if="dayKnown && !dayOpen" class="notice">
        <Icon name="alert" />
        <span>{{ t(t('Your day has not started yet. Start it and this shop will be waiting.')) }}</span>
      </p>
      <!-- The shop behind them. Named before they touch anything, with the way back to it. -->
      <p v-if="openElsewhere" class="notice">
        <Icon name="alert" />
        <span>
          You are still checked in at <b>{{ openElsewhere.outletName }}</b>. Check out from
          there first - a visit ends by checking out.
        </span>
      </p>
      <p v-if="error" class="err">{{ error }}</p>
    </div>

    <div class="bottom">
      <button v-if="openElsewhere" class="btn-primary" @click="backToOpenVisit">
        Back to {{ openElsewhere.outletName }}
      </button>
      <button v-else class="btn-primary" :disabled="busy || !dayKnown" @click="begin()">
        {{ busy ? t('Checking in…')
           : !dayKnown ? t('One moment…')
           : !dayOpen ? t('Start my day')
           : outsideFence ? t('Check in with the distance logged')
           : t('Check in') }}
      </button>

      <!-- The way out for a rep who has genuinely walked away from that shop and cannot go
           back. Offered, spelled out, and never the first thing their thumb finds. -->
      <template v-if="openElsewhere">
        <button v-if="!closing" class="btn-plain" @click="closing = true">
          I have left {{ openElsewhere.outletName }}
        </button>
        <template v-else>
          <p class="muted">
            That visit will be closed where it stands and counted as a short visit - as
            <b>{{ t(t('No Order')) }}</b> unless an order was already booked in it. You cannot go back and
            fill it in.
          </p>
          <button class="btn-plain" :disabled="busy" @click="begin({ closeOpen: true })">
            {{ busy ? t('Checking in…') : t('Close it and check in here') }}
          </button>
        </template>
      </template>

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
/* A label, not a button, because it wraps the file input. Same furniture either way, and the
   48px floor every control on this screen holds. */
.photo { cursor: pointer; min-height: 48px; }
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
