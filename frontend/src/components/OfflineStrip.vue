<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
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

const tone = computed(() => (stuck.value ? 'stuck' : online.value ? 'on' : 'off'))

// A dot on its own when everything is fine, and words only when there is something to say.
// The full-width bar this used to be took a line off every screen to repeat "Online" all day,
// which is the state the rep is in almost always and the one they least need telling about.
const message = computed(() => {
  if (stuck.value) return `${stuck.value} need${stuck.value === 1 ? 's' : ''} attention`
  if (syncing.value && queued.value) return `Sending ${queued.value}…`
  if (queued.value) return online.value
    ? `${queued.value} waiting`
    : `Offline · ${queued.value} saved`
  return online.value ? '' : 'Offline · all work saved'
})

const label = computed(() =>
  stuck.value ? `${stuck.value} records need attention`
    : online.value ? 'Online' : 'Offline, work is saved on this phone')
</script>

<template>
  <!-- Always present, always honest about queue depth. Never a spinner that could hang for
       ever - every write commits locally first and says so. -->
  <div class="lane" :class="[tone, message ? 'loud' : 'quiet']"
       role="status" :aria-label="label">
    <div class="inner">
      <span class="dot" aria-hidden="true"></span>
      <span v-if="message" class="text tnum">{{ message }}</span>
    </div>
  </div>
</template>

<style scoped>
/* A lane in the shell's column, not a badge floating over the screen.
 *
 * Floating it meant every screen had to leave a hole in its own padding for it, and the one
 * that forgot got a status pill sitting on top of its heading - which is exactly what
 * happened. In the flow it cannot overlap anything, whatever a screen does above it.
 *
 * Quiet it is one dot on a 20px lane: less than half a line of text, and the cheapest
 * honest way to say "online". Loud it fills out into a tinted band across the width,
 * because something a rep has to act on has earned the room.
 */
.lane { flex: none; padding: calc(env(safe-area-inset-top, 0px) + 5px) 0 5px; }
.lane.loud { padding-top: calc(env(safe-area-inset-top, 0px) + 7px); padding-bottom: 7px; }

/* Same 560px column and 16px gutter as `.wrap`, so the dot sits on the same left edge as
   every heading below it rather than at an arbitrary offset. */
.inner { max-width: 560px; margin: 0 auto; padding: 0 16px; min-height: 10px;
         display: flex; align-items: center; gap: 8px;
         font-size: 13px; font-weight: 600; line-height: 1.2; }

.dot { width: 9px; height: 9px; border-radius: 50%; background: currentColor; flex: none; }
.text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.on { color: var(--ok); }
.off { color: var(--warn); }
.stuck { color: var(--crit); }
/* The tint only when there are words to carry. A green band all day is the thing this
   replaced. */
.loud.off { background: var(--warn-soft); }
.loud.stuck { background: var(--crit-soft); }
.loud.on { background: var(--ok-soft); }
</style>
