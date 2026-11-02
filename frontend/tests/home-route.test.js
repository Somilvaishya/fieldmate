/**
 * No screen sends anybody to a hard-coded home.
 *
 * Home is Today for a rep and the Team board for a manager. Day Start, Day End, the end of a
 * visit, the end of an order and half a dozen guards all said '/today' - so an Area Manager who
 * checked out of a shop landed on a rep's Today, with "Finish day" and "My routes" on it and none
 * of their own tabs lit. Found twice, by hand, in two different flows. Read off the source, the
 * way stock-count-entry.test.js reads a stylesheet, because the next one will be in a flow
 * nobody thought to mount.
 */
import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const SCREENS = resolve(process.cwd(), 'src/screens')

describe('where a flow ends', () => {
  it("no screen names '/today' as the place to go back to", () => {
    const offenders = readdirSync(SCREENS)
      .filter((f) => f.endsWith('.vue'))
      .filter((f) => /['"]\/today['"]/.test(readFileSync(resolve(SCREENS, f), 'utf8')))
    expect(offenders).toEqual([])
  })
})
