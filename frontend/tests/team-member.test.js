/**
 * One rep's page on the manager's phone.
 *
 * The server says what the caller may do - edit, cancel, clear a sync jam - and the page draws
 * only those buttons. Pinned here: a button the server would refuse is never shown, a cancel
 * asks why before it goes, and a sync jam offers only the two endings that do what they say.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

function page(over = {}) {
  return {
    profile: { name: 'rep1@x.test', full_name: 'Ravi', designation: 'Field Rep',
               territory: 'Delhi North', status: 'Active', reports_to: 'am@x.test',
               mobile_no: '9800000000', daily_target_calls: 20,
               can_create_outlet: 1, can_collect_payment: 0 },
    can_edit: false, can_cancel_orders: true, can_resolve_conflicts: true, options: null,
    orders: [{ name: 'ORD-1', outlet_name: 'Maruti', order_date: '2026-10-30',
               grand_total: 1200, order_status: 'Sent To Distributor', can_cancel: true }],
    conflicts: [{ name: 'CONF-1', reference_doctype: 'FieldMate Order', creation: '2026-10-30 10:00',
                  resolution_notes: 'Item ABC is not on the price list' }],
    ...over,
  }
}

const api = {
  teamMember: vi.fn(async () => page()),
  teamCancelOrder: vi.fn(async () => ({})),
  teamResolveConflict: vi.fn(async () => ({})),
  teamUpdateMember: vi.fn(async (_, p) => page({ profile: { ...page().profile, ...p } })),
}

vi.mock('../src/api/client', () => ({ ApiError: class extends Error {}, api }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { rep: 'rep1@x.test' } }),
  useRouter: () => ({ replace: () => {} }),
}))

const { default: TeamMember } = await import('../src/screens/TeamMember.vue')

async function open() {
  const w = mount(TeamMember, { global: { stubs: { Icon: true, RouterLink: { template: '<a><slot/></a>' } } } })
  await flushPromises()
  return w
}

beforeEach(() => Object.values(api).forEach((f) => f.mockClear()))

describe("a rep's page", () => {
  it('an area manager is not offered an edit the server would refuse', async () => {
    const w = await open()
    expect(w.text()).not.toContain('Edit')
  })

  it('a cancel asks why, and will not go without an answer', async () => {
    const w = await open()
    await w.find('.order .link.danger').trigger('click')
    await w.find('.order .no').trigger('click')
    await flushPromises()
    expect(api.teamCancelOrder).not.toHaveBeenCalled()

    await w.find('.order textarea').setValue('Shop shut for a month')
    await w.find('.order .no').trigger('click')
    await flushPromises()
    expect(api.teamCancelOrder).toHaveBeenCalledWith('ORD-1', 'Shop shut for a month')
    expect(w.text()).toContain('Cancelled')
  })

  it('a sync jam shows why it failed and offers only the two honest endings', async () => {
    const w = await open()
    const jam = w.find('.jam')
    expect(jam.text()).toContain('not on the price list')
    expect(jam.findAll('button').map((b) => b.text())).toEqual(
      ['Drop what the phone sent', 'Leave it as it is'])
    await jam.findAll('button')[0].trigger('click')
    await flushPromises()
    expect(api.teamResolveConflict).toHaveBeenCalledWith('CONF-1', 'Discarded')
    expect(w.find('.jam').exists()).toBe(false)
  })

  it('a regional manager edits, and only to what the server offered', async () => {
    api.teamMember.mockResolvedValueOnce(page({
      can_edit: true, can_cancel_orders: false, can_resolve_conflicts: false, conflicts: [],
      orders: [{ ...page().orders[0], can_cancel: false }],
      options: { designation: ['Field Rep', 'Area Manager'], status: ['Active', 'Inactive'],
                 territory: ['Delhi North'], distributor: [],
                 reports_to: [{ name: 'rm@x.test', full_name: 'Regional Head' }] },
    }))
    const w = await open()
    expect(w.text()).not.toContain('Cancel this order')
    await w.find('.link').trigger('click')
    const reportsTo = w.findAll('select')[3]
    expect(reportsTo.findAll('option').map((o) => o.text())).toEqual(['Nobody', 'Regional Head'])
    await reportsTo.setValue('rm@x.test')
    await w.find('.form .btn').trigger('click')
    await flushPromises()
    expect(api.teamUpdateMember.mock.calls[0][1]).toMatchObject({ reports_to: 'rm@x.test',
                                                                  can_create_outlet: 1 })
  })
})
