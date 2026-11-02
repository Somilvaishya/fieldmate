/**
 * A manager signing in gets a manager's app.
 *
 * Until this, an Area Manager, a Regional Manager and a Sales Head saw exactly what a rep saw -
 * Today, Shops, Orders, Collect, Me - with nowhere to see their team and nowhere to approve
 * anything. The roles arrived in every `auth.bootstrap`; nothing read them.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const inbox = {
  counts: { outlets: 1, orders: 0, expenses: 1, geo_fence: 0 },
  total: 2,
  outlets: [{ name: 'FM-OUT-1', outlet_name: 'Maruti Store', rep_name: 'Ravi', latitude: 28.6 }],
  orders: [],
  expenses: [{ name: 'FM-EXP-1', rep_name: 'Ravi', claimed_amount: 600, expense_type: 'Travel',
               claim_date: '2026-10-30' }],
  geo_fence: [],
}
let today = { members: [], totals: {} }
const decideOutlet = vi.fn(async () => ({}))
const decideExpense = vi.fn(async () => ({}))

vi.mock('../src/api/client', () => ({
  ApiError: class extends Error {},
  api: {
    teamInbox: async () => JSON.parse(JSON.stringify(inbox)),
    teamToday: async () => { if (today instanceof Error) throw today; return today },
    decideOutlet: (...a) => decideOutlet(...a),
    decideExpense: (...a) => decideExpense(...a),
  },
}))
vi.mock('../src/db', () => ({ getMeta: async () => null, setMeta: vi.fn() }))
vi.mock('../src/sync/auto', () => ({ start: vi.fn(), stop: vi.fn() }))
// The manager's own day, settable per test. `vi.hoisted` because vi.mock factories run before
// the imports above them and cannot reach an ordinary module-level variable.
const day = vi.hoisted(() => ({ open: null, loaded: null }))
vi.mock('../src/stores/day', async () => {
  const { ref } = await import('vue')
  day.open = ref(null)
  day.loaded = ref(true)
  return { ensure: async () => {}, openDay: day.open, loaded: day.loaded }
})
vi.mock('../src/sync/pinger', () => ({ configure: vi.fn() }))
const replace = vi.hoisted(() => ({ fn: null }))
vi.mock('vue-router', async () => {
  const { vi: v } = await import('vitest')
  replace.fn = v.fn()
  return { useRoute: () => ({ name: 'team' }), useRouter: () => ({ replace: replace.fn }) }
})

const role = await import('../src/stores/role')
const { default: App } = await import('../src/App.vue')
const { default: Approvals } = await import('../src/screens/Approvals.vue')
const { default: Team } = await import('../src/screens/Team.vue')

const STUBS = {
  RouterView: true,
  OfflineStrip: true,
  Icon: true,
  RouterLink: { props: ['to'], template: '<a :data-to="to"><slot/></a>' },
}

function tabs() {
  return mount(App, { global: { stubs: STUBS } }).findAll('nav a').map((a) => a.attributes('data-to'))
}

beforeEach(() => {
  role.forget()
  decideOutlet.mockClear()
  decideExpense.mockClear()
})

describe('the bottom bar follows the role', () => {
  it('a rep gets the rep tabs', () => {
    role.remember({ roles: ['FieldMate Field Rep'] })
    expect(tabs()).toEqual(['/today', '/outlets', '/orders', '/money', '/me'])
  })

  for (const r of ['Area Manager', 'Regional Manager', 'Sales Head']) {
    it(`a ${r} gets Team and Approvals`, () => {
      role.remember({ roles: [`FieldMate ${r}`] })
      expect(tabs()).toEqual(['/team', '/approvals', '/plan', '/outlets', '/me'])
    })
  }

  it('home is Team for a manager and Today for a rep', () => {
    role.remember({ roles: ['FieldMate Area Manager'] })
    expect(role.homeRoute.value).toBe('/team')
    role.remember({ roles: ['FieldMate Field Rep'] })
    expect(role.homeRoute.value).toBe('/today')
  })

  it('signing out forgets the role, so the next login does not inherit the tabs', () => {
    role.remember({ roles: ['FieldMate Sales Head'] })
    role.forget()
    expect(role.isManager.value).toBe(false)
  })
})

describe('approving from the phone', () => {
  async function screen() {
    const w = mount(Approvals, { global: { stubs: { Icon: true } } })
    await flushPromises()
    return w
  }

  it('opens on a kind that has something waiting, with the counts on the chips', async () => {
    const w = await screen()
    expect(w.text()).toContain('Maruti Store')
    expect(w.findAll('.chip .count').map((c) => c.text())).toEqual(['1', '1'])
  })

  it('approving takes the row off the list at once', async () => {
    const w = await screen()
    await w.find('.yes').trigger('click')
    await flushPromises()
    expect(decideOutlet).toHaveBeenCalledWith('FM-OUT-1', 'Approved', undefined)
    expect(w.text()).not.toContain('Maruti Store')
  })

  it('a refusal asks why first, and will not go without a reason', async () => {
    const w = await screen()
    await w.find('.ghost').trigger('click')
    await w.find('.no').trigger('click')
    await flushPromises()
    expect(decideOutlet).not.toHaveBeenCalled()
    expect(w.text()).toContain('Say why')

    await w.find('textarea').setValue('Shop is outside our territory')
    await w.find('.no').trigger('click')
    await flushPromises()
    expect(decideOutlet).toHaveBeenCalledWith('FM-OUT-1', 'Rejected', 'Shop is outside our territory')
  })

  it('an expense is approved at the figure the manager typed, not only the claim', async () => {
    const w = await screen()
    const chips = w.findAll('.chip')
    await chips[2].trigger('click')
    await w.find('.amount input').setValue('450')
    await w.find('.yes').trigger('click')
    await flushPromises()
    expect(decideExpense).toHaveBeenCalledWith('FM-EXP-1', 'Approved', 450, undefined)
  })
})

describe('the team board', () => {
  function member(over) {
    return { field_user: 'a@x.test', full_name: 'Somil', territory: 'Delhi North',
             day_status: 'Not Started', visits: 0, planned_calls: 0, productive: 0,
             orders: 0, order_value: 0, ...over }
  }

  async function board(members, totals = {}) {
    today = { members, totals: { members: members.length, started: 0, visits: 0, order_value: 0,
                                 ...totals } }
    const w = mount(Team, { global: { stubs: { Icon: true, RouterLink: { template: '<a><slot/></a>' } } } })
    await flushPromises()
    return w
  }

  // Seen on testerp2: two reps called Somil in Delhi North, two identical cards.
  it('two reps with one name are told apart by their login', async () => {
    const w = await board([member({ field_user: 'rep1@yourco.test' }),
                           member({ field_user: 'test@rep.com' })])
    const text = w.text()
    expect(text).toContain('rep1@yourco.test')
    expect(text).toContain('test@rep.com')
  })

  it('a name nobody shares is not cluttered with a login', async () => {
    const w = await board([member({ field_user: 'rep1@yourco.test', full_name: 'Ravi' }),
                           member({ field_user: 'test@rep.com', full_name: 'Somil' })])
    expect(w.text()).not.toContain('rep1@yourco.test')
  })

  it('order value reads as money, with a rupee sign, even at zero', async () => {
    const w = await board([member({})], { order_value: 0 })
    expect(w.find('.facts').text()).toContain('₹0')
  })
})

describe("the manager's own day", () => {
  async function board() {
    today = { members: [], totals: {} }
    const w = mount(Team, { global: { stubs: { Icon: true,
      RouterLink: { props: ['to'], template: '<a :data-to="to"><slot/></a>' } } } })
    await flushPromises()
    return w
  }

  it('a manager who has not started is offered Day Start, the same screen a rep uses', async () => {
    day.open.value = null
    const w = await board()
    expect(w.find('.myday a').attributes('data-to')).toBe('/day/start')
  })

  it('once started, it says since when and offers Day End', async () => {
    day.open.value = { started_at: '2026-10-31 09:41:12', day_date: '2026-10-31' }
    const w = await board()
    expect(w.find('.myday').text()).toContain('09:41')
    expect(w.find('.myday a').attributes('data-to')).toBe('/day/end')
    day.open.value = null
  })
})

describe('a manager whose session has gone', () => {
  // Seen on testerp2: taking Desk from a manager changes their user type, and Frappe ends every
  // session of a user whose type changes. The next morning the board printed "Please sign in
  // again" with nowhere to do it.
  it('is sent to sign in, not left on a dead screen', async () => {
    const { ApiError } = await import('../src/api/client')
    today = Object.assign(new ApiError('Please sign in again.'), { code: 'AUTH_REQUIRED' })
    replace.fn.mockClear()
    mount(Team, { global: { stubs: { Icon: true, RouterLink: { template: '<a><slot/></a>' } } } })
    await flushPromises()
    expect(replace.fn).toHaveBeenCalledWith('/login')
    today = { members: [], totals: {} }
  })
})
