/**
 * The scheme corpus, run through the engine that ships to the phone.
 *
 * `scripts/parity.sh` has always diffed three pairings - python against the corpus, node against
 * the corpus, and python against node - and it has always been run by hand. Only two of those
 * three were ever checked by a machine on its own: `bench run-tests` runs
 * `fieldmate/tests/test_scheme_parity.py`, which is the Python half, and CI never touched
 * `src/scheme/engine.js` at all. So the 691 lines that decide which offer a rep reads out across
 * a counter were covered by nothing that runs unprompted.
 *
 * This file is the missing third. It is deliberately a mirror of the Python test rather than a
 * fresh idea about how to check the same thing: same corpus file, same case ids, one test per
 * case, and the same integer rule from section 2 of `docs/SCHEME_SPEC.md`. When the two engines
 * drift, both suites go red and name the same case.
 *
 * The corpus is the independent third party here, which is the whole shape of the gate. Two
 * engines diffed only against each other agree perfectly the day they share a misreading.
 */

import { describe, expect, it } from 'vitest'

// The one corpus, imported by a path relative to this file rather than read off the working
// directory. vitest starts in `frontend/`, `parity.sh` runs from the app root and CI cd's
// somewhere else again; a harness that reads a different corpus depending on where it was
// started from can report green on nothing at all. (`parity.mjs` resolves the same file against
// `import.meta.url`, which under vitest is not a file: URL - hence the import.)
import cases from '../../fieldmate/scheme/cases.json'

import { evaluate } from '../src/scheme/engine.js'

/**
 * A result with its numbers checked for being whole ones.
 *
 * Section 2 of the spec says there is no floating point anywhere in the money path, so a float
 * arriving here is the exact class of bug this gate exists to catch. It would otherwise slip
 * through a value comparison unnoticed: 24 and 24.0 are the same JavaScript number, so only an
 * explicit check can tell a paise count from a rupee figure that got divided somewhere.
 */
function assertWholeNumbers(value, path = '') {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertWholeNumbers(item, `${path}[${index}]`))
    return
  }
  if (typeof value === 'number' && !Number.isInteger(value)) {
    throw new Error(`${path || '(whole result)'} is ${value}, and the money path carries only integer paise`)
  }
  if (value !== null && typeof value === 'object') {
    for (const key of Object.keys(value)) assertWholeNumbers(value[key], path ? `${path}.${key}` : key)
  }
}

describe('the scheme corpus against the engine the phone runs', () => {
  it('is not empty', () => {
    // A corpus that failed to load would otherwise register zero tests and report green.
    expect(cases.length).toBeGreaterThan(0)
  })

  it('has no duplicate case ids', () => {
    // Two cases sharing an id leaves the gate one case smaller than it reads, silently. The
    // Python half fails its import over this; here the ids are what name the tests below.
    const ids = cases.map((one) => one.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  for (const one of cases) {
    // `why` says what the case is defending, and it belongs in the test name for the same reason
    // the Python half puts it in the docstring: it is the shortest route from a red line to the
    // clause of the spec it came from.
    it(`${one.id} — ${one.why}`, () => {
      const result = evaluate(one.cart, one.specs)
      assertWholeNumbers(result)
      // `toStrictEqual`, not `toEqual`: the spec writes an absent label as null on purpose, so a
      // key holding null and a key that is not there are two different answers and the gate has
      // to be able to tell them apart.
      expect(result).toStrictEqual(one.expect)
    })
  }
})
