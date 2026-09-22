import { db, deviceUuid, getMeta, setMeta, putRecord, rememberName } from '../db'
import { api, ApiError } from '../api/client'

const BATCH_SIZE = 50
const MAX_ATTEMPTS = 6

// The client assigns identity; the server honours it. Because every record carries a
// clientUuid with a unique index server-side, a push can be retried freely - the server
// upserts and returns whatever it already has. No duplicates, ever.
// A caller may supply the id when something already references it - a photo queued against a
// visit holds that visit's clientUuid, and generating a fresh one here would orphan it.
export async function enqueue(doctype, data, { dependsOn = null, clientUuid = null } = {}) {
  clientUuid = clientUuid || crypto.randomUUID()
  await db.outbox.add({
    clientUuid,
    doctype,
    data,
    dependsOn,
    state: 'queued',
    attempts: 0,
    nextAttemptAt: 0,
    createdAt: Date.now(),
  })
  return clientUuid
}

export async function pendingCount() {
  return db.outbox.where('state').anyOf('queued', 'failed').count()
}

function backoffMs(attempts) {
  return Math.min(2 ** attempts, 64) * 1000
}

/** Drain the outbox. Safe to call repeatedly and concurrently-ish. */
export async function drain({ appVersion = '0.0.1' } = {}) {
  if (!navigator.onLine) return { skipped: 'offline' }

  const now = Date.now()
  const all = await db.outbox
    .where('state').anyOf('queued', 'failed')
    .sortBy('seq')

  const ready = []
  const heldUuids = new Set()

  for (const item of all) {
    if (item.nextAttemptAt > now) { heldUuids.add(item.clientUuid); continue }
    // A blocked parent holds its children rather than orphaning them.
    if (item.dependsOn && heldUuids.has(item.dependsOn)) { heldUuids.add(item.clientUuid); continue }
    ready.push(item)
    if (ready.length >= BATCH_SIZE) break
  }

  if (!ready.length) return { sent: 0 }

  const device = await deviceUuid()
  const batchUuid = crypto.randomUUID()
  const records = ready.map((i) => ({
    doctype: i.doctype,
    client_uuid: i.clientUuid,
    data: i.data,
    depends_on: i.dependsOn,
  }))

  try {
    const result = await api.push(device, batchUuid, records, appVersion)
    const byUuid = new Map((result.results || []).map((r) => [r.client_uuid, r]))

    for (const item of ready) {
      const r = byUuid.get(item.clientUuid)
      if (!r) continue
      if (r.status === 'created' || r.status === 'duplicate') {
        // The server name has to outlive the outbox row: a photo queued against this visit
        // still needs somewhere to look up what the visit ended up being called.
        await rememberName(item.clientUuid, item.doctype, r.name)
        if (item.doctype === 'FieldMate Visit') {
          await db.visits.update(item.clientUuid, { serverName: r.name })
        }
        await db.outbox.delete(item.seq)
      } else if (r.status === 'held') {
        await db.outbox.update(item.seq, {
          state: 'queued',
          attempts: item.attempts + 1,
          nextAttemptAt: Date.now() + backoffMs(item.attempts + 1),
        })
      } else {
        // rejected or conflict - stop retrying and surface it in the Sync Centre.
        await db.outbox.update(item.seq, {
          state: 'blocked',
          lastError: r.message || r.code,
          conflict: r.conflict || null,
        })
      }
    }
    await setMeta('lastPushAt', Date.now())
    return { sent: ready.length, batchUuid, result }
  } catch (e) {
    const fatal = e instanceof ApiError && ['AUTH_REQUIRED', 'DEVICE_INACTIVE'].includes(e.code)
    for (const item of ready) {
      const attempts = item.attempts + 1
      await db.outbox.update(item.seq, {
        state: fatal || attempts >= MAX_ATTEMPTS ? 'blocked' : 'failed',
        attempts,
        nextAttemptAt: Date.now() + backoffMs(attempts),
        lastError: e.message,
      })
    }
    return { sent: 0, error: e.message }
  }
}

/** Delta pull into the local mirror. Server wins on masters, always. */
export async function pull() {
  const device = await deviceUuid()
  const since = await getMeta('watermark')
  const result = await api.pull(device, since)

  for (const [doctype, rows] of Object.entries(result.changes || {})) {
    for (const row of rows) {
      await putRecord(doctype, { ...row, name: row.name || row[Object.keys(row)[0]] })
    }
  }
  await setMeta('watermark', result.watermark)
  return result
}
