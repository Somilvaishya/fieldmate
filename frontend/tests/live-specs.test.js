/**
 * Which offers a phone still honours — the other half of a rule the server also enforces.
 *
 * `scheme_compile.for_outlet` filters on the same four dates before it ever sends a spec. This
 * copy exists so a phone three days behind on its sync retires an offer itself rather than
 * quoting one whose book shut on Sunday, and the two drifting apart is the exact class of bug
 * this app keeps finding in the field rather than in a test.
 *
 * Two windows, and they are different questions:
 *   valid_from / valid_to     — when the offer exists at all
 *   booking_from / booking_to — when the order has to be TAKEN to earn it
 *
 * A season scheme is live from November to March, because that is when it is billed, and rewards
 * only the orders booked in November.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../src/db', () => ({
  db: { carts: {}, catalogues: {}, outbox: {}, records: {}, visits: {} },
  deviceUuid: async () => 'device-1',
  getMeta: async (_k, fallback = null) => fallback,
  setMeta: async () => {},
  putRecord: async () => {},
  rememberName: async () => {},
  serverNameFor: async () => null,
}))
vi.mock('../src/api/client', () => ({
  api: {},
  ApiError: class ApiError extends Error {},
}))
vi.mock('../src/sync/outbox', () => ({ enqueue: vi.fn() }))
vi.mock('../src/sync/photos', () => ({ pendingCount: async () => 0 }))
vi.mock('../src/sync/pinger', () => ({ flushSoon: async () => {} }))
vi.mock('../src/stores/visit', () => ({ activeVisit: { value: null }, recordOrder: async () => {} }))

const { liveSpecs } = await import('../src/stores/order')

const TODAY = '2026-11-15'

/** One compiled spec, trimmed to the dates this is about. */
function spec(dates = {}) {
  return {
    scheme: 'FM-SCH-0001',
    valid_from: null,
    valid_to: null,
    booking_from: null,
    booking_to: null,
    ...dates,
  }
}

const kept = (s) => liveSpecs([s], TODAY).length === 1

beforeEach(() => {})

describe('the validity window', () => {
  it('keeps an offer with no dates at all', () => {
    // Every ordinary scheme, and it must stay true.
    expect(kept(spec())).toBe(true)
  })

  it('drops one that has not started', () => {
    expect(kept(spec({ valid_from: '2026-12-01' }))).toBe(false)
  })

  it('drops one that has ended', () => {
    expect(kept(spec({ valid_to: '2026-11-14' }))).toBe(false)
  })

  it('keeps one on its last day', () => {
    // Inclusive at both ends, as the server is. An offer good "to the 15th" is good on the 15th.
    expect(kept(spec({ valid_from: '2026-11-15', valid_to: '2026-11-15' }))).toBe(true)
  })
})

describe('the early-booking window', () => {
  it('keeps an order taken inside it', () => {
    expect(kept(spec({ booking_from: '2026-11-01', booking_to: '2026-11-30' }))).toBe(true)
  })

  it('drops one taken after the book shut', () => {
    expect(kept(spec({ booking_from: '2026-11-01', booking_to: '2026-11-14' }))).toBe(false)
  })

  it('drops one taken before it opened', () => {
    expect(kept(spec({ booking_from: '2026-11-16' }))).toBe(false)
  })

  it('is a different question from being live', () => {
    // Live from November to March because that is when it is billed; the book shut yesterday.
    expect(kept(spec({
      valid_from: '2026-11-01', valid_to: '2027-03-31',
      booking_from: '2026-11-01', booking_to: '2026-11-14',
    }))).toBe(false)
  })

  it('ignores a spec from a server that predates the window', () => {
    // An older build sends no such keys. `undefined` must read as "no window", not as a wall -
    // a phone that retired every offer after a server downgrade would quote nothing at all.
    const old = { scheme: 'FM-SCH-0001', valid_from: null, valid_to: null }
    expect(liveSpecs([old], TODAY)).toHaveLength(1)
  })
})

describe('across a list', () => {
  it('keeps only what still applies', () => {
    const specs = [
      spec({ scheme: 'LIVE' }),
      spec({ scheme: 'ENDED', valid_to: '2026-11-01' }),
      spec({ scheme: 'BOOK-SHUT', booking_to: '2026-11-01' }),
      spec({ scheme: 'IN-WINDOW', booking_from: '2026-11-01', booking_to: '2026-11-30' }),
    ]
    expect(liveSpecs(specs, TODAY).map((s) => s.scheme)).toEqual(['LIVE', 'IN-WINDOW'])
  })

  it('has nothing to say about an empty list', () => {
    expect(liveSpecs([], TODAY)).toEqual([])
    expect(liveSpecs(null, TODAY)).toEqual([])
  })
})
