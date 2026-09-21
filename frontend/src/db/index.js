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

export async function setMeta(key, value) {
  await db.meta.put({ key, value })
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
