/**
 * The orders list — the figure a rep reads back to a shopkeeper.
 *
 * A rep booked a primary order of 981.80 and the Sales Order in Desk read 1,099.62. The phone
 * showed 981.80 everywhere, because this screen drew `net_total` and the server never sent the
 * tax at all. The same order's card had **no name on it**: a primary order has no outlet, it has
 * a customer, and the list asked only for the outlet.
 *
 * Both were one-line template bugs over a server that had the right answer, and no test in the
 * repo could see a template. This is the one that can.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const orderList = vi.fn()

vi.mock('../src/api/client', () => ({
  api: { orderList: () => orderList() },
  ApiError: class ApiError extends Error {},
}))

const { default: Orders } = await import('../src/screens/Orders.vue')

/** The shape `order.mine` sends, which is what this screen reads. */
function order(extra = {}) {
  return {
    name: 'FM-ORD-000169',
    order_date: '2026-10-06',
    outlet: null,
    outlet_name: null,
    customer: null,
    party_type: 'Outlet',
    net_total: 981.8,
    tax_total: 0,
    grand_total: 0,
    order_status: 'Approved',
    docstatus: 1,
    ...extra,
  }
}

async function screen(orders) {
  orderList.mockResolvedValue({ orders })
  const wrapper = mount(Orders, {
    global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => orderList.mockReset())

describe('what the card says the order came to', () => {
  it('shows the bill total, not the goods', async () => {
    const w = await screen([order({ tax_total: 117.82, grand_total: 1099.62 })])
    expect(w.text()).toContain('1,099.62')
    expect(w.text()).not.toContain('981.80')
  })

  it('falls back to the net where no tax template covers the cart', async () => {
    // Zero is the ordinary state of a site holding no tax templates. A blank where a figure
    // belongs is worse than the net.
    const w = await screen([order({ tax_total: 0, grand_total: 0 })])
    expect(w.text()).toContain('981.80')
  })

  it('adds up the day on bill totals too', async () => {
    const w = await screen([
      order({ name: 'A', grand_total: 1099.62 }),
      order({ name: 'B', net_total: 500, grand_total: 560 }),
    ])
    expect(w.text()).toContain('1,659.62')
  })
})

describe('whose order it is', () => {
  it('names the party on a primary order, which has no outlet', async () => {
    const w = await screen([order({
      party_type: 'Customer', outlet: null, customer: 'Mahalaxmi Distributors',
      grand_total: 1099.62,
    })])
    expect(w.text()).toContain('Mahalaxmi Distributors')
  })

  it('names the shop on a secondary order', async () => {
    const w = await screen([order({ outlet: 'FM-OUT-05814', outlet_name: 'Nagpal Complex' })])
    expect(w.text()).toContain('Nagpal Complex')
  })

  it('never draws a card with no name at all', async () => {
    // The worst case: a rep looking at a row they cannot identify. The document id is a poor
    // name and a far better one than nothing.
    const w = await screen([order({ outlet: null, outlet_name: null, customer: null })])
    expect(w.text()).toContain('FM-ORD-000169')
  })
})
