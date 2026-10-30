/**
 * The Plan tab: building and approving a rep's month, and shaping a beat, from the phone.
 *
 * The route maths is the server's (`journey.build_days`). What is pinned here is what the
 * manager is shown before they approve, and what the beat screen sends.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

let params = {}
let query = {}
const replace = vi.fn()

const draft = {
  name: 'FM-JP-1', state: 'Draft', working_days: 2, planned_days: 1, planned_visits: 12, gaps: 1,
  can_cancel: false,
  days: [
    { plan_date: '2026-11-02', day_of_week: 'Monday', is_working_day: 1, status: 'Planned',
      beat: 'FM-BEAT-1', beat_name: 'Rohini Monday', outlet_count: 12 },
    { plan_date: '2026-11-03', day_of_week: 'Tuesday', is_working_day: 1, status: 'Planned',
      beat: null, outlet_count: 0 },
    { plan_date: '2026-11-08', day_of_week: 'Sunday', is_working_day: 0, status: 'Holiday',
      beat: null, outlet_count: 0 },
  ],
}
const overview = (plan) => ({ members: [{ field_user: 'rep1@x.test', full_name: 'Ravi',
                                         territory: 'Delhi North', beats: 1, plan }] })

const api = {
  planOverview: vi.fn(async () => overview(null)),
  planDays: vi.fn(async () => draft),
  planBuild: vi.fn(async () => draft),
  planApprove: vi.fn(async () => ({ ...draft, state: 'Approved' })),
  planBeat: vi.fn(async () => ({
    name: 'FM-BEAT-1', beat_name: 'Rohini Monday', assigned_to: 'rep1@x.test',
    territory: 'Delhi North', visit_day: 'Monday', frequency: 'Weekly', week_pattern: 'All',
    is_active: 1,
    outlets: [{ outlet: 'O-1', outlet_name: 'Maruti' }, { outlet: 'O-2', outlet_name: 'Laxmi' }],
  })),
  planFreeOutlets: vi.fn(async () => ({ outlets: [] })),
  planSaveBeat: vi.fn(async (p) => p),
  planHolidayLists: vi.fn(async () => ({ default: 'Delhi 2026', options: ['Delhi 2026'] })),
  planBeatOptions: vi.fn(async () => ({
    territories: ['Delhi North', 'Rohini'], default_territory: 'Delhi North',
    distributors: [{ name: 'CUST-1', customer_name: 'Sharma Traders' }],
  })),
}

vi.mock('../src/api/client', () => ({ ApiError: class extends Error {}, api }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params, query }),
  useRouter: () => ({ replace }),
}))

const { default: PlanRep } = await import('../src/screens/PlanRep.vue')
const { default: BeatEdit } = await import('../src/screens/BeatEdit.vue')

const STUBS = { Icon: true, RouterLink: { template: '<a><slot/></a>' } }

async function open(component) {
  const w = mount(component, { global: { stubs: STUBS } })
  await flushPromises()
  return w
}

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockClear())
  replace.mockClear()
})

describe("a rep's month", () => {
  beforeEach(() => { params = { rep: 'rep1@x.test' }; query = { month: '2026-11-01' } })

  it("with no plan, offers the month and the rep's own holiday list to build from", async () => {
    const w = await open(PlanRep)
    const [from, to] = w.findAll('input[type="date"]')
    expect(from.element.value).toBe('2026-11-01')
    expect(to.element.value).toBe('2026-11-30')
    expect(w.find('select').element.value).toBe('Delhi 2026')

    await w.find('.form .btn').trigger('click')
    await flushPromises()
    expect(api.planBuild).toHaveBeenCalledWith('rep1@x.test', {
      fromDate: '2026-11-01', toDate: '2026-11-30', holidayList: 'Delhi 2026' })
    expect(w.text()).toContain('Rohini Monday')
  })

  it('builds over whatever range the manager picks', async () => {
    const w = await open(PlanRep)
    const [from, to] = w.findAll('input[type="date"]')
    await from.setValue('2026-11-10')
    await to.setValue('2026-11-20')
    await w.find('select').setValue('')
    await w.find('.form .btn').trigger('click')
    await flushPromises()
    expect(api.planBuild).toHaveBeenCalledWith('rep1@x.test', {
      fromDate: '2026-11-10', toDate: '2026-11-20', holidayList: undefined })
  })

  it('a reversed range is refused before anything is sent', async () => {
    const w = await open(PlanRep)
    const [from, to] = w.findAll('input[type="date"]')
    await from.setValue('2026-11-20')
    await to.setValue('2026-11-10')
    await w.find('.form .btn').trigger('click')
    await flushPromises()
    expect(api.planBuild).not.toHaveBeenCalled()
    expect(w.text()).toContain('To date is before from date')
  })

  it('shows a working day with no beat as a hole, before anything is approved', async () => {
    api.planOverview.mockResolvedValueOnce(overview({ name: 'FM-JP-1', state: 'Draft' }))
    const w = await open(PlanRep)
    expect(w.findAll('li.hole')).toHaveLength(1)
    expect(w.text()).toContain('1 working day has no beat')
  })

  it('a holiday is a day off, not a hole', async () => {
    api.planOverview.mockResolvedValueOnce(overview({ name: 'FM-JP-1', state: 'Draft' }))
    const w = await open(PlanRep)
    expect(w.findAll('li.off')).toHaveLength(1)
    expect(w.find('li.off').text()).toContain('Holiday')
  })

  it('approving sends the draft and says it is on their phone', async () => {
    api.planOverview.mockResolvedValueOnce(overview({ name: 'FM-JP-1', state: 'Draft' }))
    const w = await open(PlanRep)
    await w.find('.actions .btn').trigger('click')
    await flushPromises()
    expect(api.planApprove).toHaveBeenCalledWith('FM-JP-1')
    expect(w.text()).toContain('on their phone')
  })

  it('an area manager is not offered a withdraw they cannot do', async () => {
    api.planOverview.mockResolvedValueOnce(overview({ name: 'FM-JP-1', state: 'Approved' }))
    api.planDays.mockResolvedValueOnce({ ...draft, state: 'Approved', can_cancel: false })
    const w = await open(PlanRep)
    expect(w.text()).not.toContain('Withdraw')
  })
})

describe('a beat', () => {
  beforeEach(() => { params = { name: 'FM-BEAT-1' }; query = {} })

  it('sends the shops in the order the manager left them', async () => {
    const w = await open(BeatEdit)
    // Laxmi up above Maruti.
    await w.findAll('.shops li')[1].findAll('.mini')[0].trigger('click')
    await w.find('.btn').trigger('click')
    await flushPromises()
    expect(api.planSaveBeat.mock.calls[0][0].outlets).toEqual(['O-2', 'O-1'])
  })

  it('a weekly beat never sends a week pattern', async () => {
    const w = await open(BeatEdit)
    await w.find('.btn').trigger('click')
    await flushPromises()
    expect(api.planSaveBeat.mock.calls[0][0].week_pattern).toBe('All')
  })

  it('removing a shop takes it off what is sent', async () => {
    const w = await open(BeatEdit)
    await w.findAll('.shops li')[0].findAll('.mini')[1].trigger('click')
    await w.find('.btn').trigger('click')
    await flushPromises()
    expect(api.planSaveBeat.mock.calls[0][0].outlets).toEqual(['O-2'])
  })
})

describe('what a beat is set to', () => {
  beforeEach(() => { params = { name: 'FM-BEAT-1' }; query = {} })

  it("offers only the territories and distributors the server allows for this rep", async () => {
    const w = await open(BeatEdit)
    expect(api.planBeatOptions).toHaveBeenCalledWith('rep1@x.test')
    const [, territory, distributor] = w.findAll('select')
    expect(territory.findAll('option').map((o) => o.text()).slice(1)).toEqual(['Delhi North', 'Rohini'])
    expect(distributor.text()).toContain('Sharma Traders')
  })

  it('sends the territory, distributor, start date and notes the manager chose', async () => {
    const w = await open(BeatEdit)
    const [, territory, distributor] = w.findAll('select')
    await territory.setValue('Rohini')
    await distributor.setValue('CUST-1')
    await w.find('input[type="date"]').setValue('2026-12-01')
    await w.find('.field textarea').setValue('Start from the chowk')
    await w.find('.btn').trigger('click')
    await flushPromises()
    const sent = api.planSaveBeat.mock.calls[0][0]
    expect(sent).toMatchObject({ territory: 'Rohini', distributor: 'CUST-1',
                                 effective_from: '2026-12-01', notes: 'Start from the chowk' })
  })

  it('a new beat with no name is stopped on the phone', async () => {
    params = { name: 'new' }
    query = { rep: 'rep1@x.test' }
    const w = await open(BeatEdit)
    await w.find('.btn').trigger('click')
    await flushPromises()
    expect(api.planSaveBeat).not.toHaveBeenCalled()
    expect(w.text()).toContain('A beat needs a name, a rep and a territory')
  })
})
