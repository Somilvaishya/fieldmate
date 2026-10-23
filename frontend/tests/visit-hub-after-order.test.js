/**
 * The visit hub after the rep has done the work.
 *
 * Reported from the field as two separate complaints and they are the same shape: "visited a shop,
 * created an order, came back to the shop - *What to do here* still says the order is not done",
 * and the same for the stock count.
 *
 * The hub reads three different sources for those three rows, which is why one can be right while
 * another is wrong:
 *
 *   - the **order** row reads `visit.order`, written by `visitStore.recordOrder` when the cart is
 *     submitted. The cart is emptied on submit, so without that write the row would go back to
 *     reading "None yet" thirty seconds after the rep booked one.
 *   - the **shelf** and **stock** rows read `visit.tasks`, the four rows the server creates at
 *     check-in (Merchandising, Stock Audit, Collection, Order). A screen that saves its work has
 *     to flip its own row to Done.
 *
 * So these drive the **real** visit store and the **real** order store against a real (in-memory)
 * IndexedDB. Only the network is mocked. Both halves are asserted twice: once in memory, and once
 * after `resume()` has read the visit back off the handset, because a rep reopening the app is the
 * case that matters and the one a memory-only assertion would miss.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const catalogue = vi.fn()
const orderSubmit = vi.fn()
const saveVisitTasks = vi.fn()
const enqueued = vi.fn()

vi.mock('../src/api/client', () => ({
  api: {
    catalogue: (...a) => catalogue(...a),
    orderSubmit: (...a) => orderSubmit(...a),
    saveVisitTasks: (...a) => saveVisitTasks(...a),
    catalogueLastOrder: async () => ({}),
    schemesFor: async () => ({ specs: [] }),
    currentVisit: async () => ({ open: true, visit: 'FM-VIS-000234' }),
  },
  ApiError: class ApiError extends Error {
    constructor(code, message) { super(message); this.code = code }
  },
}))
vi.mock('../src/sync/outbox', () => ({ enqueue: (...a) => enqueued(...a) }))
vi.mock('../src/sync/photos', () => ({ pendingCount: async () => 0 }))
vi.mock('../src/sync/pinger', () => ({ flushSoon: async () => {} }))
vi.mock('../src/stores/day', () => ({ openDay: { value: { day: 'FM-DAY-1' } } }))

const { ApiError } = await import('../src/api/client')
const visitStore = await import('../src/stores/visit')
const cart = await import('../src/stores/order')
const { db } = await import('../src/db')

const SHOP = 'FM-OUT-05814'

/** The four rows the server hands back on check-in, as `services/visit.py` builds them. */
function serverTasks() {
  return [
    { task: 'Check the shelf', task_type: 'Merchandising', status: 'Pending' },
    { task: 'Count his stock', task_type: 'Stock Audit', status: 'Pending' },
    { task: 'Collect what is due', task_type: 'Collection', status: 'Pending' },
    { task: 'Take the order', task_type: 'Order', status: 'Pending' },
  ]
}

/** A rep standing in the shop with the visit open, exactly as check-in leaves it. */
async function standingInTheShop() {
  const visit = {
    clientUuid: 'visit-1',
    serverName: 'FM-VIS-000234',
    day: 'FM-DAY-1',
    outlet: SHOP,
    outletName: 'Nagpal Complex',
    state: 'open',
    checkInTime: '2026-10-23 10:15:00',
    checklist: [],
    tasks: serverTasks(),
    remarks: '',
    outcome: null,
  }
  await db.visits.put(visit)
  visitStore.activeVisit.value = visit
  return visit
}

function payload() {
  return {
    outlet: SHOP,
    outlet_name: 'Nagpal Complex',
    price_list: 'Standard Selling',
    currency: 'INR',
    company: 'test',
    items: [{
      item_code: 'AL-21', item_name: 'Almond California',
      rate: 1100, uom: 'Kg', stock_uom: 'Kg', display_uom: 'Kg',
      conversion_factor: 1, unpriceable: false, above_mrp: false,
      sort_order: 1, currency: 'INR', tax_bps: 0,
    }],
    last_order: {},
  }
}

async function aCartWithSomethingInIt() {
  catalogue.mockResolvedValue(payload())
  await cart.openOutlet(SHOP, { type: null })
  await cart.addItem('AL-21', { qty: 2 })
  expect(cart.isEmpty.value).toBe(false)
}

/** What the hub does on mount: it reads the visit back off the handset. */
async function reopenTheApp() {
  visitStore.activeVisit.value = null
  return visitStore.resume()
}

beforeEach(async () => {
  await db.carts.clear()
  await db.visits.clear()
  await cart.clear()
  visitStore.activeVisit.value = null
  catalogue.mockReset()
  orderSubmit.mockReset()
  enqueued.mockReset()
  saveVisitTasks.mockReset()
  saveVisitTasks.mockResolvedValue({})
})

describe('an order booked during a visit', () => {
  it('is on the visit the moment it is sent', async () => {
    await standingInTheShop()
    await aCartWithSomethingInIt()
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000001' })

    await cart.submit()

    // This is what the hub's Order row reads. Empty here is the field complaint.
    expect(visitStore.activeVisit.value.order).toBeTruthy()
    expect(visitStore.activeVisit.value.order.name).toBe('FM-ORD-000001')
    expect(visitStore.activeVisit.value.order.offline).toBe(false)
  })

  it('is still there after the rep reopens the app', async () => {
    await standingInTheShop()
    await aCartWithSomethingInIt()
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000001' })
    await cart.submit()

    const back = await reopenTheApp()

    expect(back).toBeTruthy()
    expect(back.order?.name).toBe('FM-ORD-000001')
  })

  it('is on the visit even when it only reached the outbox', async () => {
    // Offline is the majority path, and the order has no server name at all - so the hub has to
    // read the booking off the visit rather than off a name it will not have for hours.
    await standingInTheShop()
    await aCartWithSomethingInIt()
    // Only an ApiError with this code falls through to the outbox - `isOffline` checks the type,
    // because a validation failure must stay on the screen for the rep to fix.
    orderSubmit.mockRejectedValue(new ApiError('OFFLINE', 'No signal.'))

    const result = await cart.submit()

    expect(result.offline).toBe(true)
    expect(visitStore.activeVisit.value.order).toBeTruthy()
    expect(visitStore.activeVisit.value.order.offline).toBe(true)
  })

  it('marks the visit\'s own Order row done, not just the hub card', async () => {
    // The server creates an `Order` task at check-in and nothing ever flipped it, so a visit the
    // rep took an order in closed with that row still Pending - and the check-out screen asks for
    // an outcome the app already knows.
    await standingInTheShop()
    await aCartWithSomethingInIt()
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000001' })

    await cart.submit()

    const row = visitStore.activeVisit.value.tasks.find((t) => t.task_type === 'Order')
    expect(row?.status).toBe('Done')
  })
})

describe('an order booked after the app has been reloaded mid-flow', () => {
  /**
   * The reported bug, and the only version of it that reproduces.
   *
   * `activeVisit` is a module ref, so it lives for as long as the page does. The visit screens all
   * call `resume()` on mount and read the open visit back off the handset; **the order screens and
   * the stock count did not**. Launching the installed app from its home-screen icon is a fresh
   * page load, and so is a service-worker update or Android reclaiming the tab - so a rep who
   * checked in, left the app on the catalogue, and came back to punch the order was submitting
   * with no open visit in memory at all.
   *
   * Two things went wrong at once, and the second is the one the rep saw:
   *   - the order reached the server with **no visit on it**, so it counted towards no call;
   *   - `recordOrder` returned early, so the hub's Order row still read "None yet" over an order
   *     the rep had just taken.
   */
  async function asIfTheAppWasReloaded() {
    // The visit is on the handset, exactly as check-in left it. Memory is empty.
    const visit = await standingInTheShop()
    visitStore.activeVisit.value = null
    return visit
  }

  it('still lands on the visit', async () => {
    await asIfTheAppWasReloaded()
    await aCartWithSomethingInIt()
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000001' })

    await cart.submit()

    expect(visitStore.activeVisit.value?.order?.name).toBe('FM-ORD-000001')
  })

  it('reaches the server with the visit on it', async () => {
    // Worse than the pill, and invisible: an order with no visit counts towards no call, so
    // coverage and strike rate quietly undercount the rep's day.
    await asIfTheAppWasReloaded()
    await aCartWithSomethingInIt()
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000001' })

    await cart.submit()

    const [, doc] = orderSubmit.mock.calls[0]
    expect(doc.visit).toBe('FM-VIS-000234')
  })

  it('marks the visit\'s Order row done as well', async () => {
    await asIfTheAppWasReloaded()
    await aCartWithSomethingInIt()
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000001' })

    await cart.submit()

    const row = visitStore.activeVisit.value.tasks.find((t) => t.task_type === 'Order')
    expect(row?.status).toBe('Done')
  })

  it('leaves a shop order alone when there is genuinely no visit', async () => {
    // A rep can order from the Shops tab without checking in. That must stay possible, and the
    // order must not invent a visit to hang itself on.
    await db.visits.clear()
    visitStore.activeVisit.value = null
    await aCartWithSomethingInIt()
    orderSubmit.mockResolvedValue({ order: 'FM-ORD-000002' })

    await cart.submit()

    const [, doc] = orderSubmit.mock.calls[0]
    expect(doc.visit).toBeNull()
    expect(visitStore.activeVisit.value).toBeNull()
  })
})

describe('a stock count saved during a visit', () => {
  it('marks the Stock Audit row done', async () => {
    // The field complaint: the count saves, the rep comes back, and the hub still says "None yet".
    // `StockCheck.vue` saved to the server and told the visit nothing.
    await standingInTheShop()

    await visitStore.markTask('Stock Audit')

    const row = visitStore.activeVisit.value.tasks.find((t) => t.task_type === 'Stock Audit')
    expect(row?.status).toBe('Done')
  })

  it('survives the app being reopened', async () => {
    await standingInTheShop()
    await visitStore.markTask('Stock Audit')

    const back = await reopenTheApp()

    expect(back.tasks.find((t) => t.task_type === 'Stock Audit')?.status).toBe('Done')
  })

  it('leaves the other rows alone', async () => {
    await standingInTheShop()
    await visitStore.markTask('Stock Audit')

    const others = visitStore.activeVisit.value.tasks
      .filter((t) => t.task_type !== 'Stock Audit')
      .map((t) => t.status)
    expect(others).toEqual(['Pending', 'Pending', 'Pending'])
  })

  it('says nothing and throws nothing when the row is not there', async () => {
    // A visit created offline has no tasks at all until the server answers. Marking one must not
    // take the save down with it - the count is the work, the row is the bookkeeping.
    const visit = await standingInTheShop()
    visit.tasks = []

    await expect(visitStore.markTask('Stock Audit')).resolves.not.toThrow()
  })
})
