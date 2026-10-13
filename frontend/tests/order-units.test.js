/**
 * Changing the unit a line is ordered in, offline, on the handset.
 *
 * #12. The choices come from the item master and travel with the catalogue, so the dropdown works
 * in a market with no signal - a rep cannot ask the server what a case is at the moment they
 * change their mind about the unit.
 *
 * **The decision this file pins.** Somebody who typed 5 and then reaches for the dropdown meant
 * five cases. They are correcting the unit, not the number. So the typed figure is kept and the
 * base quantity is recomputed - which multiplies the order, and has to, because the alternative
 * is restating their five pieces as four tenths of a case and leaving them to work out what to
 * type instead.
 *
 * The other half is what must NOT move: `rate_paise` is per base unit. A case costs twelve times
 * a piece because it holds twelve of them, not because its rate is a different number. A second
 * rate per unit would be a second place for the price to be wrong.
 *
 * Driven against the real store and a real IndexedDB, as every test here is. Only the network is
 * mocked.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'

const catalogue = vi.fn()

vi.mock('../src/api/client', () => ({
  api: {
    catalogue: (...a) => catalogue(...a),
    orderSubmit: async () => ({}),
    catalogueLastOrder: async () => ({}),
    schemesFor: async () => ({ specs: [] }),
  },
  ApiError: class ApiError extends Error {},
}))
vi.mock('../src/sync/outbox', () => ({ enqueue: vi.fn() }))
vi.mock('../src/stores/visit', () => ({ activeVisit: ref(null), recordOrder: vi.fn() }))

const cart = await import('../src/stores/order')
const { db } = await import('../src/db')

const SHOP = 'SHOP-1'

/** One item at ten rupees a piece, a dozen to the box and two dozen to the case. */
function payload({ order_uoms, order_uom = 'Nos', conversion_factor = 1 } = {}) {
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
        stock_uom: 'Nos',
        order_uom,
        conversion_factor,
        order_uoms: order_uoms === undefined
          ? [
              { uom: 'Nos', conversion_factor: 1 },
              { uom: 'Box', conversion_factor: 12 },
              { uom: 'Case', conversion_factor: 24 },
            ]
          : order_uoms,
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

async function aCart(options) {
  catalogue.mockResolvedValue(payload(options))
  await cart.openOutlet(SHOP, { type: null })
  return cart.addItem('SOAP-100', { qty: 5 })
}

function line() {
  return cart.lines.value.find((l) => l.item_code === 'SOAP-100')
}

beforeEach(async () => {
  await db.carts.clear()
  await cart.clear()
  catalogue.mockReset()
})

describe('switching the unit', () => {
  it('keeps the number the rep typed and reinterprets the unit', async () => {
    await aCart()
    expect(line().display_qty).toBe(5)
    expect(line().qty).toBe(5)

    await cart.setUnit('SOAP-100', 'Box')

    expect(line().display_uom).toBe('Box')
    expect(line().display_qty).toBe(5)
    // Five boxes of twelve. The order did just get twelve times bigger, in front of the rep.
    expect(line().qty).toBe(60)
  })

  it('leaves the per-base rate alone and lets the shown rate follow', async () => {
    await aCart()
    expect(line().rate_paise).toBe(1000)
    expect(line().display_rate_paise).toBe(1000)

    await cart.setUnit('SOAP-100', 'Case')

    expect(line().rate_paise).toBe(1000)
    expect(line().display_rate_paise).toBe(24000)
  })

  it('totals the line on base units, so the money follows the quantity', async () => {
    await aCart()
    expect(line().gross_paise).toBe(5 * 1000)

    await cart.setUnit('SOAP-100', 'Box')

    expect(line().gross_paise).toBe(60 * 1000)
  })

  it('switches back down without losing the line', async () => {
    await aCart()
    await cart.setUnit('SOAP-100', 'Case')
    expect(line().qty).toBe(120)

    await cart.setUnit('SOAP-100', 'Nos')

    expect(line().display_uom).toBe('Nos')
    expect(line().qty).toBe(5)
  })

  it('refuses a unit the item does not offer rather than inventing a conversion', async () => {
    // Without a factor from the item master there is no honest number to use, and guessing one
    // is how a case gets booked at a piece price.
    await aCart()
    await cart.setUnit('SOAP-100', 'Tonne')

    expect(line().display_uom).toBe('Nos')
    expect(line().conversion_factor).toBe(1)
    expect(line().qty).toBe(5)
  })

  it('never rounds a line away to nothing', async () => {
    // One case already in the cart, switched to singles: 1/24 of a case rounds to zero, and a
    // rep who picked a unit has not asked to remove the line.
    await aCart({ order_uom: 'Case', conversion_factor: 24 })
    expect(line().qty).toBe(120)
    await cart.setUnit('SOAP-100', 'Nos')
    expect(line().qty).toBe(5)

    await cart.setUnit('SOAP-100', 'Case')
    await cart.setQty('SOAP-100', 1, { unit: 'base' })
    expect(line().qty).toBe(1)

    await cart.setUnit('SOAP-100', 'Case')
    expect(line().qty).toBeGreaterThanOrEqual(1)
  })

  it('keeps the choices through a reload with no signal', async () => {
    // The case this whole design is for: the rep switched to boxes in the morning, the app was
    // killed, and they reopen it in a market with nothing. If the units did not persist the
    // dropdown would quietly become a dead label and they could not switch back.
    await aCart()
    await cart.setUnit('SOAP-100', 'Box')
    expect(line().qty).toBe(60)

    catalogue.mockRejectedValue(new Error('no signal'))
    await cart.openOutlet(SHOP, { type: null })

    expect(line().display_uom).toBe('Box')
    expect(line().qty).toBe(60)
    expect(line().order_uoms.map((u) => u.uom)).toEqual(['Nos', 'Box', 'Case'])
    // And it can still be switched, with nothing on the wire.
    await cart.setUnit('SOAP-100', 'Case')
    expect(line().display_uom).toBe('Case')
  })

  it('falls back to the stock unit when the server sent no choices at all', async () => {
    // An older server, or a payload from before #12. One option is not a dropdown, and the
    // screen shows a plain label instead.
    await aCart({ order_uoms: [] })
    expect(line().order_uoms).toEqual([{ uom: 'Nos', conversion_factor: 1 }])
  })
})
