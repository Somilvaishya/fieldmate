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

/** Refresh the mirror. Offline is not a failure here — the caller keeps what it has.
 *
 * Rows are MERGED, not replaced. The search endpoint returns the narrow list projection,
 * while the sync pull and the shop's own screen store a fuller record; overwriting wholesale
 * silently deleted fields that were already on the phone, so a shop opened offline lost its
 * GSTIN, credit terms and photo the next time the list refreshed.
 *
 * No error escapes: a caller's onMounted has nowhere to put a rejection, and an expired
 * session used to surface as a silent unhandled promise.
 */
export async function refreshOutlets() {
  try {
    const { outlets } = await api.outlets()
    for (const row of outlets) {
      const existing = await db.records.get(['FieldMate Outlet', row.name])
      await putRecord('FieldMate Outlet', { ...(existing || {}), ...row })
    }
    return { ok: true, count: outlets.length }
  } catch (e) {
    if (e instanceof ApiError && e.code === 'OFFLINE') return { ok: false, offline: true }
    return { ok: false, error: e instanceof ApiError ? e.message : 'Could not refresh shops.' }
  }
}
