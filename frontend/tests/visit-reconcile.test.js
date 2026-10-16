/**
 * What the phone shows as visited, after somebody in the office took it back.
 *
 * **The bug this pins.** `todaysVisits()` read IndexedDB and asked the server nothing. A day
 * cancelled in Desk — its day, its visits, its orders — left every one of those rows sitting
 * on the handset. The rep started their day again and the route still showed every shop as
 * covered, the progress bar still read done, and "next shop" pointed past shops nobody had been
 * to. Reported from the field exactly that way.
 *
 * The rule the fix must not break is the one the whole app is built on: **unsent work is never
 * thrown away**. A visit this phone has not yet sent has no server name, the server has never
 * heard of it, and its absence from the server's answer means nothing at all.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const visitHistory = vi.fn()

vi.mock('../src/api/client', () => ({
  api: { visitHistory: (...a) => visitHistory(...a) },
  ApiError: class ApiError extends Error {},
}))

vi.mock('../src/sync/outbox', () => ({ enqueue: vi.fn() }))
vi.mock('../src/sync/photos', () => ({ pendingCount: async () => 0, queue: vi.fn() }))
vi.mock('../src/sync/pinger', () => ({ flushSoon: vi.fn() }))
vi.mock('../src/stores/day', () => ({ openDay: { value: null }, refresh: vi.fn() }))

const visitStore = await import('../src/stores/visit')
const { db } = await import('../src/db')

function today() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** A visit row as the phone stores one. `serverName` is what says it has been sent. */
async function put({ uuid, outlet, serverName = null, state = 'closed' }) {
  await db.visits.put({
    clientUuid: uuid,
    visitDate: today(),
    outlet,
    outletName: outlet,
    serverName,
    state,
    checkInTime: `${today()} 10:00:00`,
    checklist: [],
  })
}

beforeEach(async () => {
  await db.visits.clear()
  visitHistory.mockReset()
})

describe('a visit the office cancelled', () => {
  it('stops being shown as visited', async () => {
    // The bug, in one assertion.
    await put({ uuid: 'v-1', outlet: 'SHOP-A', serverName: 'FM-VISIT-0001' })
    visitHistory.mockResolvedValue({ visits: [] })

    const rows = await visitStore.todaysVisits()
    expect(rows).toHaveLength(0)
  })

  it('leaves the ones the server still has', async () => {
    await put({ uuid: 'v-1', outlet: 'SHOP-A', serverName: 'FM-VISIT-0001' })
    await put({ uuid: 'v-2', outlet: 'SHOP-B', serverName: 'FM-VISIT-0002' })
    visitHistory.mockResolvedValue({ visits: [{ visit: 'FM-VISIT-0002' }] })

    const rows = await visitStore.todaysVisits()
    expect(rows.map((r) => r.outlet)).toEqual(['SHOP-B'])
  })
})

describe('work this phone has not sent yet', () => {
  it('survives, whatever the server says', async () => {
    // The rule the whole app is built on. A visit with no server name was never sent, so the
    // server's silence about it is not evidence of anything.
    await put({ uuid: 'v-3', outlet: 'SHOP-C', serverName: null })
    visitHistory.mockResolvedValue({ visits: [] })

    const rows = await visitStore.todaysVisits()
    expect(rows.map((r) => r.outlet)).toEqual(['SHOP-C'])
  })

  it('survives beside a cancelled one', async () => {
    await put({ uuid: 'v-1', outlet: 'SHOP-A', serverName: 'FM-VISIT-0001' })
    await put({ uuid: 'v-3', outlet: 'SHOP-C', serverName: null })
    visitHistory.mockResolvedValue({ visits: [] })

    const rows = await visitStore.todaysVisits()
    expect(rows.map((r) => r.outlet)).toEqual(['SHOP-C'])
  })

  it('survives an open visit the rep is standing in', async () => {
    await put({ uuid: 'v-4', outlet: 'SHOP-D', serverName: null, state: 'open' })
    visitHistory.mockResolvedValue({ visits: [] })

    const rows = await visitStore.todaysVisits()
    expect(rows).toHaveLength(1)
  })
})

describe('with no signal', () => {
  it('keeps everything, because a dead link is not a cancellation', async () => {
    await put({ uuid: 'v-1', outlet: 'SHOP-A', serverName: 'FM-VISIT-0001' })
    visitHistory.mockRejectedValue(new Error('no connection'))

    const rows = await visitStore.todaysVisits()
    expect(rows).toHaveLength(1)
  })

  it('asks for today, not for whatever the server feels like', async () => {
    await put({ uuid: 'v-1', outlet: 'SHOP-A', serverName: 'FM-VISIT-0001' })
    visitHistory.mockResolvedValue({ visits: [{ visit: 'FM-VISIT-0001' }] })

    await visitStore.todaysVisits()
    expect(visitHistory).toHaveBeenCalledWith(today())
  })
})

describe('the answer the server actually sends', () => {
  it('is read by the key `visit.history` uses', async () => {
    // It selects `name as visit`. Reading `name` here would match nothing, every synced row would
    // look cancelled, and the fix would delete a rep's whole day.
    await put({ uuid: 'v-1', outlet: 'SHOP-A', serverName: 'FM-VISIT-0001' })
    visitHistory.mockResolvedValue({ visits: [{ visit: 'FM-VISIT-0001' }] })

    expect(await visitStore.todaysVisits()).toHaveLength(1)
  })

  it('is also read when the call answers a bare list', async () => {
    await put({ uuid: 'v-1', outlet: 'SHOP-A', serverName: 'FM-VISIT-0001' })
    visitHistory.mockResolvedValue([{ visit: 'FM-VISIT-0001' }])

    expect(await visitStore.todaysVisits()).toHaveLength(1)
  })
})
