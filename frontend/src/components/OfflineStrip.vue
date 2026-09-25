<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { pendingCount, blockedCount } from '../sync/outbox'
import * as photoQueue from '../sync/photos'
import * as auto from '../sync/auto'

const online = ref(navigator.onLine)
const queued = ref(0)
const stuck = ref(0)
const syncing = ref(false)
let timer = null

async function refresh() {
  queued.value = (await pendingCount()) + (await photoQueue.pendingCount())
  stuck.value = await blockedCount()
  syncing.value = auto.isRunning()
}
function setOnline() { online.value = true }
function setOffline() { online.value = false }

onMounted(() => {
  window.addEventListener('online', setOnline)
  window.addEventListener('offline', setOffline)
  refresh()
  timer = setInterval(refresh, 3000)
})
onUnmounted(() => {
  window.removeEventListener('online', setOnline)
  window.removeEventListener('offline', setOffline)
  clearInterval(timer)
})
</script>

<template>
  <!-- Always present, always honest about queue depth. Never a spinner that could hang
       forever - every write commits locally first and says so.

       "Syncing" is claimed only while a drain is actually in flight. It used to appear
       whenever the app was online with anything queued, which was false for as long as
       nothing was draining the queue. -->
  <div class="strip" :class="stuck ? 'stuck' : online ? 'on' : 'off'">
    <span class="dot" aria-hidden="true"></span>
    <span v-if="stuck" class="tnum">
      <b>{{ stuck }}</b> {{ stuck === 1 ? 'record needs' : 'records need' }} attention
    </span>
    <span v-else-if="syncing" class="tnum">Sending <b>{{ queued }}</b>…</span>
    <span v-else-if="online && !queued">Online</span>
    <span v-else-if="online" class="tnum"><b>{{ queued }}</b> waiting to send</span>
    <span v-else-if="queued" class="tnum">Offline &middot; <b>{{ queued }}</b> saved on this phone</span>
    <span v-else>Offline &middot; all work saved</span>
  </div>
</template>

<style scoped>
/* Tokens, not literals. The two tints here were hand-picked before the palette was derived
   from the logo, and drifted out of the audited set. */
.strip { display: flex; align-items: center; justify-content: center; gap: 8px;
         padding: 6px 16px; font-size: 14px; border-bottom: 1px solid var(--line); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; flex: none; }
.on  { background: var(--ok-soft); color: var(--ok); }
.off { background: var(--warn-soft); color: var(--warn); }
.stuck { background: var(--crit-soft); color: var(--crit); }
</style>
