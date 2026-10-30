/**
 * The Me screen reads the profile in the shape `auth.bootstrap` actually sends.
 *
 * It used to read designation, territory, the call target and the support line off the top level.
 * The server nests the first three under `field_user` and the last under `settings`, so every login
 * - Area Manager, Regional Manager, Sales Head - read "Field Rep", and the other three never showed.
 * The mock in language-switch.test.js put `designation` on the top level too, which is how a test
 * and a screen agreed on a shape the server never sent.
 *
 * The payload below mirrors `fieldmate/api/auth.py:bootstrap`. If that changes, change this.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

let payload

vi.mock('../src/api/client', () => ({
  api: { bootstrap: async () => payload, logout: vi.fn() },
  setCsrfToken: vi.fn(),
}))
vi.mock('../src/db', () => ({ getMeta: async () => null, setMeta: vi.fn(), wipe: vi.fn() }))
vi.mock('../src/sync/outbox', () => ({ pendingCount: async () => 0, drain: vi.fn() }))
vi.mock('../src/sync/photos', () => ({ pendingCount: async () => 0, drain: vi.fn() }))
vi.mock('../src/sync/pinger', () => ({ pendingPings: async () => 0, flush: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const { setLanguage } = await import('../src/lib/i18n')
const { default: Me } = await import('../src/screens/Me.vue')

function bootstrapFor({ designation, roles, isRep = false, fieldUser = true } = {}) {
  return {
    user: 'am1@test', full_name: 'Asha Mehra', roles, is_field_rep: isRep,
    sales_mode: 'Secondary',
    settings: { support_contact: '98100 00000' },
    field_user: fieldUser ? {
      field_user: 'FU-0003', designation, territory: 'Delhi West',
      daily_target_calls: 18, daily_target_basis: 'route', daily_target_beat: 'Rohini Monday',
    } : {},
  }
}

async function screen() {
  const w = mount(Me, {
    global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
  })
  await flushPromises()
  return w
}

beforeEach(() => setLanguage('en'))

describe('who the Me screen says you are', () => {
  for (const designation of ['Area Manager', 'Regional Manager', 'Sales Head']) {
    it(`a ${designation} is not called a Field Rep`, async () => {
      payload = bootstrapFor({ designation, roles: [`FieldMate ${designation}`] })
      const who = (await screen()).find('.who .dim').text()
      expect(who).toContain(designation)
      expect(who).not.toContain('Field Rep')
    })
  }

  it('shows the territory beside the designation', async () => {
    payload = bootstrapFor({ designation: 'Area Manager', roles: ['FieldMate Area Manager'] })
    expect((await screen()).find('.who .dim').text()).toContain('Delhi West')
  })

  it("shows today's call target and the beat it came from", async () => {
    payload = bootstrapFor({ designation: 'Field Rep', roles: ['FieldMate Field Rep'], isRep: true })
    const facts = (await screen()).find('.facts').text()
    expect(facts).toContain('18')
    expect(facts).toContain('Rohini Monday')
  })

  it('shows the support line from settings', async () => {
    payload = bootstrapFor({ designation: 'Field Rep', roles: ['FieldMate Field Rep'], isRep: true })
    expect((await screen()).text()).toContain('98100 00000')
  })

  it('a manager with no Field User row is not labelled a Field Rep', async () => {
    payload = bootstrapFor({ roles: ['FieldMate Sales Head'], fieldUser: false })
    expect((await screen()).find('.who .dim').text()).not.toContain('Field Rep')
  })

  it('a rep with no designation typed still reads Field Rep', async () => {
    payload = bootstrapFor({ roles: ['FieldMate Field Rep'], isRep: true })
    expect((await screen()).find('.who .dim').text()).toContain('Field Rep')
  })
})
