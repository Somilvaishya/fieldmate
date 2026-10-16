/**
 * Checking out is how a visit ends.
 *
 * A rep standing in one shop could tap the next one from the list and the first visit was closed
 * for them - silently, stamped short, with nothing on the screen to say it had happened. A rep
 * could walk a row of shops leaving empty visits behind that still counted towards coverage.
 *
 * The refusal lives here as well as on the server, and **the one here is the one that matters**:
 * offline there is no server to ask, the visit queues with `created_offline` set, and the server
 * honours those rather than rejecting work the rep really did. So this is the only thing standing
 * between a stray tap and a closed visit.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const checkIn = vi.fn()

vi.mock('../src/db', () => ({
  db: { visits: { put: vi.fn(), update: vi.fn(), where: () => ({ equals: () => ({ toArray: async () => [] }) }) } },
  deviceUuid: async () => 'device-1',
  getMeta: async (_k, fallback = null) => fallback,
  setMeta: async () => {},
  putRecord: async () => {},
  rememberName: async () => {},
}))
vi.mock('../src/api/client', () => ({
  api: { checkIn: (...a) => checkIn(...a), currentVisit: async () => ({ open: false }) },
  ApiError: class ApiError extends Error {
    constructor(code, message) { super(message); this.code = code }
  },
}))
vi.mock('../src/sync/outbox', () => ({ enqueue: vi.fn() }))
vi.mock('../src/sync/photos', () => ({ pendingCount: async () => 0 }))
vi.mock('../src/sync/pinger', () => ({ flushSoon: async () => {} }))
vi.mock('../src/stores/day', () => ({ openDay: { value: { day: 'FM-DAY-1' } } }))

const visitStore = await import('../src/stores/visit')

const NAGPAL = { name: 'FM-OUT-05814', outlet_name: 'Nagpal Complex' }
const RAJA = { name: 'FM-OUT-05804', outlet_name: 'Raja Kirana' }

/** The rep is standing in Nagpal Complex with the visit open. */
function standingIn(outlet) {
  visitStore.activeVisit.value = {
    clientUuid: 'visit-1', serverName: 'FM-VIS-000234',
    outlet: outlet.name, outletName: outlet.outlet_name, state: 'open',
  }
}

beforeEach(() => {
  visitStore.activeVisit.value = null
  checkIn.mockReset()
  checkIn.mockResolvedValue({ visit: 'FM-VIS-000235', checklist: [], tasks: [] })
})

describe('a second shop while a visit is open', () => {
  it('is refused', async () => {
    standingIn(NAGPAL)
    await expect(visitStore.checkIn(RAJA)).rejects.toBeInstanceOf(visitStore.OpenVisitError)
  })

  it('names the shop the rep has to go back to', async () => {
    standingIn(NAGPAL)
    await expect(visitStore.checkIn(RAJA)).rejects.toThrow('Nagpal Complex')
  })

  it('does not reach the server at all', async () => {
    // The whole point. A refusal that had already asked the server to close the visit would be
    // the bug with a message attached - and offline there is no server to ask.
    standingIn(NAGPAL)
    await visitStore.checkIn(RAJA).catch(() => {})
    expect(checkIn).not.toHaveBeenCalled()
  })

  it('leaves the open visit open', async () => {
    standingIn(NAGPAL)
    await visitStore.checkIn(RAJA).catch(() => {})
    expect(visitStore.activeVisit.value.outlet).toBe(NAGPAL.name)
    expect(visitStore.activeVisit.value.state).toBe('open')
  })
})

describe('the ways through', () => {
  it('lets a rep who has left say so', async () => {
    // Offered, spelled out on screen, and never the first thing their thumb finds. Without it a
    // rep whose shop is behind them is stuck outside the next one.
    standingIn(NAGPAL)
    const visit = await visitStore.checkIn(RAJA, { closeOpen: true })
    expect(visit.outlet).toBe(RAJA.name)
    expect(checkIn).toHaveBeenCalledOnce()
    expect(checkIn.mock.calls[0][1].close_open_visit).toBe(1)
  })

  it('does not send the override when it was not asked for', async () => {
    const visit = await visitStore.checkIn(NAGPAL)
    expect(visit.outlet).toBe(NAGPAL.name)
    expect(checkIn.mock.calls[0][1].close_open_visit).toBe(0)
  })

  it('does not refuse the shop the rep is already in', async () => {
    // A rep re-opening the app, or a push being retried, is at the shop they are standing in.
    // Refusing that would lock them out of it, which is worse than what this fixes.
    standingIn(NAGPAL)
    await expect(visitStore.checkIn(NAGPAL)).resolves.toBeTruthy()
  })

  it('checks in freely when no visit is open', async () => {
    await expect(visitStore.checkIn(RAJA)).resolves.toBeTruthy()
  })
})
