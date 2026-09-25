import { drain, pendingCount } from './outbox'
import * as photoQueue from './photos'

// Queued work has to leave the phone on its own.
//
// Until this existed, `drain()` had exactly one caller - the "Sync now" button on Today -
// so a rep who captured a morning offline and never tapped it kept the whole day on the
// handset, while the status strip said "Syncing". The strip was not wrong about the queue;
// it was wrong that anything was working on it.
//
// Records go first and photos follow, for the same reason as everywhere else: a day of
// coverage must not wait behind one shelf photo crawling up a 2G uplink.

const IDLE_MS = 60_000

let timer = null
let running = false
let lastResult = { at: 0, sent: 0 }

/** Drain once, never overlapping with another drain. */
export async function syncNow({ appVersion = '0.0.1' } = {}) {
  if (running || !navigator.onLine) return { skipped: running ? 'busy' : 'offline' }
  running = true
  try {
    const records = await drain({ appVersion })
    const photos = await photoQueue.drain()
    lastResult = { at: Date.now(), sent: (records.sent || 0) + (photos.sent || 0) }
    return lastResult
  } catch {
    // A failed sweep is not an error a rep needs to see. The queue keeps its own retry
    // state and the strip keeps showing the depth.
    return { sent: 0 }
  } finally {
    running = false
  }
}

function onOnline() {
  // The single most valuable moment to try: the rep just walked back into coverage.
  syncNow()
}

export function start() {
  if (timer) return
  window.addEventListener('online', onOnline)
  timer = setInterval(() => {
    if (navigator.onLine) syncNow()
  }, IDLE_MS)
  syncNow()
}

export function stop() {
  if (!timer) return
  window.removeEventListener('online', onOnline)
  clearInterval(timer)
  timer = null
}

export function isRunning() {
  return running
}

export async function queueDepth() {
  return (await pendingCount()) + (await photoQueue.pendingCount())
}

export function lastSync() {
  return lastResult
}
