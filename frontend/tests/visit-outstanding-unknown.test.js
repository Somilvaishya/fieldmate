/**
 * Not knowing what a shop owes is not the same as the shop owing nothing.
 *
 * The visit hub reads the outstanding figure best-effort - a rep with no signal still gets the
 * rest of the screen - and the failed read fell back to `0`. Zero is not a gap on this card: it
 * renders as **"Nothing outstanding"** under a **Clear** pill. So a rep standing in a shop that
 * owed money, on a handset that could not reach the server, was told the shop was clear and had
 * no reason to ask for anything.
 *
 * The three states are distinct now, and these pin that: a figure, a genuine zero, and a read
 * that did not happen.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const outstanding = vi.fn()

vi.mock('../src/api/client', () => ({
  api: {
    outstanding: (...a) => outstanding(...a),
  },
  ApiError: class ApiError extends Error {
    constructor(code, message) { super(message); this.code = code }
  },
}))
vi.mock('../src/db', () => ({
  db: { visits: { put: vi.fn(), update: vi.fn() } },
  deviceUuid: async () => 'device-1',
  getMeta: async (_k, fallback = null) => fallback,
  setMeta: async () => {},
  rememberName: async () => {},
}))
vi.mock('../src/sync/photos', () => ({
  // `forVisit` is what the hub calls to draw the shots it has taken. Leaving it out of the mock
  // threw inside onMounted, which rendered nothing - and a `not.toContain` against an empty
  // screen passes for the wrong reason.
  forVisit: async () => [],
  pendingCount: async () => 0,
  drain: async () => {},
}))
vi.mock('../src/sync/outbox', () => ({ enqueue: vi.fn(), pendingCount: async () => 0 }))
vi.mock('../src/sync/pinger', () => ({ flushSoon: async () => {} }))
vi.mock('../src/stores/day', () => ({ openDay: { value: { day: 'FM-DAY-1' } } }))
vi.mock('../src/stores/order', () => ({ peek: async () => ({ lines: 0, units: 0 }) }))

const visitStore = await import('../src/stores/visit')
const Visit = (await import('../src/screens/Visit.vue')).default

/** The rep is standing in the shop with the visit open. */
function standingInTheShop() {
  visitStore.activeVisit.value = {
    clientUuid: 'visit-1', serverName: 'FM-VIS-000234',
    outlet: 'FM-OUT-05814', outletName: 'Nagpal Complex', state: 'open',
    checkInTime: '2026-10-24 10:15:00',
    checklist: [], tasks: [], remarks: '', outcome: null,
  }
}

async function theMoneyCard() {
  const wrapper = mount(Visit, {
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' }, Icon: true } },
  })
  await flushPromises()
  return wrapper.text()
}

beforeEach(() => {
  outstanding.mockReset()
  standingInTheShop()
})

describe('the Collect payment card', () => {
  it('shows the figure when the server answers', async () => {
    outstanding.mockResolvedValue({ outstanding: 4200 })

    const text = await theMoneyCard()

    expect(text).toContain('outstanding')
    expect(text).not.toContain('Nothing outstanding')
  })

  it('says the shop is clear only when the server says zero', async () => {
    outstanding.mockResolvedValue({ outstanding: 0 })

    const text = await theMoneyCard()

    expect(text).toContain('Nothing outstanding')
  })

  it('does not claim the shop is clear when it could not ask', async () => {
    // The bug, in one assertion. A dead link used to render as "Nothing outstanding".
    outstanding.mockRejectedValue(new Error('no signal'))

    const text = await theMoneyCard()

    expect(text).not.toContain('Nothing outstanding')
    expect(text).toContain('Could not check what is owed')
  })
})
