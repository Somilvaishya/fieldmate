import { db, serverNameFor } from '../db'
import { api, ApiError } from '../api/client'

// Photos travel on their own queue, one at a time.
//
// A compressed shelf photo is ~120 KB against a visit record's ~2 KB. Sharing the outbox would
// mean a whole day of records waiting behind one photo crawling up a 2G link, and a manager
// seeing no coverage until the pictures finished. Records go first; pictures follow.

const MAX_ATTEMPTS = 8

function backoffMs(attempts) {
  return Math.min(2 ** attempts, 300) * 1000
}

/** Queue a photo against a visit, by the visit's client id rather than its server name.
 *
 * The visit may not have synced yet - it may not even have a server name - and the rep should
 * not have to wait to take the next picture.
 */
export async function queue(visitClientUuid, { dataUrl, purpose, caption, kb, fix = {} }) {
  const clientUuid = crypto.randomUUID()
  await db.photos.add({
    clientUuid,
    visitClientUuid,
    dataUrl,
    purpose: purpose || 'Other',
    caption: caption || null,
    kb: kb || 0,
    latitude: fix.latitude ?? null,
    longitude: fix.longitude ?? null,
    takenAt: new Date().toISOString().slice(0, 19).replace('T', ' '),
    state: 'queued',
    attempts: 0,
    nextAttemptAt: 0,
  })
  return clientUuid
}

export async function pendingCount(visitClientUuid = null) {
  const rows = await db.photos.where('state').anyOf('queued', 'failed').toArray()
  return visitClientUuid
    ? rows.filter((r) => r.visitClientUuid === visitClientUuid).length
    : rows.length
}

/** Send what is ready, oldest first, one request each. */
export async function drain() {
  if (!navigator.onLine) return { sent: 0, skipped: 'offline' }

  const now = Date.now()
  const ready = (await db.photos.where('state').anyOf('queued', 'failed').sortBy('id'))
    .filter((p) => p.nextAttemptAt <= now)

  let sent = 0
  for (const photo of ready) {
    const visit = await serverNameFor(photo.visitClientUuid)
    if (!visit) {
      // The visit has not landed yet. Held rather than failed - this is the normal order of
      // events after a morning offline, not an error worth showing anyone.
      continue
    }

    try {
      await api.uploadPhoto(visit, {
        photo: photo.dataUrl,
        purpose: photo.purpose,
        caption: photo.caption,
        taken_at: photo.takenAt,
        latitude: photo.latitude,
        longitude: photo.longitude,
        size_kb: photo.kb,
        client_uuid: photo.clientUuid,
      })
      // The image is the heaviest thing on this device. Once the server has it, drop it.
      await db.photos.delete(photo.id)
      sent += 1
    } catch (e) {
      const attempts = photo.attempts + 1
      const fatal = e instanceof ApiError &&
        ['AUTH_REQUIRED', 'DEVICE_INACTIVE', 'VALIDATION_FAILED'].includes(e.code)
      await db.photos.update(photo.id, {
        state: fatal || attempts >= MAX_ATTEMPTS ? 'blocked' : 'failed',
        attempts,
        nextAttemptAt: Date.now() + backoffMs(attempts),
        lastError: e.message,
      })
      if (e instanceof ApiError && e.code === 'OFFLINE') break
    }
  }
  return { sent }
}
