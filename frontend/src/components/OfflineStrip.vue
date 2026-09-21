<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { pendingCount } from '../sync/outbox'

const online = ref(navigator.onLine)
const queued = ref(0)
let timer = null

async function refresh() { queued.value = await pendingCount() }
function setOnline() { online.value = true }
function setOffline() { online.value = false }

onMounted(() => {
  window.addEventListener('online', setOnline)
  window.addEventListener('offline', setOffline)
  refresh()
  timer = setInterval(refresh, 4000)
})
onUnmounted(() => {
  window.removeEventListener('online', setOnline)
  window.removeEventListener('offline', setOffline)
  clearInterval(timer)
})
</script>

<template>
  <!-- Always present, always honest about queue depth. Never a spinner that could
       hang forever - every write commits locally first and says so. -->
  <div class="strip" :class="online ? 'on' : 'off'">
    <span v-if="online && !queued">Online</span>
    <span v-else-if="online">Syncing &middot; <b class="tnum">{{ queued }}</b> waiting</span>
    <span v-else-if="queued">Offline &middot; <b class="tnum">{{ queued }}</b> saved on this phone</span>
    <span v-else>Offline &middot; all work saved</span>
  </div>
</template>

<style scoped>
.strip { padding: 6px 16px; font-size: 14px; text-align: center; border-bottom: 1px solid var(--line); }
.on  { background: #e6f4ee; color: var(--ok); }
.off { background: #f7eedd; color: var(--warn); }
</style>
