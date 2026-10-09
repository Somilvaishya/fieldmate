/**
 * The deposit screen, and the cheque it must not call money.
 *
 * A rep hands in the satchel: cash, cheques, the slip number. A **post-dated** cheque goes in with
 * the rest — the office holds it until it falls due — but it is not money, and it was drawn among
 * the ordinary cheques under a heading that said "Cheques in the envelope". Two things went wrong
 * at once: the rep was told to hand in something no bank would take today, and for three weeks
 * afterwards nothing on any screen explained why it had not cleared.
 *
 * It matters more since Phase 2. A season booking is released by money that has **arrived**, so a
 * PDC leaves the booking held — and the rep who collected it is the person being asked by the
 * party when their stock is coming.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const cashInHand = vi.fn()

vi.mock('../src/api/client', () => ({
  api: { cashInHand: () => cashInHand(), depositDeclare: vi.fn() },
  ApiError: class ApiError extends Error {},
}))

vi.mock('../src/db', () => ({ deviceUuid: async () => 'device-1' }))

vi.mock('vue-router', () => ({ useRouter: () => ({ replace: vi.fn() }) }))

const { default: DepositDeclare } = await import('../src/screens/DepositDeclare.vue')

/** One collection as `collection.undeposited` sends it. */
function row(extra = {}) {
  return {
    name: 'FM-COLL-0001',
    receipt_no: 'RC-0001',
    collection_date: '2026-01-14',
    party: 'Mahalaxmi Distributors',
    party_type: 'Distributor',
    mode: 'Cash',
    amount: 5000,
    instrument_no: null,
    instrument_date: null,
    is_pdc: 0,
    posts_to_ledger: 1,
    ...extra,
  }
}

/** A cheque dated ahead of us, as the server marks it. */
function pdc(extra = {}) {
  return row({
    name: 'FM-COLL-0002',
    mode: 'Cheque',
    amount: 10000,
    instrument_no: '884920',
    instrument_date: '2026-03-20',
    is_pdc: 1,
    ...extra,
  })
}

/** A cheque that can be banked today. */
function cheque(extra = {}) {
  return row({
    name: 'FM-COLL-0003',
    mode: 'Cheque',
    amount: 2500,
    instrument_no: '117733',
    instrument_date: '2026-01-10',
    is_pdc: 0,
    ...extra,
  })
}

async function screen(rows, extra = {}) {
  const cash = rows.filter((r) => !['Cheque', 'DD'].includes(r.mode))
  const cheques = rows.filter((r) => ['Cheque', 'DD'].includes(r.mode))
  const sum = (list) => list.reduce((t, r) => t + r.amount, 0)

  cashInHand.mockResolvedValue({
    collections: rows,
    count: rows.length,
    cash_amount: sum(cash),
    cheque_amount: sum(cheques),
    pdc_amount: sum(rows.filter((r) => r.is_pdc)),
    total_amount: sum(rows),
    ours_amount: sum(rows),
    oldest_days: 1,
    is_overdue: false,
    threshold_days: 2,
    ...extra,
  })

  const wrapper = mount(DepositDeclare, { global: { stubs: { Icon: true } } })
  await flushPromises()
  return wrapper
}

// `restoreMocks` in `vitest.config.js` resets these between tests. An explicit `mockReset` in a
// `beforeEach` also makes vitest report a caught rejection as unhandled - see `bookings.test.js`.

describe('a post-dated cheque on the row the rep ticks', () => {
  it('is marked on the row itself, not only in a tally', async () => {
    // The rep ticks these one at a time. This is the one they must not read as cash.
    const w = await screen([pdc()])
    expect(w.text()).toContain('not bankable yet')
  })

  it('says the date it falls due', async () => {
    const w = await screen([pdc()])
    expect(w.text()).toContain('2026-03-20')
  })

  it('leaves an ordinary cheque unmarked', async () => {
    const w = await screen([cheque()])
    expect(w.text()).not.toContain('not bankable yet')
  })

  it('leaves cash unmarked', async () => {
    const w = await screen([row()])
    expect(w.text()).not.toContain('not bankable yet')
  })
})

describe('the envelope, split', () => {
  it('lists post-dated cheques in their own block', async () => {
    const w = await screen([pdc()])
    expect(w.text()).toContain('Post-dated cheques')
  })

  it('keeps a bankable cheque out of that block', async () => {
    const w = await screen([cheque()])
    expect(w.text()).toContain('Cheques in the envelope')
    expect(w.text()).not.toContain('Post-dated cheques')
  })

  it('says what the office does with one, so the rep still hands it in', async () => {
    // A rep who thinks a PDC is useless keeps it in the satchel, and then nobody has it at all.
    const w = await screen([pdc()])
    expect(w.text()).toContain('Hand these in')
    expect(w.text()).toContain('until its date')
  })

  it('says no booking is released by one', async () => {
    // The connection to Phase 2, in the words of the person collecting the money.
    const w = await screen([pdc()])
    expect(w.text()).toContain('no booking is released')
  })
})

describe('the figures at the top', () => {
  it('shows the post-dated amount as part of the cheque figure', async () => {
    const w = await screen([row(), pdc(), cheque()])
    expect(w.text()).toContain('Post-dated')
    // 10,000 of PDC inside 12,500 of cheques, inside 17,500 in hand.
    expect(w.text()).toContain('10,000')
    expect(w.text()).toContain('12,500')
    expect(w.text()).toContain('17,500')
  })

  it('leaves the column out when nothing is post-dated', async () => {
    // A zero post-dated tile is a claim about the satchel rather than a fact about it.
    const w = await screen([row(), cheque()])
    expect(w.text()).not.toContain('Post-dated')
  })

  it('says how much of the declaration will not clear yet', async () => {
    const w = await screen([row(), pdc()])
    expect(w.text()).toContain('post-dated and will not clear yet')
  })

  it('says nothing of the kind on an all-cash deposit', async () => {
    const w = await screen([row()])
    expect(w.text()).not.toContain('will not clear yet')
  })
})
