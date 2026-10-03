import { db, deviceUuid, getMeta, setMeta } from '../db'
import { api, ApiError } from '../api/client'
import { tryPosition } from '../lib/geo'

// Defaults; overridden by whatever bootstrap returned from FieldMate Settings.
let PING_SECONDS = 90
let UPLOAD_EVERY = 10 * 60 * 1000

// Never two uploads inside this window, whoever asks for one. Check-in, check-out and the
// app coming back to the foreground all land within seconds of each other, and each upload
// is a radio wake-up - which is the expensive part, not the fixes.
const MIN_GAP = 60 * 1000

let pingTimer = null
let uploadTimer = null
let lastFlushAt = 0

export function configure(settings = {}) {
  if (settings.gps_ping_interval_seconds) PING_SECONDS = settings.gps_ping_interval_seconds
}

/** Record one fix. Cheap, silent, and never interrupts what the rep is doing. */
async function collect() {
  const pos = await tryPosition()
  if (!pos) return false
  await db.pings.add({
    t: new Date().toISOString().slice(0, 19).replace('T', ' '),
    lat: pos.latitude,
    lon: pos.longitude,
    acc: pos.accuracy_m,
    mock: pos.is_mock_location ? 1 : 0,
    sent: 0,
  })
  return true
}

/** Send what has accumulated.
 *
 * Batched rather than sent per fix: a radio wake-up every 90 seconds costs far more battery
 * than the fixes themselves, and the budget is under 20% over a nine hour day.
 */
export async function flush() {
  lastFlushAt = Date.now()
  if (!navigator.onLine) return { skipped: 'offline' }

  const pending = await db.pings.where('sent').equals(0).toArray()
  if (!pending.length) return { sent: 0 }

  try {
    const device = await deviceUuid()
    const result = await api.uploadPings(device, pending.map(({ t, lat, lon, acc, mock }) => ({
      t, lat, lon, acc, mock: !!mock,
    })))
    // Delete rather than mark: the server now holds them, and the phone has no reason to.
    await db.pings.bulkDelete(pending.map((p) => p.id))
    await setMeta('lastPingUploadAt', Date.now())
    return { sent: pending.length, ...result }
  } catch (e) {
    // Keep them. An offline morning uploads in one go when signal returns.
    if (e instanceof ApiError && ['OFFLINE', 'AUTH_REQUIRED'].includes(e.code)) {
      return { sent: 0, kept: pending.length }
    }
    return { sent: 0, error: e.message }
  }
}

/** Flush unless one just went out.
 *
 * This is what the moments that matter call - the day starting, a check-in, a check-out,
 * signal coming back, the app returning to the foreground. Without it the trail first
 * appeared on the desk ten minutes after the rep had walked into the shop, which read as
 * the device not pinging at all.
 */
export async function flushSoon({ force = false } = {}) {
  if (!force && Date.now() - lastFlushAt < MIN_GAP) return { skipped: 'too soon' }
  return flush()
}

export async function pendingPings() {
  return db.pings.where('sent').equals(0).count()
}

// Signal returning and the app being reopened are both moments where the desk is most
// likely to be looking and the phone is most likely to be holding a backlog.
function onWake() {
  if (document.visibilityState === 'hidden') return
  flushSoon().catch(() => {})
}

export function start() {
  stop()
  // The first fix goes up on its own rather than waiting out the batch window. One small
  // request at the start of a day, or when the app is reopened, against a budget measured
  // over nine hours.
  collect().then((got) => {
    if (got) flushSoon({ force: true }).catch(() => {})
  }).catch(() => {})
  pingTimer = setInterval(collect, PING_SECONDS * 1000)
  uploadTimer = setInterval(flush, UPLOAD_EVERY)
  window.addEventListener('online', onWake)
  document.addEventListener('visibilitychange', onWake)
}

export function stop() {
  clearInterval(pingTimer)
  clearInterval(uploadTimer)
  pingTimer = uploadTimer = null
  window.removeEventListener('online', onWake)
  document.removeEventListener('visibilitychange', onWake)
}

export function isRunning() {
  return pingTimer !== null
}

/** Resume pinging after a reload if a day is still open. */
export async function resumeIfDayOpen() {
  const open = await getMeta('openDay')
  if (open) start()
}
