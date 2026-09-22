import Dexie from 'dexie'

// Local truth. Screens read from here, never from the network - a screen that awaits a
// request cannot work in a basement market with no signal.
export const db = new Dexie('fieldmate')

db.version(1).stores({
  // The outbox. `seq` keeps FIFO order; `dependsOn` holds a parent's clientUuid so a
  // visit lands before its order and an order before its collection.
  outbox: '++seq, clientUuid, doctype, state, dependsOn',
  // Mirrored server records, keyed by doctype + name.
  records: '[doctype+name], doctype, modified',
  // Watermarks, device id, profile, settings.
  meta: 'key',
})

// GPS pings collected while a day is open. Held here rather than in memory so a reload, a
// backgrounded tab or a killed app does not lose the morning's trail.
db.version(2).stores({
  outbox: '++seq, clientUuid, doctype, state, dependsOn',
  records: '[doctype+name], doctype, modified',
  meta: 'key',
  pings: '++id, t, sent',
})

// Visits and their photos.
//
// `visits` is the working copy a screen reads and writes while the rep is in the shop. It
// exists even online, because a check-in that only lives on the server is a check-in that
// vanishes when the lift doors close.
//
// `photos` is deliberately its own queue rather than outbox rows. A shelf photo is two orders
// of magnitude larger than a visit record, and putting them in one FIFO means a day's records
// sit behind a single photo crawling up a 2G link.
//
// `names` maps a clientUuid to the server name it was given, which is how a queued photo finds
// the visit it belongs to once that visit has synced.
db.version(3).stores({
  outbox: '++seq, clientUuid, doctype, state, dependsOn',
  records: '[doctype+name], doctype, modified',
  meta: 'key',
  pings: '++id, t, sent',
  visits: 'clientUuid, serverName, outlet, visitDate, state',
  photos: '++id, visitClientUuid, state',
  names: 'clientUuid, name',
})

export async function rememberName(clientUuid, doctype, name) {
  if (!clientUuid || !name) return
  await db.names.put({ clientUuid, doctype, name })
}

export async function serverNameFor(clientUuid) {
  const row = await db.names.get(clientUuid)
  return row ? row.name : null
}

/** Strip anything IndexedDB cannot structured-clone.
 *
 * Vue refs hand back reactive Proxies, and a Proxy throws DataCloneError on put(). Everything
 * we persist is plain JSON anyway, so a round-trip both sanitises the value and guarantees no
 * caller can poison the store by passing something live.
 */
function plain(value) {
  if (value === null || typeof value !== 'object') return value
  try {
    return JSON.parse(JSON.stringify(value))
  } catch {
    return null
  }
}

export async function setMeta(key, value) {
  await db.meta.put({ key, value: plain(value) })
}

export async function putRecord(doctype, row) {
  await db.records.put(plain({ doctype, ...row }))
}

export async function getMeta(key, fallback = null) {
  const row = await db.meta.get(key)
  return row ? row.value : fallback
}

export async function deviceUuid() {
  let id = await getMeta('deviceUuid')
  if (!id) {
    id = crypto.randomUUID()
    await setMeta('deviceUuid', id)
  }
  return id
}

export async function wipe() {
  // Called on logout or deregistration. A lost handset carries a territory's outlet data.
  await db.delete()
}
