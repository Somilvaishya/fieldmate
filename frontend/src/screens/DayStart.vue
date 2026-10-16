<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { getPosition } from '../lib/geo'
import { compress } from '../lib/image'
import { getMeta } from '../db'
import * as dayStore from '../stores/day'
import { t } from '../lib/i18n'
import Icon from '../components/Icon.vue'

const router = useRouter()
const fix = ref(null)
const selfie = ref(null)
const selfieKb = ref(0)
const selfieAt = ref(null)
const odometer = ref('')
const busy = ref(false)
const locating = ref(false)
const error = ref('')
const requireSelfie = ref(true)

const planned = dayStore.plannedToday

const today = computed(() =>
  new Date().toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })
)

const duration = computed(() => {
  const mins = planned.value?.estimated_duration_min
  if (!mins) return null
  const h = Math.floor(mins / 60)
  return h ? `${h}h ${mins % 60}m` : `${mins}m`
})

const ready = computed(() => !!fix.value && (!requireSelfie.value || !!selfie.value))

onMounted(async () => {
  const settings = (await getMeta('profile'))?.settings || {}
  // The server sends a JSON boolean, not 0/1. Comparing against 0 made this always true -
  // `false !== 0` - so a site that switched the selfie off still forced one, and told the
  // rep it was required while the server would have accepted the day without it.
  requireSelfie.value = settings.require_day_start_selfie !== false
  await dayStore.refresh().catch(() => {})
  // Ask for the fix straight away. It is needed either way, and the permission prompt is
  // better answered while the rep is looking at the screen than after they tap Start.
  locate()
})

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
    selfieAt.value = new Date().toLocaleTimeString('en-IN',
      { hour: '2-digit', minute: '2-digit' })
  } catch {
    error.value = t('Could not read that photo. Try taking it again.')
  } finally {
    event.target.value = ''
  }
}

async function begin() {
  error.value = ''
  if (!fix.value) return (error.value = t('Capture your location first.'))
  if (requireSelfie.value && !selfie.value) {
    return (error.value = t('Take the start-of-day photo first.'))
  }
  busy.value = true
  try {
    await dayStore.start({
      ...fix.value,
      selfie: selfie.value,
      odometer_start: odometer.value ? Number(odometer.value) : null,
    })
    router.replace('/today')
  } catch (e) {
    error.value = e instanceof ApiError
      ? e.message
      : t('Could not start your day. Try again in a moment.')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap screen">
    <div class="top">
      <div class="head">
        <div>
          <span class="eyebrow">{{ t("Today's assignment") }}</span>
          <h2>{{ planned?.beat_name || planned?.beat || t('No route planned') }}</h2>
        </div>
        <span class="date tnum">{{ today }}</span>
      </div>

      <!-- Location. Not optional: a day that starts nowhere cannot be checked against
           anything the rep does afterwards. -->
      <button type="button" class="tile" :class="{ done: fix }" :disabled="locating"
              @click="locate">
        <span class="badge"><Icon :name="fix ? 'check' : 'pin'" size="22" /></span>
        <span class="tile-text">
          <b v-if="locating">{{ t('Getting a fix…') }}</b>
          <b v-else-if="fix" class="tnum">
            {{ t('Location captured · ±{m} m', { m: fix.accuracy_m }) }}
          </b>
          <b v-else>{{ t('Capture your location') }}</b>
          <span class="muted tnum" v-if="fix">
            {{ fix.latitude }}, {{ fix.longitude }} · {{ fix.location_provider }}
          </span>
          <span class="muted" v-else-if="!locating">{{ t('Tap to try again') }}</span>
        </span>
        <Icon v-if="fix" name="refresh" size="20" class="go" />
      </button>

      <label class="tile" :class="{ done: selfie }">
        <span class="badge"><Icon :name="selfie ? 'check' : 'camera'" size="22" /></span>
        <span class="tile-text">
          <b v-if="selfie" class="tnum">
            {{ t('Photo taken · {kb} KB', { kb: selfieKb }) }}
          </b>
          <b v-else>{{ t('Take the start-of-day photo') }}</b>
          <span class="muted tnum" v-if="selfie">
            {{ t('Taken at {at} · tap to retake', { at: selfieAt }) }}
          </span>
          <span class="muted" v-else>{{ requireSelfie ? t('Required') : t('Optional') }}</span>
        </span>
        <input type="file" accept="image/*" capture="user" hidden @change="onSelfie" />
      </label>

      <div class="card">
        <label class="lbl" for="odo">
          {{ t('Odometer reading') }} <span class="muted">{{ t('(optional)') }}</span>
        </label>
        <div class="odo">
          <input id="odo" v-model="odometer" inputmode="numeric" class="tnum"
                 :placeholder="t('e.g. 14250')" />
          <span class="unit">km</span>
        </div>
        <p class="muted hint">{{ t('Recorded with your day.') }}</p>
      </div>

      <!-- What the day asks of them, before they commit to it. Only what the route
           actually records - a made-up estimate is worse than none. -->
      <div class="card" v-if="planned?.beat">
        <div class="row">
          <b>{{ t("Today's route") }}</b>
          <span class="pill tnum" v-if="planned.outlet_count">
            {{ planned.outlet_count }} shops
          </span>
        </div>
        <div class="facts">
          <div class="fact" v-if="planned.outlet_count">
            <Icon name="store" size="20" />
            <span>
              <span class="muted">{{ t('Shops planned') }}</span>
              <b class="tnum">{{ planned.outlet_count }}</b>
            </span>
          </div>
          <div class="fact" v-if="planned.estimated_travel_km">
            <Icon name="directions" size="20" />
            <span>
              <span class="muted">{{ t('Route distance') }}</span>
              <b class="tnum">about {{ planned.estimated_travel_km }} km</b>
            </span>
          </div>
          <div class="fact" v-if="duration">
            <Icon name="refresh" size="20" />
            <span>
              <span class="muted">{{ t('Expected time') }}</span>
              <b class="tnum">about {{ duration }}</b>
            </span>
          </div>
        </div>
      </div>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>
    </div>

    <div class="bottom">
      <button class="btn-primary" :disabled="busy || !ready" @click="begin">
        {{ busy ? t('Starting…') : t('Start day') }}
      </button>
      <p class="muted foot" v-if="!ready && !busy">
        {{ !fix ? t('Capture your location to continue.') : t('Take the photo to continue.') }}
      </p>
      <p class="muted foot" v-else>
        {{ t('Your location is recorded through the day and stops when you finish.') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: grid; gap: 12px; align-content: start; }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px;
        margin: 8px 0 4px; }
.eyebrow { display: block; font-size: 14px; font-weight: 700; letter-spacing: 0.05em;
           text-transform: uppercase; color: var(--muted); }
h2 { margin: 2px 0 0; font-size: 20px; overflow-wrap: anywhere; }
.date { flex: none; font-size: 14px; font-weight: 600; color: var(--primary);
        background: var(--primary-soft); border-radius: 4px; padding: 6px 10px; }
.muted { color: var(--muted); font-size: 14px; font-weight: 400; }

.tile { display: flex; align-items: center; gap: 12px; width: 100%; text-align: left;
        padding: 12px; min-height: 72px; background: var(--surface);
        border: 1px solid var(--line); border-radius: 6px; cursor: pointer; }
.tile.done { border-color: var(--ok); background: var(--ok-soft); }
.tile-text { flex: 1; display: grid; gap: 2px; min-width: 0; }
.tile-text b { overflow-wrap: anywhere; }
.badge { width: 44px; height: 44px; flex: none; display: grid; place-items: center;
         border-radius: 6px; background: var(--primary-soft); color: var(--primary); }
.tile.done .badge { background: var(--ok); color: var(--surface); }
.go { color: var(--muted); flex: none; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; }
.lbl { display: block; font-weight: 600; font-size: 16px; margin-bottom: 6px; }
.odo { position: relative; display: flex; align-items: center; }
.odo input { padding-right: 52px; }
.unit { position: absolute; right: 14px; font-weight: 700; color: var(--muted);
        pointer-events: none; }
.hint { margin: 6px 0 0; }

.row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.pill { flex: none; font-size: 14px; font-weight: 600; padding: 3px 8px; border-radius: 4px;
        background: var(--primary-soft); color: var(--primary); }
.facts { display: grid; gap: 10px; margin-top: 12px; padding-top: 12px;
         border-top: 1px solid var(--line); }
.fact { display: flex; align-items: center; gap: 10px; color: var(--muted); }
.fact > span { display: grid; gap: 1px; min-width: 0; }
.fact b { color: var(--ink); }

.err { display: flex; align-items: flex-start; gap: 8px; margin: 0; font-size: 14px;
       background: var(--crit-soft); color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.bottom { position: sticky; bottom: 0; padding: 12px 0 4px; margin-top: 16px;
          background: var(--bg); border-top: 1px solid var(--line); }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               padding: 14px; min-height: 52px; border-radius: 6px; }
.btn-primary:disabled { opacity: 0.55; }
.foot { text-align: center; margin: 8px 0 0; }
</style>
