/**
 * The switch that turns the translations on.
 *
 * Without this the whole of #13 was machinery nobody could reach: `t()` worked, the Hindi was
 * written, seven screens were converted, and a rep opening the app saw English because the only
 * way to change language was to edit their User record in Desk.
 *
 * The thing worth pinning is that it takes effect **at once**. `t()` reads a ref, so every
 * converted screen re-renders on the tap - no reload, no re-fetch, nothing to wait for on a
 * market connection. A language switch that needed a reload would be one a rep tried once.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('../src/api/client', () => ({
  api: { bootstrap: async () => ({ full_name: 'Test Rep', designation: 'Field Rep' }), logout: vi.fn() },
  setCsrfToken: vi.fn(),
}))
vi.mock('../src/db', () => ({
  getMeta: async () => ({ full_name: 'Test Rep' }),
  setMeta: vi.fn(),
  wipe: vi.fn(),
}))
vi.mock('../src/sync/outbox', () => ({ pendingCount: async () => 0, drain: vi.fn() }))
vi.mock('../src/sync/photos', () => ({ pendingCount: async () => 0, drain: vi.fn() }))
vi.mock('../src/sync/pinger', () => ({ pendingPings: async () => 0, flush: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

const { setLanguage, language } = await import('../src/lib/i18n')
const { default: Me } = await import('../src/screens/Me.vue')

async function screen() {
  const w = mount(Me, {
    global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
  })
  await flushPromises()
  return w
}

/** The two language buttons, in the order the screen offers them. */
function options(w) {
  return w.findAll('.opt')
}

beforeEach(() => {
  setLanguage('en')
  try {
    localStorage.clear()
  } catch {
    // Storage the environment refuses is not a test failure.
  }
})

describe('the language switch', () => {
  it('offers both languages, each labelled in its own script', async () => {
    const w = await screen()
    expect(options(w).map((b) => b.text())).toEqual(['English', 'हिन्दी'])
  })

  it('shows which one is on', async () => {
    const w = await screen()
    expect(options(w)[0].attributes('aria-pressed')).toBe('true')
    expect(options(w)[1].attributes('aria-pressed')).toBe('false')
  })

  it('changes the language on the tap', async () => {
    const w = await screen()
    await options(w)[1].trigger('click')
    expect(language.value).toBe('hi')
  })

  it('redraws the screen in Hindi at once, with no reload', async () => {
    // The whole point. `t()` reads a ref, so the row's own label changes under the thumb.
    const w = await screen()
    expect(w.text()).toContain('Language')

    await options(w)[1].trigger('click')
    await flushPromises()

    expect(w.text()).toContain('भाषा')
    expect(w.text()).not.toContain('Language')
  })

  it('moves the mark to whichever is chosen', async () => {
    const w = await screen()
    await options(w)[1].trigger('click')
    await flushPromises()
    expect(options(w)[1].attributes('aria-pressed')).toBe('true')
    expect(options(w)[0].attributes('aria-pressed')).toBe('false')
  })

  it('remembers the choice on this handset', async () => {
    const w = await screen()
    await options(w)[1].trigger('click')
    expect(localStorage.getItem('fm_language')).toBe('hi')
  })

  it('goes back to English just as easily', async () => {
    const w = await screen()
    await options(w)[1].trigger('click')
    await flushPromises()
    await options(w)[0].trigger('click')
    await flushPromises()
    expect(language.value).toBe('en')
    expect(w.text()).toContain('Language')
  })
})
