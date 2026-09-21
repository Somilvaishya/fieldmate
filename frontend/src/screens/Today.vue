<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api/client'
import { pull, drain, pendingCount } from '../sync/outbox'

const boot = ref(null)
const error = ref('')
const queued = ref(0)

onMounted(async () => {
  try {
    boot.value = await api.bootstrap()
    await pull()
  } catch (e) {
    error.value = e.message
  }
  queued.value = await pendingCount()
})

async function syncNow() {
  await drain()
  await pull()
  queued.value = await pendingCount()
}
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
    <p class="muted">Phase 0 shell. Beat, visits and orders arrive in Phases 1–4.</p>
    <button class="btn-primary" @click="syncNow">Sync now ({{ queued }} queued)</button>
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
