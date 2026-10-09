/**
 * The review screen, for an order **we** invoice — a primary order, or a booking of a season.
 *
 * Two things were wrong here and both were sentences, which is why no Python test could see them.
 *
 * **It said the distributor bills the shop, over every order.** ADR-023 is about a *retailer*
 * order: a secondary sale the distributor delivers out of their own stock and invoices themselves.
 * A primary order and a season booking are sales we raise and we invoice, and this screen told the
 * rep otherwise in three places — the note above the button, the button, and the confirmation
 * afterwards. A rep reading that out to a distributor is telling them somebody else will bill
 * them.
 *
 * **A booking carries three promises and the screen made none of them.** The rates are held at
 * today's, an advance has to be collected before anything is reserved, and every line is
 * delivered inside the season's window. The server enforces all three; the rep had no way to know
 * any of them before submit, and would find out when the order came back refused.
 *
 * The delivery window is the clearest case. `check_delivery_dates` throws on the **first** line it
 * meets, naming one item — so a rep fixes that one, sends again, and is told about the next. On a
 * market uplink, at a counter. This screen names all of them at once and will not send until they
 * are inside.
 */
import { describe, it, expect, vi, beforeAll } from 'vitest'
import { ref, computed } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'

// ----------------------------------------------------------------------------- the cart, faked
//
// The store is mocked rather than driven, because these tests are about the screen's words and its
// gate. What the store computes has its own tests.

const state = {
  outlet: ref('MAHALAXMI'),
  outletName: ref('Mahalaxmi Distributors'),
  loading: ref(false),
  catalogue: ref({ price_list: 'Holi 2026 - Selling', currency: 'INR' }),
  orderKind: ref('Booking'),
  season: ref({
    name: 'FM-SEASON-0001',
    season_name: 'Holi 2026',
    advance_pct: 25,
    delivery_from: '2026-02-20',
    delivery_to: '2026-03-10',
    may_change: true,
    change_note: '',
  }),
  rawLines: ref([
    { item_code: 'SOAP-100', item_name: 'Toilet soap 100g' },
    { item_code: 'SOAP-250', item_name: 'Toilet soap 250g' },
  ]),
}

const submitted = vi.fn()

vi.mock('../src/stores/order', () => ({
  outlet: state.outlet,
  outletName: state.outletName,
  loading: state.loading,
  catalogue: state.catalogue,
  orderKind: state.orderKind,
  season: state.season,
  lines: computed(() =>
    state.rawLines.value.map((l) => ({
      ...l,
      qty: 10,
      conversion_factor: 1,
      base_uom: 'Nos',
      display_uom: 'Nos',
      display_whole: null,
      display_remainder: 0,
      gross: '1,000.00',
      display_rate: '100.00',
      unpriceable: false,
    }))
  ),
  lineCount: computed(() => state.rawLines.value.length),
  baseUnitCount: computed(() => 20),
  isEmpty: computed(() => state.rawLines.value.length === 0),
  totals: computed(() => ({
    net_paise: 4000000,
    tax_paise: 720000,
    discount_paise: 0,
    net: '40,000.00',
    tax: '7,200.00',
    grand: '47,200.00',
    gross: '40,000.00',
    discount: '0.00',
    currency: 'INR',
  })),
  freeGoods: computed(() => []),
  blockers: computed(() => []),
  catalogueItems: computed(() => []),
  openOutlet: vi.fn(),
  verifyWithServer: vi.fn(async () => null),
  submit: (...args) => submitted(...args),
}))

vi.mock('../src/stores/visit', () => ({
  activeVisit: ref(null),
  recordOrder: vi.fn(),
}))

vi.mock('../src/sync/outbox', () => ({ pendingCount: async () => 0 }))

vi.mock('../src/db', () => ({
  db: { records: { get: async () => null } },
  getMeta: async () => ({ distributors: [] }),
  setMeta: async () => {},
}))

vi.mock('../src/api/client', () => ({
  api: { outlet: async () => ({ outlet: {}, credit: null }) },
  ApiError: class ApiError extends Error {},
}))

const replace = vi.fn()
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { outlet: 'MAHALAXMI' }, query: { party: 'Customer' } }),
  useRouter: () => ({ replace, push: vi.fn() }),
}))

let Review
beforeAll(async () => {
  Review = (await import('../src/screens/OrderReview.vue')).default
})

async function screen() {
  const wrapper = mount(Review, {
    global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
  })
  await flushPromises()
  await flushPromises()
  return wrapper
}

function asBooking() {
  state.orderKind.value = 'Booking'
  state.season.value = {
    name: 'FM-SEASON-0001',
    season_name: 'Holi 2026',
    advance_pct: 25,
    delivery_from: '2026-02-20',
    delivery_to: '2026-03-10',
    may_change: true,
    change_note: '',
  }
}

function asPrimary() {
  state.orderKind.value = 'Primary'
  state.season.value = null
}

function asRetailer() {
  state.orderKind.value = 'Secondary'
  state.season.value = null
}

describe('a booking says what was promised at the counter', () => {
  it('names the season it books', async () => {
    asBooking()
    const w = await screen()
    expect(w.text()).toContain('Holi 2026')
  })

  it('says the rates are held and will not be repriced', async () => {
    asBooking()
    const w = await screen()
    expect(w.text()).toContain('held for this season')
    expect(w.text()).toContain('not repriced')
  })

  it('says what advance has to be collected, to the rupee', async () => {
    // 25% of 40,000.00. The rep has to say this figure out loud before the party agrees.
    asBooking()
    const w = await screen()
    expect(w.text()).toContain('Advance to collect')
    expect(w.text()).toContain('10,000.00')
  })

  it('says nothing is reserved until the advance is in hand', async () => {
    asBooking()
    const w = await screen()
    expect(w.text()).toContain('Nothing is reserved or dispatched')
  })

  it('warns that a cheque dated later does not count', async () => {
    // Which is the single most expensive misunderstanding available here: the rep takes a PDC,
    // tells the party the stock is coming, and nothing is reserved for three weeks.
    asBooking()
    const w = await screen()
    expect(w.text()).toContain('dated later does not count')
  })

  it('says the delivery window', async () => {
    asBooking()
    const w = await screen()
    expect(w.text()).toContain('2026-02-20')
    expect(w.text()).toContain('2026-03-10')
  })

  it('says so when the season has closed for changes', async () => {
    asBooking()
    state.season.value = {
      ...state.season.value,
      may_change: false,
      change_note: 'Holi 2026 closed for changes on 25-01-2026.',
    }
    const w = await screen()
    expect(w.text()).toContain('closed for changes')
  })

  it('shows none of it on an ordinary shop order', async () => {
    asRetailer()
    const w = await screen()
    expect(w.text()).not.toContain('Advance to collect')
    expect(w.text()).not.toContain('held for this season')
  })
})

describe('the delivery date', () => {
  it('defaults to the first day the season delivers', async () => {
    asBooking()
    const w = await screen()
    expect(w.find('#booking-date').element.value).toBe('2026-02-20')
  })

  it('bounds the input by the window, so the picker cannot offer a bad date', async () => {
    asBooking()
    const w = await screen()
    const input = w.find('#booking-date')
    expect(input.attributes('min')).toBe('2026-02-20')
    expect(input.attributes('max')).toBe('2026-03-10')
  })

  it('names every line outside the window, not just the first', async () => {
    // The server throws on the first one it meets. A rep reading that fixes it, sends again, and
    // is told about the next - at a counter, on a market uplink.
    //
    // Driven by narrowing the season rather than by typing an impossible date, because happy-dom
    // refuses a value outside a date input's `min`/`max` and answers `''`. A real browser does
    // not - `min` and `max` only make a value *invalid* there, which is exactly why this guard
    // exists. Narrowing the window is also a real case: `season` comes off the catalogue payload,
    // so a rep holding a cart when the office corrects the master gets the new window and must be
    // refused rather than left to send dates the server will reject.
    asBooking()
    const w = await screen()
    await w.findAll('.when input')[1].setValue('2026-03-05')
    state.season.value = { ...state.season.value, delivery_to: '2026-02-28' }
    await flushPromises()

    expect(w.text()).toContain('Toilet soap 250g')
    expect(w.text()).toContain('outside this season')
  })

  it('will not send while a line is outside the window', async () => {
    asBooking()
    const w = await screen()
    await w.findAll('.when input')[1].setValue('2026-03-05')
    state.season.value = { ...state.season.value, delivery_to: '2026-02-28' }
    // Read back and agreed, which is the only other gate.
    await w.find('.attest input').setValue(true)
    await flushPromises()
    expect(w.find('.bottom .btn-primary').attributes('disabled')).toBeDefined()
  })

  it('sends once every line is back inside the window', async () => {
    // The gate lets go of its own accord. A screen that stayed refused after the rep fixed it
    // would be a screen they stop trusting.
    asBooking()
    const w = await screen()
    await w.find('.attest input').setValue(true)
    await flushPromises()
    expect(w.find('.bottom .btn-primary').attributes('disabled')).toBeUndefined()
  })

  it('offers no date at all on an ordinary shop order', async () => {
    asRetailer()
    const w = await screen()
    expect(w.find('#booking-date').exists()).toBe(false)
    expect(w.findAll('.when input')).toHaveLength(0)
  })

  it('sends one date per line when the rep set them', async () => {
    asBooking()
    const w = await screen()
    submitted.mockResolvedValue({ order: 'FM-ORD-1', offline: false, server: {} })
    await w.findAll('.when input')[1].setValue('2026-03-05')
    await w.find('.attest input').setValue(true)
    await w.find('.bottom .btn-primary').trigger('click')
    await flushPromises()

    const sent = submitted.mock.calls.at(-1)[0]
    expect(sent.deliveryDates).toEqual({
      'SOAP-100': '2026-02-20',
      'SOAP-250': '2026-03-05',
    })
  })

  it('sends no dates on an ordinary shop order', async () => {
    asRetailer()
    const w = await screen()
    submitted.mockResolvedValue({ order: 'FM-ORD-2', offline: false, server: {} })
    await w.find('.attest input').setValue(true)
    await w.find('.bottom .btn-primary').trigger('click')
    await flushPromises()
    expect(submitted.mock.calls.at(-1)[0].deliveryDates).toBeNull()
  })
})

describe('who actually bills this order', () => {
  it('does not tell a distributor somebody else will bill them', async () => {
    // The bug, in the one place a rep cannot miss it. ADR-023 is about a *retailer* order.
    asPrimary()
    const w = await screen()
    expect(w.text()).not.toContain('they bill the shop')
    expect(w.text()).toContain('a sale we invoice')
  })

  it('still says it on a retailer order, where it is true', async () => {
    asRetailer()
    const w = await screen()
    expect(w.text()).toContain('they bill the shop')
  })

  it('names the booking and the party rather than a queue', async () => {
    asBooking()
    const w = await screen()
    expect(w.text()).toContain('We raise the order and we invoice it')
  })

  it('labels the button for what it does', async () => {
    asBooking()
    const w = await screen()
    expect(w.find('.bottom .btn-primary').text()).toContain('Book Holi 2026')
  })

  it('labels it for the office on a plain primary order', async () => {
    asPrimary()
    const w = await screen()
    expect(w.find('.bottom .btn-primary').text()).toContain('Send to the office')
  })

  it('still says "distributor" on a retailer order', async () => {
    asRetailer()
    const w = await screen()
    expect(w.find('.bottom .btn-primary').text()).toContain('Send to distributor')
  })

  it('asks what the party pays, not what the shop pays', async () => {
    asPrimary()
    const w = await screen()
    expect(w.text()).toContain('What the party pays')
  })
})

describe('after it is booked', () => {
  async function send(server) {
    asBooking()
    const w = await screen()
    submitted.mockResolvedValue({ order: 'FM-ORD-000204', offline: false, server })
    await w.find('.attest input').setValue(true)
    await w.find('.bottom .btn-primary').trigger('click')
    await flushPromises()
    return w
  }

  it('says it is booked, not sent to a distributor', async () => {
    const w = await send({ name: 'FM-ORD-000204', order_status: 'Awaiting Advance' })
    expect(w.text()).toContain('Booked')
    expect(w.text()).not.toContain('Sent to the distributor')
  })

  it('leaves the counter with the one number that matters', async () => {
    const w = await send({
      name: 'FM-ORD-000204',
      order_status: 'Awaiting Advance',
      advance: { required: 10000, in_hand: 0, short: 10000, held: true, pdc_total: 0 },
    })
    expect(w.text()).toContain('Collect')
    expect(w.text()).toContain('10,000.00')
  })

  it('says nothing is reserved while it is held', async () => {
    const w = await send({
      name: 'FM-ORD-000204',
      order_status: 'Awaiting Advance',
      advance: { required: 10000, in_hand: 0, short: 10000, held: true, pdc_total: 0 },
    })
    expect(w.text()).toContain('Nothing is reserved or dispatched')
  })

  it('says it goes forward once the advance is in', async () => {
    const w = await send({
      name: 'FM-ORD-000204',
      order_status: 'Approved',
      advance: { required: 10000, in_hand: 10000, short: 0, held: false, pdc_total: 0 },
    })
    expect(w.text()).toContain('goes forward to be planned')
  })
})
