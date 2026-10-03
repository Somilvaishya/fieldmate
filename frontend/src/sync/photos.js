import { db, deviceUuid, serverNameFor } from '../db'
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
export async function queue(visitClientUuid, { dataUrl, thumb, purpose, caption, kb, fix = {} }) {
  const clientUuid = crypto.randomUUID()
  await db.photos.add({
    clientUuid,
    visitClientUuid,
    dataUrl,
    // A few kilobytes kept back when the full image is dropped, so the rep can still see what
    // they photographed. Without it the visit showed a count that fell to zero the moment the
    // upload succeeded, which reads as "the photo is gone" rather than "the photo arrived".
    thumb: thumb || null,
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

/** Every photo of one visit, sent or not, newest last. What the visit screen shows. */
export async function forVisit(visitClientUuid) {
  const rows = await db.photos.where('visitClientUuid').equals(visitClientUuid).sortBy('id')
  return rows.map(({ id, clientUuid, purpose, thumb, state, takenAt, lastError }) => ({
    id, clientUuid, purpose, thumb, state, takenAt, lastError,
  }))
}

/** Drop the thumbnails of visits closed a while ago. Called on day end.
 *
 * The thumbnails exist so a rep can see this morning's work, not to become a gallery. A day of
 * them is perhaps 60 KB; a season of them is not something to leave on a phone nobody clears.
 */
export async function forgetSentBefore(ms) {
  const old = await db.photos
    .where('state').equals('sent')
    .filter((p) => (p.sentAt || 0) < ms)
    .toArray()
  await db.photos.bulkDelete(old.map((p) => p.id))
  return old.length
}

/** Send what is ready, oldest first, one request each. */
export async function drain() {
  if (!navigator.onLine) return { sent: 0, skipped: 'offline' }

  const now = Date.now()
  const ready = (await db.photos.where('state').anyOf('queued', 'failed').sortBy('id'))
    .filter((p) => p.nextAttemptAt <= now)

  let sent = 0
  // Once for the whole drain, not once per photo: it is the same id for every one of them.
  const device = await deviceUuid()
  for (const photo of ready) {
    const visit = await serverNameFor(photo.visitClientUuid)
    if (!visit) {
      // The visit has not landed yet. Held rather than failed - this is the normal order of
      // events after a morning offline, not an error worth showing anyone.
      continue
    }

    try {
      await api.uploadPhoto(device, visit, {
        photo: photo.dataUrl,
        purpose: photo.purpose,
        caption: photo.caption,
        taken_at: photo.takenAt,
        latitude: photo.latitude,
        longitude: photo.longitude,
        size_kb: photo.kb,
        client_uuid: photo.clientUuid,
      })
      // The full image is the heaviest thing on this device. Once the server has it, drop that
      // and keep only the thumbnail, so the visit can still show what was taken.
      await db.photos.update(photo.id, {
        state: 'sent',
        dataUrl: null,
        sentAt: Date.now(),
        lastError: null,
      })
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
