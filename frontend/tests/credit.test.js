/**
 * `lib/credit.js` — whose credit a screen is about.
 *
 * A rep opened a kirana and read "Credit headroom -600, of 500 limit". Both figures were its
 * distributor's position with us. The shop's own limit was unset and its own outstanding nothing.
 * `api.outlet` returning the billing party's credit is correct and always was; what was wrong is
 * that this reading carried no name, so every screen built on it drew the number anonymously and
 * a rep read it as the shop's.
 *
 * These tests are about the reading, not the rendering: does it carry whose figures these are,
 * and does it keep the shop's own position beside them.
 */
import { describe, it, expect } from 'vitest'
import { assessCredit } from '../src/lib/credit'

/** What `api.outlet` sends, trimmed to the credit block these tests are about. */
function reading({ limit = 500, outstanding = 0, shop = null, party = 'Mahalaxmi Distributors' } = {}) {
  return {
    limit_paise: limit * 100,
    outstanding_paise: outstanding * 100,
    unlimited: !limit,
    known: true,
    party_name: party,
    shop_limit_paise: (shop?.limit || 0) * 100,
    shop_outstanding_paise: (shop?.outstanding || 0) * 100,
    shop_headroom_paise: (shop?.headroom || 0) * 100,
    shop_has_limit: (shop?.limit || 0) > 0,
  }
}

describe('whose credit the screen is about', () => {
  it('names the party on a figure it reports', () => {
    const view = assessCredit(reading({ limit: 500, outstanding: 1099.62 }), 0)
    expect(view.party_name).toBe('Mahalaxmi Distributors')
  })

  it('names the party even when nobody set a limit', () => {
    // The headline used to read "No credit limit set for this shop" over the distributor's own
    // position - the one party it was never about.
    const view = assessCredit(reading({ limit: 0 }), 0)
    expect(view.state).toBe('unlimited')
    expect(view.headline).toContain('Mahalaxmi Distributors')
    expect(view.headline).not.toContain('this shop')
  })

  it('carries the shop’s own position beside the distributor’s', () => {
    const view = assessCredit(
      reading({ limit: 500, outstanding: 1099.62, shop: { limit: 5000, outstanding: 1200 } }), 0)

    expect(view.limit_paise).toBe(50_000)
    expect(view.shop_limit_paise).toBe(500_000)
    expect(view.shop_outstanding_paise).toBe(120_000)
    expect(view.shop_has_limit).toBe(true)
  })

  it('does not measure a shop nobody has given a limit', () => {
    // A Currency column is NOT NULL DEFAULT 0, so a zero cannot be told from a blank. Treating
    // the default as a ceiling would put every shop over its limit the day it was onboarded.
    const view = assessCredit(reading({ shop: { limit: 0, outstanding: 0 } }), 0)
    expect(view.shop_has_limit).toBe(false)
  })
})

describe('the distributor’s own arithmetic', () => {
  it('reports a breach when the order takes the party past its limit', () => {
    const view = assessCredit(reading({ limit: 500, outstanding: 400 }), 20_000)
    expect(view.state).toBe('breach')
    expect(view.over_paise).toBe(10_000)
  })

  it('does not call a rounding difference a breach', () => {
    // "You are 0.000001 over" is not something anybody can say to a shopkeeper.
    const view = assessCredit(reading({ limit: 500, outstanding: 500 }), 0)
    expect(view.state).toBe('within')
  })

  it('says nothing at all when the phone has no reading', () => {
    const view = assessCredit(null, 1000)
    expect(view.state).not.toBe('within')
    expect(view.state).not.toBe('breach')
  })
})
