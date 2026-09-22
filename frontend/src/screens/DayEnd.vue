<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { getPosition } from '../lib/geo'
import * as dayStore from '../stores/day'
import { pendingPings } from '../sync/pinger'

const router = useRouter()
const odometer = ref('')
const remarks = ref('')
const busy = ref(false)
const error = ref('')
const summary = ref(null)
const queued = ref(0)

pendingPings().then((n) => (queued.value = n))

async function finish() {
  error.value = ''
  busy.value = true
  try {
    let fix = {}
    try {
      fix = await getPosition({ timeout: 8000 })
    } catch {
      // Ending without a fix is fine. Refusing to close the day over GPS would strand a rep.
    }
    summary.value = await dayStore.end({
      ...fix,
      odometer_end: odometer.value ? Number(odometer.value) : null,
      remarks: remarks.value || null,
    })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not finish your day. Try again.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap screen">
    <div v-if="summary" class="top">
      <h2>Day finished</h2>
      <div class="card">
        <div class="kv"><span>Hours worked</span><b class="tnum">{{ summary.duration_hours }}</b></div>
        <div class="kv"><span>Distance</span><b class="tnum">{{ summary.distance_km }} km</b></div>
        <div class="kv"><span>Visits</span><b class="tnum">{{ summary.actual_visits }} of {{ summary.planned_visits }}</b></div>
        <div class="kv"><span>Orders</span><b class="tnum">{{ summary.orders_count }}</b></div>
        <div class="kv"><span>New shops</span><b class="tnum">{{ summary.new_outlets }}</b></div>
      </div>
      <p class="muted">Distance comes from your location trail, not the odometer.</p>
      <RouterLink to="/today" class="btn-primary">Done</RouterLink>
    </div>

    <template v-else>
      <div class="top">
        <h2>Finish your day</h2>
        <p class="muted">This closes the day. You cannot restart it afterwards.</p>
        <p v-if="queued" class="muted">{{ queued }} location points will upload first.</p>

        <label for="odo-end">Odometer <span class="muted">(optional)</span></label>
        <input id="odo-end" v-model="odometer" inputmode="numeric" placeholder="e.g. 45198" />

        <label for="rem">Anything worth noting?</label>
        <input id="rem" v-model="remarks" placeholder="Optional" />

        <p v-if="error" class="err">{{ error }}</p>
      </div>
      <div class="bottom">
        <button class="btn-primary" :disabled="busy" @click="finish">
          {{ busy ? 'Finishing…' : 'Finish day' }}
        </button>
        <RouterLink to="/today" class="cancel">Not yet</RouterLink>
      </div>
    </template>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; }
.bottom { padding-top: 16px; }
h2 { margin: 8px 0 4px; }
.muted { color: var(--muted); font-size: 14px; }
label { display: block; margin: 18px 0 6px; font-weight: 600; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
        padding: 12px; margin: 14px 0; }
.kv { display: flex; justify-content: space-between; padding: 6px 0; gap: 12px; }
.kv span { color: var(--muted); }
.err { color: var(--crit); margin-top: 14px; }
.btn-primary { display: block; text-align: center; text-decoration: none; margin-top: 16px; }
.cancel { display: block; text-align: center; padding: 14px; color: var(--muted);
          text-decoration: none; min-height: 48px; }
</style>
