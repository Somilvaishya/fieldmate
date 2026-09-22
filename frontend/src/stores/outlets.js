import { db, putRecord } from '../db'
import { api, ApiError } from '../api/client'

/** Outlets from the local mirror. Screens never wait on the network. */
export async function localOutlets({ beat = null, query = '' } = {}) {
  let rows = await db.records.where('doctype').equals('FieldMate Outlet').toArray()
  if (beat) rows = rows.filter((r) => r.primary_beat === beat)
  if (query) {
    const q = query.toLowerCase()
    rows = rows.filter((r) =>
      [r.outlet_name, r.city, r.mobile_no].some((v) => (v || '').toLowerCase().includes(q))
    )
  }
  return rows.sort((a, b) => (a.outlet_name || '').localeCompare(b.outlet_name || ''))
}

export async function localOutlet(name) {
  return db.records.get(['FieldMate Outlet', name])
}

/** Refresh the mirror. Offline is not a failure here — the caller keeps what it has. */
export async function refreshOutlets() {
  try {
    const { outlets } = await api.outlets()
    for (const row of outlets) await putRecord('FieldMate Outlet', row)
    return { ok: true, count: outlets.length }
  } catch (e) {
    if (e instanceof ApiError && e.code === 'OFFLINE') return { ok: false, offline: true }
    throw e
  }
}
