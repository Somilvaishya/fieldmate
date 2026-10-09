/**
 * `lib/season.js` — the booking arithmetic, which is the server's arithmetic written twice.
 *
 * A rep standing in a distributor's office has to say an advance figure out loud months before
 * anything is delivered, with no signal, and the office then asks for its own figure. The two have
 * to agree to the paisa for the same reason the cart total does: a rep who quoted a different
 * number has the argument at the counter, not in an email.
 *
 * The rest of these are about what must **not** be counted. A post-dated cheque is allocated to a
 * booking and shown against it and it is not money until its date, and a screen that added it to
 * the advance would release a booking on a promise — reserving stock and planning a dispatch
 * against a cheque that may yet bounce.
 */
import { describe, it, expect } from 'vitest'
import {
  AWAITING_ADVANCE,
  advanceDue,
  advanceView,
  changeNote,
  defaultDeliveryDate,
  deliveryWindow,
  isBooking,
  outsideWindow,
  pdcStatus,
  seasonLabel,
  withinWindow,
} from '../src/lib/season'

/** What `season.describe` sends, which is what every one of these reads. */
function season(extra = {}) {
  return {
    name: 'FM-SEASON-0001',
    season_name: 'Holi 2026',
    advance_pct: 25,
    delivery_from: '2026-02-20',
    delivery_to: '2026-03-10',
    change_cutoff: '2026-01-25',
    may_change: true,
    change_note: '',
    ...extra,
  }
}

describe('what kind of order this is', () => {
  it('is a booking when the kind says so', () => {
    expect(isBooking('Booking')).toBe(true)
  })

  it('is not a booking for a primary order', () => {
    // A primary order outside any open season. The season link is the *consequence* of being a
    // booking, never the test for it: the server writes it off the order date.
    expect(isBooking('Primary')).toBe(false)
    expect(isBooking('Secondary')).toBe(false)
    expect(isBooking(null)).toBe(false)
  })
})

describe('the advance, to the paisa', () => {
  it('takes the percentage off the net', () => {
    // 25% of 40,000.00
    expect(advanceDue(4000000, season())).toBe(1000000)
  })

  it('rounds a half up, as the server does', () => {
    // 25% of 1,000.05 is 250.0125 -> 250.01. `flt(x, 2)` on the server rounds half away from
    // zero; the phone divides through `round_half_up_div`. Both land on 25001 paise.
    expect(advanceDue(100005, season())).toBe(25001)
  })

  it('handles a fractional percentage', () => {
    // 12.5% of 1,000.00. A percentage with a decimal in it is why the rate is taken to basis
    // points before the division rather than multiplied in as a float.
    expect(advanceDue(100000, season({ advance_pct: 12.5 }))).toBe(12500)
  })

  it('asks for nothing where the season asks for nothing', () => {
    // A season sold on open terms. Somebody decided this; it is not an oversight.
    expect(advanceDue(4000000, season({ advance_pct: 0 }))).toBe(0)
  })

  it('asks for nothing when there is no season at all', () => {
    expect(advanceDue(4000000, null)).toBe(0)
  })
})

describe('what has arrived against it', () => {
  it('is short until the whole advance is in hand', () => {
    const view = advanceView({ netPaise: 4000000, season: season(), inHandPaise: 600000 })
    expect(view.required).toBe(1000000)
    expect(view.short).toBe(400000)
    expect(view.held).toBe(true)
  })

  it('is not short once it is covered', () => {
    const view = advanceView({ netPaise: 4000000, season: season(), inHandPaise: 1000000 })
    expect(view.short).toBe(0)
    expect(view.held).toBe(false)
  })

  it('does not count a post-dated cheque towards the advance', () => {
    // The whole point. The cheque is recorded, allocated and reported - and the booking is still
    // held, because releasing it means reserving stock against a promise.
    const view = advanceView({
      netPaise: 4000000,
      season: season(),
      inHandPaise: 0,
      pdcPaise: 1000000,
    })
    expect(view.short).toBe(1000000)
    expect(view.held).toBe(true)
    expect(view.pdc).toBe(1000000)
  })

  it('reports the post-dated money rather than hiding it', () => {
    // Hidden, a rep who has taken a cheque reads the hold as the office losing their paperwork.
    const view = advanceView({ netPaise: 100000, season: season(), pdcPaise: 25000 })
    expect(view.pdc).toBe(25000)
  })

  it('is never over-paid into a negative shortfall', () => {
    const view = advanceView({ netPaise: 100000, season: season(), inHandPaise: 99999999 })
    expect(view.short).toBe(0)
  })

  it('reads as settled where no advance is required', () => {
    const view = advanceView({ netPaise: 100000, season: season({ advance_pct: 0 }) })
    expect(view.held).toBe(false)
    expect(view.pctDone).toBe(100)
  })
})

describe('the delivery window', () => {
  it('carries the season dates', () => {
    expect(deliveryWindow(season())).toEqual({ from: '2026-02-20', to: '2026-03-10' })
  })

  it('is unbounded for an order with no season', () => {
    // Which is exactly right for a date input's min and max on an ordinary shop order.
    expect(deliveryWindow(null)).toEqual({ from: null, to: null })
  })

  it('defaults a line to the first day the season delivers', () => {
    expect(defaultDeliveryDate(season())).toBe('2026-02-20')
  })

  it('accepts a date inside the window', () => {
    expect(withinWindow('2026-02-25', season())).toBe(true)
  })

  it('accepts the boundaries themselves', () => {
    expect(withinWindow('2026-02-20', season())).toBe(true)
    expect(withinWindow('2026-03-10', season())).toBe(true)
  })

  it('refuses a date before the window', () => {
    expect(withinWindow('2026-02-19', season())).toBe(false)
  })

  it('refuses a date after the window', () => {
    expect(withinWindow('2026-03-11', season())).toBe(false)
  })

  it('accepts a blank, because the server fills it with the first day', () => {
    // `check_delivery_dates` does exactly this rather than refusing. Making a rep type the same
    // date on forty lines is how a form stops being filled in honestly.
    expect(withinWindow('', season())).toBe(true)
    expect(withinWindow(null, season())).toBe(true)
  })

  it('names every line the season will refuse, not just the first', () => {
    // The server throws on the first one it meets. A rep reading that fixes it, sends again, and
    // is told about the next - standing at a counter, on a market uplink.
    const bad = outsideWindow(
      [
        { item_code: 'A', delivery_date: '2026-02-25' },
        { item_code: 'B', delivery_date: '2026-04-01' },
        { item_code: 'C', delivery_date: '2026-01-01' },
      ],
      season()
    )
    expect(bad.map((l) => l.item_code)).toEqual(['B', 'C'])
  })

  it('refuses nothing on an order with no season', () => {
    expect(outsideWindow([{ item_code: 'A', delivery_date: '2030-01-01' }], null)).toEqual([])
  })
})

describe('the words', () => {
  it('calls the season by the name somebody typed', () => {
    expect(seasonLabel(season())).toBe('Holi 2026')
  })

  it('falls back to the id rather than drawing a blank chip', () => {
    expect(seasonLabel(season({ season_name: null }))).toBe('FM-SEASON-0001')
  })

  it('says nothing while the book is open', () => {
    expect(changeNote(season())).toBe('')
  })

  it("carries the server's sentence once the cutoff has passed", () => {
    const closed = season({ may_change: false, change_note: 'Holi 2026 closed for changes on 25-01-2026.' })
    expect(changeNote(closed)).toContain('closed for changes')
  })

  it('still says something if the server sent no sentence', () => {
    expect(changeNote(season({ may_change: false, change_note: '' }))).toBeTruthy()
  })
})

describe('a post-dated cheque in the satchel', () => {
  it("reads the server's verdict, not the handset clock", () => {
    // A phone whose clock is a week out would otherwise call a cheque bankable when the bank
    // will refuse it, which is why the comparison is made server-side.
    expect(pdcStatus({ mode: 'Cheque', instrument_date: '2026-03-20', is_pdc: 1 }).isPdc).toBe(true)
  })

  it('says when it falls due', () => {
    expect(pdcStatus({ is_pdc: 1, instrument_date: '2026-03-20' }).dueOn).toBe('2026-03-20')
  })

  it('is not post-dated when the server did not say so', () => {
    // A cheque dated today or earlier is ordinary money in the envelope.
    expect(pdcStatus({ mode: 'Cheque', instrument_date: '2026-01-01', is_pdc: 0 }).isPdc).toBe(false)
    expect(pdcStatus({ mode: 'Cash' }).isPdc).toBe(false)
  })

  it('says the office holds it, which is what the rep has to know', () => {
    expect(pdcStatus({ is_pdc: 1 }).words).toContain('holds it')
  })
})

describe('the status a held booking carries', () => {
  it('is its own, not an approval', () => {
    // Nobody is deciding anything - it is waiting for money - so it must not sit in a manager's
    // approval queue or read like something a rep can chase them about.
    expect(AWAITING_ADVANCE).toBe('Awaiting Advance')
  })
})
