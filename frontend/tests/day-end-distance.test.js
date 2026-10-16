/**
 * What the day end screen says the distance figure *is*.
 *
 * The app only reports its position while it is open. A rep who worked a full beat with the
 * phone in a pocket has no trail, so the server now measures the route instead - day start,
 * then each shop that was actually visited.
 *
 * **The trap this pins.** Both figures land in the same `distance_km`, and this screen captioned
 * it "from your GPS trail" unconditionally, with "Your GPS trail recorded N km today" sitting
 * directly above the odometer box. A route figure under that caption tells the rep a trail
 * exists, invites them to reconcile their odometer against it, and is read again by the manager
 * approving the travel claim. The number may be right; the sentence about it was not.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const daySummary = vi.fn()

vi.mock('../src/api/client', () => ({
  api: { daySummary: (...a) => daySummary(...a) },
  ApiError: class ApiError extends Error {},
}))
vi.mock('../src/lib/geo', () => ({ getPosition: async () => ({}) }))
vi.mock('../src/sync/outbox', () => ({ pendingCount: async () => 0 }))
vi.mock('../src/sync/pinger', () => ({ pendingPings: async () => 0 }))
vi.mock('../src/sync/photos', () => ({ pendingCount: async () => 0 }))
vi.mock('../src/stores/day', () => ({ openDay: { value: null }, endDay: vi.fn(), refresh: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: vi.fn(), back: vi.fn(), push: vi.fn() }) }))

const { default: DayEnd } = await import('../src/screens/DayEnd.vue')

async function screen(summary) {
  daySummary.mockResolvedValue({
    date: '2026-10-13', open: true, day: 'FM-DAY-0001',
    started_at: '2026-10-13 09:30:00', minutes_on_route: 240,
    actual_visits: 6, planned_visits: 8, productive_visits: 4, pending_shops: [],
    ...summary,
  })
  const w = mount(DayEnd, {
    global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
  })
  await flushPromises()
  return w.text()
}

describe('where the distance figure came from', () => {
  it('says GPS trail when there really was one', async () => {
    const text = await screen({ distance_km: 41.2, distance_basis: 'trail' })
    expect(text).toContain('from your GPS trail')
    expect(text).toContain('Your GPS trail recorded 41.2 km today.')
  })

  it('does not claim a trail when the figure came off the route', async () => {
    const text = await screen({ distance_km: 38.5, distance_basis: 'route' })
    expect(text).not.toContain('GPS trail recorded')
    expect(text).toContain('No GPS trail today')
    // The figure itself is still shown. The fix is the caption, not hiding the number.
    expect(text).toContain('38.5')
    // And it says which way the figure under-reports, since the rep types an odometer under it.
    expect(text).toContain('The road is usually longer.')
  })

  it('says nothing was recorded when nothing was', async () => {
    const text = await screen({ distance_km: 0, distance_basis: null })
    expect(text).toContain('nothing recorded')
    expect(text).toContain('your odometer is the only figure there is')
    expect(text).not.toContain('GPS trail recorded')
  })
})

/**
 * The same figure on the claim screen, where it is what somebody gets paid.
 *
 * This one matters more than the day end caption: the rep edits a number against it and the
 * manager reads the sentence when deciding whether to approve. "1.4 km more than your trail
 * recorded" is a specific claim about data, and on a day with no trail there is no such data.
 */
const expenseEstimate = vi.fn()

vi.mock('../src/lib/money', () => ({ formatRupees: (n) => `₹${Number(n || 0).toFixed(2)}` }))

const { default: ExpenseClaim } = await import('../src/screens/ExpenseClaim.vue')

async function claimScreen(estimate) {
  // Same module instance the day end tests mocked, so the extra methods are added here.
  const { api } = await import('../src/api/client')
  api.expenseEstimate = (...a) => expenseEstimate(...a)
  api.expensesMine = async () => []
  expenseEstimate.mockResolvedValue({
    expense_type: 'Travel', claim_date: '2026-10-13',
    trail_ping_count: 0, check_ins: 6, rate_per_km: 4, rate_is_set: true,
    tolerance_pct: 10, receipt_required_above: 500, already_claimed: null,
    ...estimate,
  })
  const w = mount(ExpenseClaim, {
    global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
  })
  await flushPromises()
  return w
}

describe('what the travel claim says it measured', () => {
  it('badges a real trail as a trail', async () => {
    const w = await claimScreen({
      trail_distance_km: 41.2, claimed_distance_km: 41.2,
      distance_basis: 'trail', trail_ping_count: 184,
    })
    expect(w.text()).toContain('GPS trail')
    expect(w.text()).toContain('184 pings')
  })

  it('badges a route figure as the route, not as a trail', async () => {
    const w = await claimScreen({
      trail_distance_km: 38.5, claimed_distance_km: 38.5, distance_basis: 'route',
    })
    const text = w.text()
    // The badge is the claim. The explanation below it may well say the words "GPS trail" -
    // saying there wasn't one is the whole point - so assert on the badge itself.
    expect(w.find('.badge').text()).toBe('Your route')
    expect(text).toContain('No GPS trail that day')
    // Shown as what it is: a straight line, so under the road distance, which is why a rep
    // editing it upward is normal rather than suspicious.
    expect(text).toContain('straight line')
  })

  it('does not tell the rep a trail recorded something it did not', async () => {
    // Well over the tolerance, which is the branch that prints the sentence.
    const w = await claimScreen({
      trail_distance_km: 20, claimed_distance_km: 20, distance_basis: 'route',
    })
    await w.find('button.link').trigger('click')
    const km = w.find('#km')
    await km.setValue(60)
    await flushPromises()
    const text = w.text()
    expect(text).toContain('than your route comes to')
    expect(text).not.toContain('than your trail recorded')
  })
})
