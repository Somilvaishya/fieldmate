/**
 * The box a rep types the count into.
 *
 * This is a layout rule, not behaviour, so it is asserted against the stylesheet rather than a
 * mounted component - jsdom lays nothing out and would have called the broken screen fine. It
 * earns a test because the cause was invisible from this file: the global sheet gives every
 * `select` `width: 100%`, and inside the flex row that reads as a basis of the whole line, so
 * the count box - which asked only for the leftover space - collapsed to a few pixels. A rep on
 * a real phone could not tap it, and the screen looked broken rather than cramped.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// From the project root, which is where vitest is run from. `import.meta.url` is rewritten by
// the transform and does not come back a file URL.
const source = readFileSync(resolve(process.cwd(), 'src/screens/StockCheck.vue'), 'utf8')

/** The declarations of one rule, as written. */
function rule(selector) {
  const at = source.indexOf(`\n${selector} {`)
  expect(at, `no rule for ${selector}`).toBeGreaterThan(-1)
  return source.slice(at + selector.length + 3, source.indexOf('}', at))
}

describe('the count box and the unit box share the row', () => {
  it('gives the pair a track of its own, so the item name cannot crowd them out', () => {
    const entry = rule('.entry')
    expect(entry).toMatch(/flex:\s*0 0 \d+px/)
    // Without this the track is only a wish: a flex item refuses to shrink below its content,
    // and the content here is an input whose intrinsic width is about twenty characters.
    expect(entry).toMatch(/min-width:\s*0/)
  })

  it('pins the unit box to a fixed width instead of the whole row', () => {
    const units = rule('.units')
    expect(units).toMatch(/flex:\s*0 0 \d+px/)
    // The global `select { width: 100% }` has to be answered in so many words; a flex basis
    // alone leaves the declared width standing on browsers that resolve it first.
    expect(units).toMatch(/width:\s*\d+px/)
  })

  it('lets the count box take whatever the unit box leaves, and claim nothing of its own', () => {
    const qty = rule('.qty')
    // Basis zero. `auto` here is what crushed the item name to one letter per line.
    expect(qty).toMatch(/flex:\s*1 1 0/)
    expect(qty).toMatch(/min-width:\s*0/)
    expect(qty).not.toMatch(/width:\s*auto/)
  })

  it('still clears the 48px target both boxes are tapped at', () => {
    expect(rule('.units')).toMatch(/min-height:\s*48px/)
    // `.qty` inherits its 48px from the global `input` rule.
    expect(source).toContain('class="qty tnum"')
  })
})
