/**
 * Finishing a visit — the screen that once would not let a rep leave the shop.
 *
 * A rep reported that check-out only worked when an order had been booked; every other outcome
 * left the button dead. The cause was a gate the app invented and could not satisfy: choosing
 * anything but "Order taken" demanded a **No Order Reason**, and a site with no reason master —
 * which is most sites on day one — has none to offer. The screen said "no reasons on this phone",
 * the rep could not create one, and the button stayed disabled for ever. The visit then stayed
 * open until the next check-in closed it as something it was not.
 *
 * The server never asked for a reason. `visit.check_out` records one if it is sent, the field is
 * not mandatory, and the auto-close path falls back to whatever reason exists or to none.
 *
 * So: a reason is required only when there is one to pick, a note takes its place when there is
 * not, and — the other half of the complaint — the button now **says what it is waiting for**
 * instead of sitting dead and silent.
 */
import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

const visit = ref(null)
const reasons = ref([])
const unanswered = ref([])
const checkOut = vi.fn()

vi.mock('../src/stores/visit', () => ({
  activeVisit: visit,
  resume: vi.fn(),
  noOrderReasons: async () => reasons.value,
  unansweredRequired: () => unanswered.value,
  checkOut: (...a) => checkOut(...a),
}))

vi.mock('../src/sync/photos', () => ({ pendingCount: async () => 0 }))
vi.mock('../src/lib/geo', () => ({ getPosition: async () => ({}) }))
vi.mock('../src/api/client', () => ({ ApiError: class ApiError extends Error {} }))
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: vi.fn(), back: vi.fn() }) }))

const { default: CheckOut } = await import('../src/screens/VisitCheckOut.vue')

function aVisit(extra = {}) {
  return {
    clientUuid: 'v-1',
    outletName: 'Nagpal Complex',
    checkInTime: '2026-10-12 11:00:00',
    checklist: [],
    remarks: '',
    order: null,
    ...extra,
  }
}

async function screen({ order = null, withReasons = [], missing = [] } = {}) {
  visit.value = aVisit({ order })
  reasons.value = withReasons
  unanswered.value = missing
  const w = mount(CheckOut, {
    global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
  })
  await flushPromises()
  return w
}

const REASONS = [
  { name: 'r1', reason: 'Shop shut', requires_note: 0 },
  { name: 'r2', reason: 'Owner away', requires_note: 1 },
]

/** The outcome buttons, in the order the screen lists them. */
function outcomes(w) {
  return w.findAll('.outcome')
}
function sendButton(w) {
  return w.find('.bottom .btn-primary')
}
async function pick(w, label) {
  const button = outcomes(w).find((b) => b.text().includes(label))
  expect(button, `no outcome called ${label}`).toBeTruthy()
  await button.trigger('click')
}

describe('a site with no No Order Reason master', () => {
  it('still lets the rep leave the shop', async () => {
    // The bug, in one line. Before this, picking anything but "Order taken" was a dead end.
    const w = await screen({ withReasons: [] })
    await pick(w, 'Shop closed')
    await w.find('#note').setValue('Shutter down, nobody there all afternoon.')
    expect(sendButton(w).attributes('disabled')).toBeUndefined()
  })

  it('asks for a note in the reason&apos;s place', async () => {
    // Not simply waved through: a visit that recorded no order and no explanation is a visit
    // nobody can act on.
    const w = await screen({ withReasons: [] })
    await pick(w, 'No order')
    expect(sendButton(w).attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('write what happened in the note')
  })

  it('says the rep can still check out, rather than telling them to sync', async () => {
    const w = await screen({ withReasons: [] })
    await pick(w, 'No order')
    expect(w.text()).toContain('still check out')
  })

  it('sends no reason at all, because there is none to send', async () => {
    const w = await screen({ withReasons: [] })
    await pick(w, 'Owner away')
    await w.find('#note').setValue('Back on Thursday.')
    await sendButton(w).trigger('click')
    await flushPromises()
    expect(checkOut.mock.calls.at(-1)[0].noOrderReason).toBeNull()
  })
})

describe('a site that has reasons', () => {
  it('still requires one to be picked', async () => {
    const w = await screen({ withReasons: REASONS })
    await pick(w, 'No order')
    expect(sendButton(w).attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('Pick why there was no order')
  })

  it('goes once a reason is chosen', async () => {
    const w = await screen({ withReasons: REASONS })
    await pick(w, 'No order')
    await w.findAll('.chip')[0].trigger('click')
    expect(sendButton(w).attributes('disabled')).toBeUndefined()
  })

  it('still demands a note where the reason asks for one', async () => {
    const w = await screen({ withReasons: REASONS })
    await pick(w, 'No order')
    await w.findAll('.chip')[1].trigger('click')
    expect(sendButton(w).attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('needs a note')
  })

  it('sends the reason it was given', async () => {
    const w = await screen({ withReasons: REASONS })
    await pick(w, 'No order')
    await w.findAll('.chip')[0].trigger('click')
    await sendButton(w).trigger('click')
    await flushPromises()
    expect(checkOut.mock.calls.at(-1)[0].noOrderReason).toBe('r1')
  })
})

describe('an order was booked here', () => {
  it('needs no reason and no note', async () => {
    const w = await screen({ order: { net: 98180, offline: false }, withReasons: REASONS })
    expect(sendButton(w).attributes('disabled')).toBeUndefined()
  })

  it('sends no reason', async () => {
    const w = await screen({ order: { net: 98180, offline: false }, withReasons: REASONS })
    await sendButton(w).trigger('click')
    await flushPromises()
    expect(checkOut.mock.calls.at(-1)[0].noOrderReason).toBeNull()
  })
})

describe('the button says what it is waiting for', () => {
  it('asks for an outcome first', async () => {
    const w = await screen({ withReasons: REASONS })
    expect(sendButton(w).attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('Pick what came of this visit')
  })

  it('names the checklist when questions are unanswered', async () => {
    const w = await screen({
      withReasons: REASONS,
      missing: [{ name: 'q1' }, { name: 'q2' }],
    })
    await pick(w, 'Order taken')
    expect(sendButton(w).attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('Answer 2 required questions')
  })

  it('counts one question in the singular', async () => {
    const w = await screen({ withReasons: REASONS, missing: [{ name: 'q1' }] })
    await pick(w, 'Order taken')
    expect(w.text()).toContain('Answer 1 required question in the checklist')
  })

  it('does not block a shop that was never open on its unanswered questions', async () => {
    // A shut shop cannot be surveyed. This was already true and is pinned so the new gate did
    // not quietly take it away.
    const w = await screen({ withReasons: REASONS, missing: [{ name: 'q1' }] })
    await pick(w, 'Shop closed')
    await w.findAll('.chip')[0].trigger('click')
    expect(sendButton(w).attributes('disabled')).toBeUndefined()
  })

  it('says nothing once it will go', async () => {
    const w = await screen({ order: { net: 1000, offline: false }, withReasons: REASONS })
    expect(w.find('.gate').exists()).toBe(false)
  })
})
