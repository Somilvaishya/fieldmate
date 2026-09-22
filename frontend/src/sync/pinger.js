import { db, deviceUuid, getMeta, setMeta } from '../db'
import { api, ApiError } from '../api/client'
import { tryPosition } from '../lib/geo'

// Defaults; overridden by whatever bootstrap returned from FieldMate Settings.
let PING_SECONDS = 90
let UPLOAD_EVERY = 10 * 60 * 1000

let pingTimer = null
let uploadTimer = null

export function configure(settings = {}) {
  if (settings.gps_ping_interval_seconds) PING_SECONDS = settings.gps_ping_interval_seconds
}

/** Record one fix. Cheap, silent, and never interrupts what the rep is doing. */
async function collect() {
  const pos = await tryPosition()
  if (!pos) return
  await db.pings.add({
    t: new Date().toISOString().slice(0, 19).replace('T', ' '),
    lat: pos.latitude,
    lon: pos.longitude,
    acc: pos.accuracy_m,
    mock: pos.is_mock_location ? 1 : 0,
    sent: 0,
  })
}

/** Send what has accumulated.
 *
 * Batched rather than sent per fix: a radio wake-up every 90 seconds costs far more battery
 * than the fixes themselves, and the budget is under 20% over a nine hour day.
 */
export async function flush() {
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

export async function pendingPings() {
  return db.pings.where('sent').equals(0).count()
}

export function start() {
  stop()
  collect()
  pingTimer = setInterval(collect, PING_SECONDS * 1000)
  uploadTimer = setInterval(flush, UPLOAD_EVERY)
}

export function stop() {
  clearInterval(pingTimer)
  clearInterval(uploadTimer)
  pingTimer = uploadTimer = null
}

export function isRunning() {
  return pingTimer !== null
}

/** Resume pinging after a reload if a day is still open. */
export async function resumeIfDayOpen() {
  const open = await getMeta('openDay')
  if (open) start()
}
