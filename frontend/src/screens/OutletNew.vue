<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { getMeta } from '../db'
import { enqueue } from '../sync/outbox'

const router = useRouter()
const form = ref({ outlet_name: '', mobile_no: '', city: '', owner_name: '' })
const coords = ref(null)
const busy = ref(false)
const error = ref('')
const queued = ref(false)

function locate() {
  if (!navigator.geolocation) return
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      coords.value = {
        latitude: +pos.coords.latitude.toFixed(6),
        longitude: +pos.coords.longitude.toFixed(6),
        geo_accuracy_m: Math.round(pos.coords.accuracy),
      }
    },
    () => { error.value = 'Could not read GPS. You can still save and fix the pin later.' },
    { enableHighAccuracy: true, timeout: 10000 }
  )
}

async function save() {
  error.value = ''
  if (!form.value.outlet_name.trim()) return (error.value = 'Enter the shop name.')
  if (!form.value.mobile_no.trim()) return (error.value = 'Enter a mobile number.')

  busy.value = true
  const profile = (await getMeta('profile')) || {}
  const fu = profile.field_user || {}
  const payload = {
    ...form.value,
    ...(coords.value || {}),
    territory: fu.territory,
    distributor: fu.distributor,
  }

  try {
    await api.createOutlet(payload)
    router.push('/outlets')
  } catch (e) {
    if (e instanceof ApiError && e.code === 'OFFLINE') {
      // Never lose what a rep captured standing in the shop.
      await enqueue('FieldMate Outlet', payload)
      queued.value = true
    } else {
      error.value = e.message
    }
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap">
    <RouterLink to="/outlets" class="back">← Outlets</RouterLink>
    <h2>Add a shop</h2>

    <div v-if="queued" class="card">
      <b>Saved on this phone.</b>
      <p class="muted">It will sync by itself once you have signal. A manager approves it
        before you can book an order.</p>
      <RouterLink to="/outlets" class="btn-primary">Done</RouterLink>
    </div>

    <form v-else @submit.prevent="save">
      <label for="n">Shop name</label>
      <input id="n" v-model="form.outlet_name" />
      <label for="m">Mobile</label>
      <input id="m" v-model="form.mobile_no" inputmode="numeric" />
      <label for="o">Owner</label>
      <input id="o" v-model="form.owner_name" />
      <label for="c">City</label>
      <input id="c" v-model="form.city" />

      <button type="button" class="ghost" @click="locate">
        {{ coords ? `Pin saved · ±${coords.geo_accuracy_m} m` : 'Capture GPS pin' }}
      </button>

      <p v-if="error" class="err">{{ error }}</p>
      <button class="btn-primary" :disabled="busy">{{ busy ? 'Saving…' : 'Save shop' }}</button>
      <p class="muted">A manager approves new shops before orders can be booked.</p>
    </form>
  </div>
</template>

<style scoped>
.back { display: inline-block; padding: 12px 0; color: var(--primary); text-decoration: none; }
label { display: block; margin: 14px 0 6px; font-weight: 600; }
.ghost { width: 100%; margin-top: 16px; background: transparent; color: var(--primary);
         border: 1px solid var(--primary); }
.btn-primary { margin-top: 16px; display: block; text-align: center; text-decoration: none; }
.err { color: var(--crit); margin-top: 12px; }
.muted { color: var(--muted); font-size: 14px; margin-top: 12px; }
.card { background: var(--surface); border: 1px solid var(--ok); border-radius: 6px; padding: 16px; }
</style>
