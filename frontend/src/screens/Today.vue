<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid, getMeta, setMeta } from '../db'
import { pull, drain, pendingCount } from '../sync/outbox'

const router = useRouter()
const boot = ref(null)
const error = ref('')
const stale = ref(false)
const queued = ref(0)
const syncing = ref(false)
const online = ref(navigator.onLine)
window.addEventListener('online', () => (online.value = true))
window.addEventListener('offline', () => (online.value = false))

function isOffline(e) {
  return e instanceof ApiError && e.code === 'OFFLINE'
}

function isAuth(e) {
  return e instanceof ApiError && ['AUTH_REQUIRED', 'LOGIN_FAILED'].includes(e.code)
}

/** Show the last known profile rather than an empty screen. */
async function showCached() {
  const cached = await getMeta('profile')
  if (cached) {
    boot.value = cached
    stale.value = true
    return true
  }
  return false
}

async function load() {
  try {
    // Cache the raw response. boot.value would hand back a reactive Proxy, which
    // IndexedDB cannot structured-clone.
    const profile = await api.bootstrap()
    await setMeta('profile', profile)
    boot.value = profile
    stale.value = false

    // Registration is idempotent; a returning session may hold a device id the server
    // has never seen, which used to fail with DEVICE_UNKNOWN.
    await api.registerDevice(await deviceUuid(), {
      platform: 'Web',
      app_version: '0.0.1',
      device_name: navigator.userAgent.slice(0, 60),
    })
    await pull()
  } catch (e) {
    if (isAuth(e)) return router.replace('/login')
    // Being offline is the expected state for this app, not a failure worth shouting about.
    // The strip at the top already says so.
    if (isOffline(e) || !navigator.onLine) await showCached()
    else error.value = e.message
  }
  queued.value = await pendingCount()
}

async function syncNow() {
  error.value = ''
  if (!navigator.onLine) {
    error.value = 'Still offline. Everything you captured is saved and will sync on its own.'
    return
  }
  syncing.value = true
  try {
    await drain()
    await load()
  } catch (e) {
    if (isAuth(e)) return router.replace('/login')
    if (!isOffline(e)) error.value = e.message
  }
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
      <p v-if="stale" class="muted">Showing your last saved details. Reconnect to refresh.</p>
      <template v-else>
        <p class="muted tnum">Server {{ boot.server_time }}</p>
        <p class="muted">API v{{ boot.api_version }}</p>
      </template>
    </div>
    <div v-else class="card muted">
      {{ online ? 'Loading your day…' : 'Offline. Sign in once online to get started.' }}
    </div>

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
