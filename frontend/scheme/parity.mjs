/**
 * Gate 4's parity suite, JavaScript side.
 *
 * Runs every case in `fieldmate/scheme/cases.json` through `frontend/src/scheme/engine.js` and
 * writes the results to stdout as canonical JSON - object keys sorted, no whitespace, integers as
 * integers. `fieldmate/tests/test_scheme_parity.py` does the identical thing to the Python twin and
 * serialises through a function of the same shape, so the two files compare as bytes rather than
 * as two programs somebody has to read side by side. `scripts/parity.sh` runs both and diffs all
 * three pairings: python against the corpus, node against the corpus, and python against node.
 *
 * The corpus path is resolved against this file's own URL and never against the working directory.
 * The gate gets run from the app root, from `frontend/`, and from a CI step that has cd'd
 * somewhere else entirely, and a harness that silently reads a different corpus depending on where
 * it was started from is a harness that can report green on nothing at all.
 *
 * This runs under a bare `node` with no bundler, no browser and no install step, for the same
 * reason its Python twin needs no bench: the evaluator is a pure function of a cart and a list of
 * compiled specs, and a gate that could only be checked inside a built app would not be checking
 * the thing that ships to the phone.
 */

import { readFileSync } from 'node:fs'

import { evaluate } from '../src/scheme/engine.js'

const CORPUS_URL = new URL('../../fieldmate/scheme/cases.json', import.meta.url)

/**
 * A result with its object keys sorted and every number checked for being a whole one.
 *
 * The integer check is not tidiness. Section 2 of the spec says there is no floating point
 * anywhere in the money path, so a float arriving here is the exact class of bug this gate exists
 * to catch - and it would otherwise slip through disguised as a formatting difference, because
 * JavaScript prints 24 where Python prints 24.0 for arithmetically identical values. Arrays keep
 * their order: section 6 pins `applied`, `dropped` and `near_misses` to S3 order, so their order
 * is one of the things being compared and sorting them would hide a real divergence.
 */
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical)
  if (typeof value === 'number') {
    if (!Number.isInteger(value)) {
      throw new Error(`a non-integer number reached the result where integer paise were required: ${value}`)
    }
    return value
  }
  if (value !== null && typeof value === 'object') {
    const sorted = {}
    for (const key of Object.keys(value).sort()) sorted[key] = canonical(value[key])
    return sorted
  }
  return value
}

function main() {
  const cases = JSON.parse(readFileSync(CORPUS_URL, 'utf8'))
  const emitted = cases.map((one) => ({ id: one.id, result: evaluate(one.cart, one.specs) }))
  process.stdout.write(JSON.stringify(canonical(emitted)) + '\n')
}

main()
