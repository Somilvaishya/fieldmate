/**
 * One cart is one order, however many times the rep taps send.
 *
 * **The bug this pins.** `submit()` minted a fresh `crypto.randomUUID()` on every call. On a market
 * uplink the first request reaches the server and its answer does not; the rep taps again; the
 * server — which dedupes on exactly that id — sees an order it has never heard of. Two FieldMate
 * Orders, two Sales Orders, two commitments the company has to honour, found later by somebody
 * reconciling a ledger. It was reported from the field as "ek primary order multiple time ban rahe
 * hain".
 *
 * The repo already knew the rule. `Money.vue` mints its receipt id once when the form opens, and
 * says why in a comment about collecting a depot's money twice. The order path did the opposite.
 *
 * These drive the **real store** against a **real IndexedDB** (fake-indexeddb, as every test here
 * does) so the cart genuinely persists and comes back. Only the network is mocked — which is the
 * only part that was ever in doubt.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const catalogue = vi.fn()
const orderSubmit = vi.fn()
const enqueued = vi.fn()

vi.mock('../src/api/client', () => ({
  api: {
    catalogue: (...a) => catalogue(...a),
    orderSubmit: (...a) => orderSubmit(...a),
    catalogueLastOrder: async () => ({}),
    schemesFor: async () => ({ specs: [] }),
  },
  ApiError: class ApiError extends Error {
    constructor(code, message) {
      super(message)
      this.code = code
    }
  },
}))

vi.mock('../src/sync/outbox', () => ({ enqueue: (...a) => enqueued(...a) }))

vi.mock('../src/stores/visit', () => ({
  activeVisit: ref(null),
  // The order path asks for the open visit rather than reading the ref, so that a reload between
  // check-in and the punch does not send the order with no visit on it. No visit here: these
  // tests are about the cart's own identity.
  ensureActive: async () => null,
  recordOrder: vi.fn(),
}))

const { ApiError } = await import('../src/api/client')
const cart = await import('../src/stores/order')
const { db } = await import('../src/db')

const SHOP = 'SHOP-1'

/** One priced item, which is all a cart needs to exist. */
function payload() {
  return {
    outlet: SHOP,
    outlet_name: 'Nagpal Complex',
    price_list: 'Standard Selling',
    currency: 'INR',
    company: 'test',
    items: [
      {
        item_code: 'SOAP-100',
        item_name: 'Toilet soap 100g',
        rate: 10,
        uom: 'Nos',
        stock_uom: 'Nos',
        display_uom: 'Nos',
        conversion_factor: 1,
        unpriceable: false,
        above_mrp: false,
        sort_order: 1,
        currency: 'INR',
        tax_bps: 0,
      },
    ],
    last_order: {},
  }
}

async function aCartWithSomethingInIt() {
  catalogue.mockResolvedValue(payload())
  await cart.openOutlet(SHOP, { type: null })
  await cart.addItem('SOAP-100', { qty: 5 })
  expect(cart.isEmpty.value).toBe(false)
}

beforeEach(async () => {
  await db.carts.clear()
  await cart.clear()
  catalogue.mockReset()
  orderSubmit.mockReset()
  enqueued.mockReset()
})

describe('sending the same cart twice', () => {
  it('sends the same id both times', async () => {
    // The whole bug in one assertion. Before the fix these were two different ids, and the server
    // had no way to know it was being told about one order twice.
    await aCartWithSomethingInIt()

    // A refusal that is **not** a dead link leaves the cart on the screen, exactly as it should:
    // the rep fixes what the server complained about and sends again. Before the fix that second
    // tap was a different order - and if the first one had in fact landed, the company now owed
    // the goods twice.
    orderSubmit.mockRejectedValueOnce(new ApiError('VALIDATION_FAILED', 'Fix something.'))
    await cart.submit().catch(() => {})
    expect(cart.isEmpty.value).toBe(false)

    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000001' })
    const second = await cart.submit()

    expect(second.client_uuid).toBe(orderSubmit.mock.calls[0][1].client_uuid)
  })

  it('keeps the id after the screen is closed and reopened', async () => {
    // A rep whose app was killed mid-send must resend as the same order. The id rides in the cart
    // record, so it comes back from IndexedDB with the lines.
    await aCartWithSomethingInIt()
    const before = (await db.carts.get(SHOP))?.clientUuid
    expect(before).toBeTruthy()

    await cart.openOutlet(SHOP, { refresh: false, type: null })
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000002' })
    const sent = await cart.submit()

    expect(sent.client_uuid).toBe(before)
  })
})

describe('a fresh cart is a fresh order', () => {
  it('gets a different id once the last one was sent', async () => {
    // The other half. If the id outlived the cart, the next order at the same shop would come back
    // as the previous one and never be booked at all.
    await aCartWithSomethingInIt()
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000003' })
    const first = await cart.submit()

    await aCartWithSomethingInIt()
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000004' })
    const second = await cart.submit()

    expect(second.client_uuid).not.toBe(first.client_uuid)
  })

  it('clears the id with the cart', async () => {
    await aCartWithSomethingInIt()
    expect((await db.carts.get(SHOP))?.clientUuid).toBeTruthy()
    await cart.clear()
    expect(await db.carts.get(SHOP)).toBeUndefined()
  })
})

describe('what the server is actually sent', () => {
  it('carries the cart id as the order id', async () => {
    await aCartWithSomethingInIt()
    const held = (await db.carts.get(SHOP))?.clientUuid

    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000005' })
    await cart.submit()

    expect(orderSubmit.mock.calls.at(-1)[1].client_uuid).toBe(held)
  })

  it('queues under the same id when there is no signal', async () => {
    // The offline path has to agree with the online one, or an order queued and then retried
    // online lands twice.
    await aCartWithSomethingInIt()
    const held = (await db.carts.get(SHOP))?.clientUuid

    orderSubmit.mockRejectedValue(new ApiError('OFFLINE', 'No connection.'))
    const queued = await cart.submit()

    expect(queued.offline).toBe(true)
    expect(queued.client_uuid).toBe(held)
    expect(enqueued.mock.calls.at(-1)[2].clientUuid).toBe(held)
  })
})
