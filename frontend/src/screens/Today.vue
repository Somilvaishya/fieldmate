<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid } from '../db'
import { pull, drain, pendingCount } from '../sync/outbox'

const router = useRouter()
const boot = ref(null)
const error = ref('')
const queued = ref(0)
const syncing = ref(false)

function handle(e) {
  if (e instanceof ApiError && ['AUTH_REQUIRED', 'LOGIN_FAILED'].includes(e.code)) {
    router.replace('/login')
    return true
  }
  error.value = e.message
  return false
}

async function load() {
  try {
    boot.value = await api.bootstrap()
    // A returning session has a device id in IndexedDB that the server may not know about -
    // only login used to register it, so any later visit failed with DEVICE_UNKNOWN.
    // Registration is idempotent, so just do it every boot.
    await api.registerDevice(await deviceUuid(), {
      platform: 'Web',
      app_version: '0.0.1',
      device_name: navigator.userAgent.slice(0, 60),
    })
    await pull()
  } catch (e) {
    handle(e)
  }
  queued.value = await pendingCount()
}

async function syncNow() {
  syncing.value = true
  error.value = ''
  try {
    await drain()
    await pull()
  } catch (e) {
    handle(e)
  }
  queued.value = await pendingCount()
  syncing.value = false
}

onMounted(load)
</script>

<template>
  <div class="wrap">
    <h2>Today</h2>
    <p v-if="error" class="err">{{ error }}</p>

    <div v-if="boot" class="card">
      <p><b>{{ boot.full_name }}</b></p>
      <p class="muted">{{ (boot.roles || []).join(', ') || 'No FieldMate role' }}</p>
      <p class="muted tnum">Server {{ boot.server_time }}</p>
      <p class="muted">API v{{ boot.api_version }}</p>
    </div>
    <div v-else-if="!error" class="card muted">Loading your day…</div>

    <p class="muted">Phase 0 shell. Beat, visits and orders arrive in Phases 1–4.</p>
    <button class="btn-primary" :disabled="syncing" @click="syncNow">
      {{ syncing ? 'Syncing…' : `Sync now (${queued} queued)` }}
    </button>
  </div>
</template>

<style scoped>
h2 { margin: 8px 0 16px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 12px; margin-bottom: 16px; }
.card p { margin: 0 0 4px; }
.muted { color: var(--muted); font-size: 14px; }
.err { color: var(--crit); }
</style>
