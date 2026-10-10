/**
 * The season book screen — the one list where the figure matters more than the status.
 *
 * A booking is a commitment taken months before delivery, and between the counter and the lorry
 * there is exactly one thing a rep has to keep going back for: the advance. Nothing is reserved
 * and nothing is planned until that money is in hand.
 *
 * So the tests below are mostly about what the screen must not let a rep believe:
 *
 *   - that a post-dated cheque has paid the advance. It is allocated to the booking and shown
 *     against it, and it is not money until its date — `in_hand_by_order` says so and
 *     `release_if_paid` honours it. A screen that added it to the advance would have the rep tell
 *     a party their stock is coming against a cheque that may yet bounce.
 *   - that "Awaiting Advance" is something a manager can clear. Nobody is deciding anything.
 *   - that the goods figure is the bill. The party is billed the net plus GST, like everywhere
 *     else this app prints a total.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const orderBookings = vi.fn()

vi.mock('../src/api/client', () => ({
  api: { orderBookings: () => orderBookings() },
  ApiError: class ApiError extends Error {},
}))

const { default: Bookings } = await import('../src/screens/Bookings.vue')

/** One row as `order.my_bookings` sends it. */
function booking(extra = {}) {
  return {
    name: 'FM-ORD-000204',
    order_date: '2025-11-14',
    customer: 'Mahalaxmi Distributors',
    season: 'FM-SEASON-0001',
    season_name: 'Holi 2026',
    net_total: 40000,
    tax_total: 7200,
    grand_total: 47200,
    order_status: 'Awaiting Advance',
    docstatus: 1,
    advance_required: 10000,
    advance_in_hand: 0,
    advance_short: 10000,
    pdc_total: 0,
    held: true,
    rates_locked: true,
    rates_locked_on: '2025-11-14 18:02:00',
    tops_up: null,
    delivery_from: '2026-02-20',
    delivery_to: '2026-03-10',
    ...extra,
  }
}

async function screen(bookings) {
  orderBookings.mockResolvedValue({ bookings })
  const wrapper = mount(Bookings, {
    global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
  })
  await flushPromises()
  return wrapper
}

// No `mockReset` here, and the reason is worth keeping: vitest reports a rejection from a mock
// that was reset in `beforeEach` as **unhandled**, even where the component catches it - so the
// offline test below failed over a message it had drawn correctly. `restoreMocks` in
// `vitest.config.js` already resets every implementation between tests, so the line was redundant
// as well as harmful.

describe('the advance, which is why this screen exists', () => {
  it('says what is still to collect on the row', async () => {
    const w = await screen([booking()])
    expect(w.text()).toContain('Still to collect')
    expect(w.text()).toContain('10,000')
  })

  it('says what has arrived against what is needed', async () => {
    const w = await screen([booking({ advance_in_hand: 6000, advance_short: 4000 })])
    expect(w.text()).toContain('6,000')
    expect(w.text()).toContain('10,000')
    expect(w.text()).toContain('4,000')
  })

  it('totals what the day is actually for', async () => {
    const w = await screen([
      booking({ name: 'A', advance_short: 10000 }),
      booking({ name: 'B', advance_short: 2500 }),
    ])
    expect(w.text()).toContain('12,500')
    expect(w.text()).toContain('to collect')
  })

  it('says nothing is outstanding when nothing is', async () => {
    const w = await screen([booking({ advance_in_hand: 10000, advance_short: 0 })])
    expect(w.text()).toContain('Nothing outstanding')
  })

  it('says so plainly where the season asks for no advance', async () => {
    // A season sold on open terms. Somebody decided that, and a blank where the advance would
    // be reads as a figure nobody has filled in.
    const w = await screen([
      booking({ advance_required: 0, advance_short: 0, order_status: 'Approved' }),
    ])
    expect(w.text()).toContain('no advance')
  })
})

describe('what a post-dated cheque must not be read as', () => {
  it('reports it apart from the advance, never added to it', async () => {
    const w = await screen([
      booking({ advance_in_hand: 0, advance_short: 10000, pdc_total: 10000 }),
    ])
    const text = w.text()
    // Still short by the whole advance...
    expect(text).toContain('Still to collect')
    // ...and the cheque is named, with what it is waiting for.
    expect(text).toContain('post-dated')
    expect(text).toContain('does not count until it falls due')
  })

  it('still says nothing is reserved while it is short', async () => {
    const w = await screen([booking({ pdc_total: 10000 })])
    expect(w.text()).toContain('Nothing is reserved or dispatched')
  })

  it('says nothing about cheques when there are none', async () => {
    const w = await screen([booking({ pdc_total: 0 })])
    expect(w.text()).not.toContain('post-dated')
  })
})

describe('what the status is called', () => {
  it('reads as waiting for money, not waiting for a manager', async () => {
    // "Awaiting Advance" is the field's value. A rep reading "pending approval" would chase a
    // manager who cannot do anything about it.
    const w = await screen([booking()])
    expect(w.text()).toContain('Waiting for the advance')
    expect(w.text()).not.toContain('Waiting on your manager')
  })

  it('still distinguishes a real approval', async () => {
    const w = await screen([booking({ order_status: 'Pending Approval' })])
    expect(w.text()).toContain('Waiting on your manager')
  })
})

describe('the figures beside the advance', () => {
  it('shows the bill total, not the goods', async () => {
    // The same bug the orders list had: `net_total` is the goods and the party is billed the GST
    // on top of it.
    const w = await screen([booking()])
    expect(w.text()).toContain('47,200')
    expect(w.text()).not.toContain('40,000')
  })

  it('falls back to the net where no tax template covers it', async () => {
    const w = await screen([booking({ tax_total: 0, grand_total: 0 })])
    expect(w.text()).toContain('40,000')
  })

  it('names the party and the season', async () => {
    const w = await screen([booking()])
    expect(w.text()).toContain('Mahalaxmi Distributors')
    expect(w.text()).toContain('Holi 2026')
  })

  it('says the rates are held, which is what the party was promised', async () => {
    const w = await screen([booking({ rates_locked: true })])
    expect(w.text()).toContain('Rates held')
  })

  it('says which booking a top-up adds to', async () => {
    const w = await screen([booking({ tops_up: 'FM-ORD-000180' })])
    expect(w.text()).toContain('FM-ORD-000180')
  })
})

describe('when there is nothing to show', () => {
  it('explains what makes a booking rather than saying nothing', async () => {
    const w = await screen([])
    expect(w.text()).toContain('No bookings yet')
    expect(w.text()).toContain('season')
  })

  it('says the list needs signal rather than drawing a stale one', async () => {
    // These figures move because somebody else banked a cheque. A cached copy is wrong in the
    // one direction that matters: it asks a party for money they have already paid.
    // `mockImplementation`, not `mockRejectedValue`: the latter builds its rejected promise
    // eagerly, so the rejection is reported before the screen ever gets to catch it.
    orderBookings.mockImplementation(() => Promise.reject(new Error('offline')))
    const wrapper = mount(Bookings, {
      global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('signal')
  })
})
