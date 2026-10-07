/**
 * `lib/tax.js` — the phone's half of `fieldmate/services/tax.py`.
 *
 * These two files are one rule written twice and they must change together: a rep quotes from
 * this copy with no signal, the server re-states the order from the other when the phone reaches
 * it, and the two are compared to the paise. Until now only the Python half had tests.
 *
 * The figures here are not invented. They are the ones off SAL-ORD-2026-00001, the order that
 * showed the phone and the server disagreeing in the first place.
 */
import { describe, it, expect } from 'vitest'
import { onPaise, forLines } from '../src/lib/tax'

const GST_12 = 1200
const GST_18 = 1800

describe('tax on one line', () => {
  it('matches the Sales Order that started this', () => {
    // 981.80 of goods at 12% came to 117.82 on the invoice. The phone said nothing at all.
    expect(onPaise(98_180, GST_12)).toBe(11_782)
  })

  it('rounds half up, as the server does', () => {
    // `round_half_up_div`, not banker's rounding. The two engines are compared to the paise, so
    // a different rounding rule is a divergence on every other order.
    expect(onPaise(50, GST_12)).toBe(6)   // 0.06 exactly, rounds up
    expect(onPaise(1, GST_12)).toBe(0)
  })

  it('is nothing where no template covers the item', () => {
    // Most items on most sites. A zero GST row is a claim about the company's tax position
    // rather than a fact about the order, so it is absent, not shown as zero.
    expect(onPaise(98_180, 0)).toBe(0)
    expect(onPaise(0, GST_12)).toBe(0)
  })
})

describe('tax across a cart', () => {
  const lines = [
    { item: 'SE-1000', gross_paise: 36_600 },
    { item: 'TM-500', gross_paise: 55_000 },
    { item: 'RIN-250', gross_paise: 3_300 },
  ]
  const rates = { 'SE-1000': GST_12, 'TM-500': GST_12, 'RIN-250': GST_12 }

  it('totals what the distributor will bill', () => {
    const { tax_paise } = forLines(lines, rates)
    expect(tax_paise).toBe(onPaise(36_600, GST_12) + onPaise(55_000, GST_12) + onPaise(3_300, GST_12))
  })

  it('taxes each line at its own rate', () => {
    const mixed = forLines(lines, { 'SE-1000': GST_18, 'TM-500': GST_12 })
    const byItem = Object.fromEntries(mixed.lines.map((l) => [l.item, l.tax_paise]))
    expect(byItem['SE-1000']).toBe(onPaise(36_600, GST_18))
    expect(byItem['TM-500']).toBe(onPaise(55_000, GST_12))
    expect(byItem['RIN-250']).toBe(0)
  })

  it('does not tax money the shop is not paying', () => {
    // The engine keeps one cart-level discount rather than marking down each line, so taxing a
    // line's gross would charge tax on a discount the shop never paid.
    const plain = forLines(lines, rates).tax_paise
    const discounted = forLines(lines, rates, 10_000).tax_paise
    expect(discounted).toBeLessThan(plain)
  })

  it('apportions the discount to the paise, with nothing lost', () => {
    const discount = 10_000
    const { lines: rows } = forLines(lines, rates, discount)
    const taxable = rows.reduce((sum, r) => sum + r.taxable_paise, 0)
    const gross = lines.reduce((sum, l) => sum + l.gross_paise, 0)
    expect(taxable).toBe(gross - discount)
  })

  it('answers the same for the same cart in a different order', () => {
    // Flooring leaves a few paise over and they go to the largest line, item code breaking ties.
    // Two phones holding the same cart must not disagree because a rep added things differently.
    const a = forLines(lines, rates, 7_777).tax_paise
    const b = forLines([...lines].reverse(), rates, 7_777).tax_paise
    expect(a).toBe(b)
  })

  it('never taxes more than the cart', () => {
    const { lines: rows } = forLines(lines, rates, 1_000_000)
    expect(rows.every((r) => r.taxable_paise >= 0)).toBe(true)
  })

  it('has nothing to say about an empty cart', () => {
    expect(forLines([], rates).tax_paise).toBe(0)
    expect(forLines(null, rates).tax_paise).toBe(0)
  })
})
