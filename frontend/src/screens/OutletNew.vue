<script setup>
import { ref } from 'vue'
import { api, ApiError } from '../api/client'
import { getMeta, putRecord } from '../db'
import { enqueue } from '../sync/outbox'
import { getPosition } from '../lib/geo'
import { compress } from '../lib/image'
import Icon from '../components/Icon.vue'

// The real options on FieldMate Outlet.outlet_type. Chips rather than a select: a dropdown
// on a phone is two taps and a scroll, and this is answered at a doorstep.
const TYPES = ['Kirana', 'Grocery', 'Modern Trade', 'Chemist', 'HoReCa', 'Wholesale', 'Other']

const form = ref({
  outlet_name: '', mobile_no: '', owner_name: '', city: '', outlet_type: 'Kirana',
})
const coords = ref(null)
// On screen only. A loose fix is worth re-taking while the rep is still at the shop,
// and nothing afterwards reads the number - so it is deliberately kept out of `coords`,
// which is spread wholesale into the create payload below.
const accuracyM = ref(null)
const photo = ref(null)
const photoKb = ref(0)
const locating = ref(false)
const busy = ref(false)
const error = ref('')
const saved = ref(null)

async function locate() {
  error.value = ''
  locating.value = true
  try {
    const fix = await getPosition()
    coords.value = { latitude: fix.latitude, longitude: fix.longitude }
    accuracyM.value = fix.accuracy_m
  } catch (e) {
    error.value = e.message
  } finally {
    locating.value = false
  }
}

async function onPhoto(event) {
  const file = event.target.files?.[0]
  if (!file) return
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

async function save() {
  error.value = ''
  if (!form.value.outlet_name.trim()) return (error.value = 'Enter the shop name.')
  if (!/^\d{10}$/.test(form.value.mobile_no.trim())) {
    return (error.value = 'Enter the 10-digit mobile number.')
  }

  busy.value = true
  const profile = (await getMeta('profile')) || {}
  const fu = profile.field_user || {}
  const payload = {
    ...form.value,
    ...(coords.value || {}),
    shop_photo: photo.value || undefined,
    territory: fu.territory,
    distributor: fu.distributor,
    client_uuid: crypto.randomUUID(),
  }

  try {
    const result = await api.createOutlet(payload)
    saved.value = { name: result.name, offline: false }
    await putRecord('FieldMate Outlet', { ...payload, name: result.name })
  } catch (e) {
    // A validation error is the rep's to fix right now. Anything else - the network, the
    // server, an expired session - is queued rather than thrown away, which is what used
    // to happen to everything that was not a clean OFFLINE rejection.
    if (e instanceof ApiError && e.code === 'VALIDATION_FAILED') {
      error.value = e.message
    } else {
      // Never lose what a rep captured standing in the shop.
      await enqueue('FieldMate Outlet', payload, { clientUuid: payload.client_uuid })
      // Written to the mirror too, or the shop vanishes from the Shops list and cannot be
      // visited until a sync happens - which may be hours away.
      await putRecord('FieldMate Outlet', {
        ...payload,
        name: payload.client_uuid,
        approval_status: 'Pending Approval',
        outlet_status: 'Active',
        created_offline: 1,
      })
      saved.value = { name: null, offline: true }
    }
  } finally {
    busy.value = false
  }
}

function again() {
  form.value = { outlet_name: '', mobile_no: '', owner_name: '', city: '', outlet_type: 'Kirana' }
  coords.value = null
  accuracyM.value = null
  photo.value = null
  saved.value = null
}
</script>

<template>
  <div class="wrap screen">
    <RouterLink to="/outlets" class="back"><Icon name="back" size="20" /> Shops</RouterLink>
    <h2>Add a shop</h2>

    <form id="newshop" class="top" @submit.prevent="save">
      <!-- The pin first. It is the one thing that cannot be filled in later from an office. -->
      <div class="field">
        <label>Shop location</label>
        <button type="button" class="tile" :class="{ done: coords }" :disabled="locating"
                @click="locate">
          <span class="badge"><Icon name="pin" size="22" /></span>
          <span class="tile-text">
            <b v-if="locating">Getting a fix…</b>
            <b v-else-if="coords" class="tnum">Pin saved · ±{{ accuracyM }} m</b>
            <b v-else>Capture the shop's location</b>
            <span class="muted tnum" v-if="coords">
              {{ coords.latitude }}, {{ coords.longitude }} · tap to re-take
            </span>
            <span class="muted" v-else>Stand at the shopfront for the best pin</span>
          </span>
          <Icon v-if="coords" name="refresh" size="20" class="go" />
        </button>
      </div>

      <div class="field">
        <label for="n">Shop name <span class="req">*</span></label>
        <input id="n" v-model="form.outlet_name" placeholder="e.g. Laxmi General Store" />
      </div>

      <div class="field">
        <label for="m">Mobile number <span class="req">*</span></label>
        <div class="phone">
          <span class="prefix">+91</span>
          <input id="m" v-model="form.mobile_no" inputmode="numeric" maxlength="10"
                 placeholder="10-digit number" />
        </div>
      </div>

      <div class="field">
        <label for="o">Owner's name</label>
        <input id="o" v-model="form.owner_name" placeholder="e.g. Rajesh Patel" />
      </div>

      <div class="field">
        <label for="c">Area</label>
        <input id="c" v-model="form.city" placeholder="e.g. South Market, Sector 2" />
      </div>

      <div class="field">
        <label id="typelabel">Shop type</label>
        <div class="chips" role="radiogroup" aria-labelledby="typelabel">
          <button v-for="kind in TYPES" :key="kind" type="button" class="chip"
                  :class="{ on: form.outlet_type === kind }" role="radio"
                  :aria-checked="form.outlet_type === kind" @click="form.outlet_type = kind">
            {{ kind }}
          </button>
        </div>
      </div>

      <div class="field">
        <label>Shopfront photo <span class="muted">(optional)</span></label>
        <label class="tile" :class="{ done: photo }">
          <span class="badge"><Icon name="camera" size="22" /></span>
          <span class="tile-text">
            <b>{{ photo ? 'Photo taken' : 'Add a shopfront photo' }}</b>
            <span class="muted tnum" v-if="photo">{{ photoKb }} KB · tap to retake</span>
            <span class="muted" v-else>Helps your manager approve it faster</span>
          </span>
          <input type="file" accept="image/*" capture="environment" hidden @change="onPhoto" />
        </label>
      </div>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>
    </form>

    <div class="bottom">
      <button form="newshop" class="btn-primary" :disabled="busy">
        {{ busy ? 'Saving…' : 'Save shop' }}
      </button>
      <p class="muted foot">A manager approves new shops before orders can be booked.</p>
    </div>

    <!-- A sheet, not a centred modal: a modal in the middle of the screen is out of
         thumb reach on the phone this is used on. -->
    <div v-if="saved" class="scrim">
      <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="donetitle">
        <span class="grab" aria-hidden="true"></span>
        <span class="tick"><Icon name="check" size="30" /></span>
        <h3 id="donetitle">{{ form.outlet_name || 'Shop' }} added</h3>
        <p class="muted" v-if="saved.offline">
          Saved on this phone. It sends itself when you have signal.
        </p>
        <p class="muted" v-else>
          Sent. A manager approves it before you can book an order.
        </p>
        <button class="btn-primary" @click="again">Add another shop</button>
        <RouterLink to="/outlets" class="ghost">Back to shops</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: grid; gap: 16px; align-content: start; }
.back { display: inline-flex; align-items: center; gap: 4px; min-height: 48px;
        color: var(--primary); text-decoration: none; font-weight: 600; }
h2 { margin: 0 0 16px; }
.muted { color: var(--muted); font-size: 14px; font-weight: 400; }
.field { display: grid; gap: 6px; }
label { font-weight: 600; font-size: 16px; }
.req { color: var(--crit); }

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

.phone { display: flex; gap: 8px; }
.prefix { display: grid; place-items: center; min-width: 56px; min-height: 48px;
          border-radius: 6px; background: var(--primary-soft); color: var(--primary);
          font-weight: 700; }

.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { min-height: 48px; padding: 0 14px; border-radius: 6px; font-size: 16px;
        font-weight: 600; background: var(--surface); border: 1px solid var(--line);
        color: var(--ink); }
.chip.on { background: var(--primary); border-color: var(--primary); color: var(--on-primary); }

.err { display: flex; align-items: flex-start; gap: 8px; margin: 0; font-size: 14px;
       background: var(--crit-soft); color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.bottom { position: sticky; bottom: 0; padding: 12px 0 4px; margin-top: 16px;
          background: var(--bg); border-top: 1px solid var(--line); }
.foot { text-align: center; margin: 8px 0 0; }

.scrim { position: fixed; inset: 0; z-index: 30; display: flex; align-items: flex-end;
         background: rgba(5, 23, 46, 0.6); }
.sheet { width: 100%; background: var(--surface); border-top: 1px solid var(--line);
         border-radius: 16px 16px 0 0; padding: 12px 16px 24px; display: grid; gap: 10px;
         justify-items: center; text-align: center;
         padding-bottom: calc(24px + env(safe-area-inset-bottom, 0px)); }
.grab { width: 40px; height: 4px; border-radius: 2px; background: var(--line); }
.tick { width: 56px; height: 56px; display: grid; place-items: center; border-radius: 50%;
        background: var(--ok-soft); color: var(--ok); margin-top: 4px; }
.sheet h3 { margin: 0; font-size: 18px; overflow-wrap: anywhere; }
.sheet p { margin: 0; max-width: 280px; }
.sheet .btn-primary, .sheet .ghost { width: 100%; }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               text-decoration: none; padding: 14px; min-height: 52px; border-radius: 6px; }
.ghost { display: flex; align-items: center; justify-content: center; min-height: 48px;
         background: var(--surface); color: var(--primary); border: 1px solid var(--primary);
         border-radius: 6px; font-weight: 600; text-decoration: none; }
</style>
