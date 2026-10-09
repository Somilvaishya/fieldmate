/**
 * The share screen — the only thing in this app a rep can hand to somebody with no login.
 *
 * A share link is a URL in a WhatsApp message, so whoever holds it is whoever it was forwarded to.
 * A rep who does not know that will send one into a market group, and from then on one party's
 * prices are everybody's. So what this screen must **say** is as much the feature as what it does,
 * and that is most of what is tested here.
 *
 * The second half is about not lying about a self-order. What comes back off a shared catalogue is
 * a **draft** for the rep to price and submit — a party typing quantities into a web page has been
 * through no credit check, no scheme engine and no MRP check. A screen that called it an order
 * would promise the party something the server will not do.
 */
import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const showcaseCatalogues = vi.fn()
const showcaseShare = vi.fn()
const showcaseLinks = vi.fn()
const showcaseWithdraw = vi.fn()

vi.mock('../src/api/client', () => ({
  api: {
    showcaseCatalogues: (...a) => showcaseCatalogues(...a),
    showcaseShare: (...a) => showcaseShare(...a),
    showcaseLinks: () => showcaseLinks(),
    showcaseWithdraw: (...a) => showcaseWithdraw(...a),
  },
  ApiError: class ApiError extends Error {},
}))

const profile = { distributors: [] }
vi.mock('../src/db', () => ({ getMeta: async () => profile }))

const { default: Showcase } = await import('../src/screens/Showcase.vue')

/** A link as `showcase.links_of` sends it, enriched. */
function link(extra = {}) {
  return {
    name: 'FM-SHARE-0001',
    token: 'a'.repeat(32),
    catalogue: 'FM-CAT-0007',
    catalogue_name: 'Holi range',
    party_type: 'Customer',
    customer: 'MAHALAXMI',
    party: 'MAHALAXMI',
    party_name: 'Mahalaxmi Distributors',
    valid_from: '2026-01-10',
    valid_to: '2026-02-10',
    max_views: 0,
    is_active: 1,
    view_count: 3,
    first_opened: '2026-01-11 09:00:00',
    last_opened: '2026-01-14 17:30:00',
    live: true,
    closed_because: '',
    url: 'https://testerp2.example/showcase?t=' + 'a'.repeat(32),
    season: null,
    ...extra,
  }
}

async function screen({ parties = [], links = [], catalogues = [] } = {}) {
  profile.distributors = parties
  showcaseLinks.mockResolvedValue({ links })
  showcaseCatalogues.mockResolvedValue({ catalogues })
  const wrapper = mount(Showcase, {
    global: { stubs: { RouterLink: { template: '<a><slot/></a>' }, Icon: true } },
  })
  await flushPromises()
  // The party list is read from the handset, so a single party selects itself and the catalogue
  // call goes out. Flush again so that answer has landed before anything is asserted.
  await flushPromises()
  return wrapper
}

const ONE_PARTY = [{ distributor: 'MAHALAXMI', distributor_name: 'Mahalaxmi Distributors' }]

describe('what the rep is told before they make one', () => {
  it('says whoever holds the link can open it', async () => {
    const w = await screen()
    expect(w.text()).toContain('Whoever holds the link can open it')
  })

  it('says it carries one party’s prices', async () => {
    const w = await screen()
    expect(w.text()).toContain("one party")
  })

  it('says it expires and can be switched off', async () => {
    const w = await screen()
    expect(w.text()).toContain('expires')
    expect(w.text()).toContain('switch it off')
  })
})

describe('what can be shared', () => {
  it('asks the server per party rather than guessing', async () => {
    // Scoping is per party: a catalogue written for one region does not reach a party in
    // another, and only a catalogue marked as a showcase can be shared at all.
    await screen({ parties: ONE_PARTY, catalogues: [] })
    expect(showcaseCatalogues).toHaveBeenCalledWith('MAHALAXMI', 'Customer')
  })

  it('explains why there is nothing to share, rather than drawing an empty box', async () => {
    // "Nothing to share" and "nothing is marked as a showcase" are different problems, and only
    // one of them is the rep's to report to a manager.
    const w = await screen({ parties: ONE_PARTY, catalogues: [] })
    expect(w.text()).toContain('marked as a showcase')
  })

  it('offers a showcase catalogue with its size', async () => {
    const w = await screen({
      parties: ONE_PARTY,
      catalogues: [{ name: 'FM-CAT-0007', catalogue_name: 'Holi range', line_count: 24 }],
    })
    expect(w.text()).toContain('Holi range')
    expect(w.text()).toContain('24 items')
  })

  it('says there is nobody to share with where no party is set up', async () => {
    const w = await screen({ parties: [] })
    expect(w.text()).toContain('nobody here to share with')
  })
})

describe('the link that comes back', () => {
  async function made() {
    const w = await screen({
      parties: ONE_PARTY,
      catalogues: [{ name: 'FM-CAT-0007', catalogue_name: 'Holi range', line_count: 24 }],
    })
    showcaseShare.mockResolvedValue({
      link: 'FM-SHARE-0002',
      token: 'b'.repeat(32),
      url: 'https://testerp2.example/showcase?t=' + 'b'.repeat(32),
    })
    showcaseLinks.mockResolvedValue({ links: [] })
    await w.find('button.btn-primary').trigger('click')
    await flushPromises()
    return w
  }

  it('shows the address as text, not only on the clipboard', async () => {
    // A copy the browser refused is a copy the rep has no way to notice. The URL is on screen to
    // read off either way.
    const w = await made()
    expect(w.text()).toContain('showcase?t=' + 'b'.repeat(32))
  })

  it('sends the party and the catalogue, and never a price list', async () => {
    // A phone that could name its own price list could quote the range off the cheapest one.
    await made()
    const sent = showcaseShare.mock.calls[0][0]
    expect(sent.party).toBe('MAHALAXMI')
    expect(sent.catalogue).toBe('FM-CAT-0007')
    expect(sent.party_type).toBe('Customer')
    expect(sent).not.toHaveProperty('price_list')
    expect(sent).not.toHaveProperty('token')
  })

  it('calls what comes back a draft, not an order', async () => {
    const w = await made()
    expect(w.text()).toContain('draft order')
    expect(w.text()).toContain('nothing they do commits anything')
  })
})

describe('what was shared already', () => {
  it('says how often it has been opened', async () => {
    const w = await screen({ parties: ONE_PARTY, links: [link({ view_count: 3 })] })
    expect(w.text()).toContain('Opened 3 times')
  })

  it('says so plainly when it has not been opened at all', async () => {
    // Which is the thing a rep most wants to know: did they even look.
    const w = await screen({ parties: ONE_PARTY, links: [link({ view_count: 0, last_opened: null })] })
    expect(w.text()).toContain('Not opened yet')
  })

  it('names the party and the catalogue, never their ids', async () => {
    const w = await screen({ parties: ONE_PARTY, links: [link()] })
    expect(w.text()).toContain('Mahalaxmi Distributors')
    expect(w.text()).toContain('Holi range')
    expect(w.text()).not.toContain('FM-SHARE-0001')
  })

  it('marks a closed link and says the date it expired', async () => {
    const w = await screen({
      parties: ONE_PARTY,
      links: [link({ live: false, is_active: 1, closed_because: 'This link has expired. Ask for a new one.' })],
    })
    expect(w.text()).toContain('Closed')
    expect(w.text()).toContain('Expired')
    expect(w.text()).toContain('10 Feb 26')
  })

  it('offers no copy button for a link that no longer works', async () => {
    const w = await screen({ parties: ONE_PARTY, links: [link({ live: false })] })
    expect(w.text()).not.toContain('Copy the link')
  })

  it('takes two taps to switch one off, and says it cannot be undone', async () => {
    // Somebody may be reading the page right now, and the address is dead for good.
    const w = await screen({ parties: ONE_PARTY, links: [link()] })
    const pull = w.findAll('button').find((b) => b.text() === 'Switch it off')
    await pull.trigger('click')
    expect(showcaseWithdraw).not.toHaveBeenCalled()
    expect(w.text()).toContain('cannot be undone')

    const yes = w.findAll('button').find((b) => b.text().includes('Yes, switch it off'))
    await yes.trigger('click')
    expect(showcaseWithdraw).toHaveBeenCalledWith('FM-SHARE-0001')
  })

  it('says a new one can be made, so switching off is not a decision to agonise over', async () => {
    const w = await screen({ parties: ONE_PARTY, links: [link()] })
    const pull = w.findAll('button').find((b) => b.text() === 'Switch it off')
    await pull.trigger('click')
    expect(w.text()).toContain('make a new link')
  })
})
