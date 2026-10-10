/**
 * A season booking, as the phone has to read it — the other half of `fieldmate/services/season.py`.
 *
 * Four questions, and a rep standing in a distributor's office needs all four answered with no
 * signal, because a booking is taken at a counter months before anything is delivered:
 *
 *   - is this order a booking at all, and of which season;
 *   - how much has to be collected before it is released;
 *   - which dates its lines may be asked for;
 *   - is the book still open to changes, or has the cutoff passed.
 *
 * **The arithmetic here is the server's arithmetic.** `season.advance_required` computes a
 * percentage of the order net and rounds it half up to the paisa, so this does the same, through
 * `round_half_up_div` — the one primitive every division in the money path goes through. A rep who
 * reads out an advance a paisa away from the one the office asks for has the same argument at the
 * counter as a rep who reads out the wrong total.
 *
 * Nothing here decides anything. The server owns `order_status`, the advance gate and the hold;
 * this is what the screen says while the rep is still building the cart.
 */

import { PERCENT_DENOMINATOR, round_half_up_div } from '../scheme/engine'

/** The kind a season order carries. Same string as `settings.BOOKING`, which is the field's value. */
export const BOOKING = 'Booking'

/** The status the server parks a booking in until its advance is in hand. */
export const AWAITING_ADVANCE = 'Awaiting Advance'

/**
 * Is this a booking?
 *
 * Asked of the kind, never of the presence of a season link. An order can name a season and not be
 * a booking of it — the season is written by the server off the order date, and the kind is the one
 * field that says what the order *is*.
 */
export function isBooking(kind) {
  return kind === BOOKING
}

/**
 * What a booking of this season needs up front, in whole paise.
 *
 * `advance_pct` arrives as a percentage off the master (25, or 12.5). It is taken to basis points
 * first so the division is integer: a float percentage multiplied into a paise figure is how two
 * implementations of the same rule come apart in the third decimal.
 *
 * Zero where the season asks for none, which is a decision somebody made on the master and not an
 * oversight — a season sold on open terms is an ordinary thing.
 */
export function advanceDue(netPaise, season) {
  const pct = Number(season && season.advance_pct) || 0
  const net = Math.trunc(Number(netPaise) || 0)
  if (!pct || net <= 0) return 0
  return round_half_up_div(net * Math.round(pct * 100), PERCENT_DENOMINATOR)
}

/**
 * The whole advance position of a booking, in paise, for a screen to draw in one go.
 *
 * `inHandPaise` is what has **arrived** and `pdcPaise` is what has been promised by a cheque that
 * has not fallen due. They are kept apart for the reason `in_hand_by_order` keeps them apart: a
 * post-dated cheque is allocated to the booking and visible against it, and it is not money until
 * its date. Releasing a season booking against one means reserving stock and planning a dispatch
 * on a promise.
 *
 * `held` is the arithmetic's own answer — still short. It is not a claim about what the server has
 * done: a booking's actual state is `order_status`, and only the server writes that.
 */
export function advanceView({ netPaise = 0, season = null, inHandPaise = 0, pdcPaise = 0 } = {}) {
  const required = advanceDue(netPaise, season)
  const inHand = Math.max(0, Math.trunc(Number(inHandPaise) || 0))
  const pdc = Math.max(0, Math.trunc(Number(pdcPaise) || 0))
  const short = Math.max(0, required - inHand)

  return {
    required,
    inHand,
    pdc,
    short,
    held: short > 0,
    // The percentage, for a bar. Full where nothing is required, because nothing outstanding is
    // not the same picture as nothing paid.
    pctDone: required ? Math.min(100, Math.round((inHand / required) * 100)) : 100,
  }
}

// ----------------------------------------------------------------------------- delivery window

/**
 * The dates a booking line may be asked for, as plain YYYY-MM-DD strings.
 *
 * Returned as a pair of nulls for an order with no season, so a caller can put them straight on a
 * date input's `min` and `max` without testing for a booking first — an input with no bounds is
 * exactly right for an order that has none.
 */
export function deliveryWindow(season) {
  return {
    from: (season && season.delivery_from) || null,
    to: (season && season.delivery_to) || null,
  }
}

/**
 * What a line's delivery date defaults to: the first day the season delivers.
 *
 * Blank is allowed by the server and means the same thing, but filling it in is worth doing — a
 * date a rep can see is a date a rep can change, and the whole point of booking a season is that
 * different lines land in different weeks.
 */
export function defaultDeliveryDate(season) {
  return deliveryWindow(season).from
}

/**
 * Is this date one the season can deliver on?
 *
 * Blank passes. The server fills a blank line with the window's first day (`check_delivery_dates`)
 * rather than refusing it, because making a rep type the same date on forty lines is how a form
 * stops being filled in honestly.
 */
export function withinWindow(date, season) {
  if (!date) return true
  const { from, to } = deliveryWindow(season)
  if (from && date < from) return false
  if (to && date > to) return false
  return true
}

/**
 * The lines whose date the season will refuse, so the review screen can say which before submit.
 *
 * The server throws on the first one it meets, naming one item. A rep reading that has to fix it,
 * submit again and be told about the next. This answers the whole question at once.
 */
export function outsideWindow(lines, season) {
  if (!season) return []
  return (lines || []).filter((line) => !withinWindow(line.delivery_date, season))
}

// -------------------------------------------------------------------------------------- words

/** What to call the season on a chip. The name somebody typed, never its id. */
export function seasonLabel(season) {
  return (season && (season.season_name || season.name)) || null
}

/**
 * Whether this booking can still be altered, and what to say if not.
 *
 * The verdict is the server's — `season.may_amend` reads the cutoff and this carries its answer
 * rather than comparing dates again. A screen that re-derived it would one day grey a button the
 * server would have accepted, or offer one it will refuse.
 */
export function changeNote(season) {
  if (!season || season.may_change !== false) return ''
  return season.change_note || 'This season is closed for changes.'
}

// ---------------------------------------------------------------------------------------- PDC

/**
 * A collection's post-dated status, for the deposit screen.
 *
 * `is_pdc` is the server's, decided against the server's own date: a handset whose clock is a week
 * out would otherwise tell a rep a cheque is bankable when the bank will refuse it. This only puts
 * words to it.
 *
 * A PDC still goes in the envelope. The office holds it until it falls due — which is exactly why
 * the rep has to be told, rather than left to wonder for three weeks why it never cleared.
 */
export function pdcStatus(row) {
  const isPdc = !!(row && (row.is_pdc === 1 || row.is_pdc === true))
  if (!isPdc) return { isPdc: false, dueOn: null, words: '' }
  return {
    isPdc: true,
    dueOn: (row && row.instrument_date) || null,
    words: 'Post-dated — the office holds it until it falls due',
  }
}
