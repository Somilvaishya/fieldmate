/**
 * Hindi and English on the phone.
 *
 * **The design this pins.** The English sentence is the key, the way Frappe's own `_()` keys on
 * the source string. The cost of that choice is that editing an English sentence orphans its
 * translation silently - the screen keeps working, in English, and nobody finds out. So the last
 * test here reads the screens and fails when a sentence has no Hindi, which is the only thing
 * that keeps a catalogue honest once the novelty wears off.
 *
 * The other half is whose choice wins. A handset is shared: a rep who set Hindi on this phone must
 * not be pulled back to English because the next login's User record carries the default.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { t, setLanguage, startLanguage, language, missing, LANGUAGES } from '../src/lib/i18n'
import hi from '../src/locales/hi'

beforeEach(() => {
  // Reset the in-memory language first, then wipe the saved choice - `setLanguage` persists, so
  // clearing before it would leave 'en' written down and every `startLanguage` test would then be
  // testing the handset override instead of what it says it tests.
  setLanguage('en')
  try {
    localStorage.clear()
  } catch {
    // A storage the environment refuses is not a test failure.
  }
})

describe('translating', () => {
  it('gives the English back when the language is English', () => {
    setLanguage('en')
    expect(t('Start day')).toBe('Start day')
  })

  it('gives the Hindi when it is Hindi', () => {
    setLanguage('hi')
    expect(t('Start day')).toBe('दिन शुरू करें')
  })

  it('falls back to the English sentence rather than showing a key', () => {
    // The whole reason the key is the sentence. A rep who meets an untranslated string reads
    // English they half know; a rep who meets `day.start.button` reads nothing.
    setLanguage('hi')
    expect(t('Something nobody has translated yet')).toBe('Something nobody has translated yet')
  })

  it('fills in values, and leaves a missing one as written', () => {
    setLanguage('en')
    expect(t('Owed {amount} by {shop}', { amount: '₹400', shop: 'Nagpal' }))
      .toBe('Owed ₹400 by Nagpal')
    // Not "undefined" - a sentence with a gap is still readable, and `undefined` in front of a
    // shopkeeper is not.
    expect(t('Owed {amount} by {shop}', { amount: '₹400' })).toBe('Owed ₹400 by {shop}')
  })
})

describe('choosing the language', () => {
  it('takes the one on the rep’s User record when nothing is set here', () => {
    startLanguage('hi')
    expect(language.value).toBe('hi')
  })

  it('understands hi-IN as hi', () => {
    startLanguage('hi-IN')
    expect(language.value).toBe('hi')
  })

  it('lets the handset override the login', () => {
    // The shared-phone case. Somebody set this app to Hindi; the next rep's record says English.
    setLanguage('hi')
    startLanguage('en')
    expect(language.value).toBe('hi')
  })

  it('falls back to English for a language nobody has translated', () => {
    // A User record set to Tamil must not leave every screen showing keys.
    startLanguage('ta')
    expect(language.value).toBe('en')
  })

  it('offers exactly the languages it can actually render', () => {
    expect(LANGUAGES.map((l) => l.code)).toEqual(['en', 'hi'])
  })
})

describe('the catalogue keeps up with the screens', () => {
  /** Every string a converted screen passes to `t()`. */
  function translatedStrings(file) {
    const source = readFileSync(file, 'utf8')
    const found = []
    // t('...') and t("...") - the two quote styles the screens use.
    for (const m of source.matchAll(/\bt\(\s*'((?:[^'\\]|\\.)*)'/g)) found.push(m[1])
    for (const m of source.matchAll(/\bt\(\s*"((?:[^"\\]|\\.)*)"/g)) found.push(m[1])
    return found.map((s) => s.replace(/\\'/g, "'").replace(/\\"/g, '"'))
  }

  const SCREENS = join(__dirname, '..', 'src', 'screens')
  const SRC = join(__dirname, '..', 'src')

  /** Every .js and .vue under src, so the shared libs are covered too. */
  function sources(dir = SRC) {
    const out = []
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = join(dir, entry.name)
      if (entry.isDirectory()) out.push(...sources(full))
      else if (/\.(js|vue)$/.test(entry.name) && entry.name !== 'i18n.js') out.push(full)
    }
    return out
  }

  it('has Hindi for everything the converted files ask for', () => {
    // All of src, not just the screens. Four order screens read their scheme wording out of
    // `lib/schemeWords.js`, so a sentence with no Hindi in there would have been invisible to
    // the one test whose whole job is to notice that.
    const converted = sources().filter((file) =>
      /from '[^']*i18n'/.test(readFileSync(file, 'utf8')))

    expect(converted.length).toBeGreaterThan(0)

    const asked = [...new Set(converted.flatMap(translatedStrings))]
    expect(asked.length).toBeGreaterThan(10)

    // Named rather than counted, so a failure says which sentence to go and translate.
    expect(missing(asked, 'hi')).toEqual([])
  })

  it('imports t() everywhere under src that calls it', () => {
    // `Login.vue` did not. It imported `startLanguage` alone and called `t()` on the offline
    // sign-in error path, so the one message a rep needs when the first sign-in fails with no
    // signal raised `t is not defined` instead - a ReferenceError inside a catch block, which
    // is where nothing ever looks.
    //
    // Walks all of `src`, not just the screens. The first version of this guard looked at
    // `src/screens` alone, and `lib/credit.js` and `lib/season.js` then picked up `t()` calls
    // with no import and it said nothing - the same fault, in the one place not being watched.
    // The libs matter more, not less: four order screens read their scheme wording out of
    // `lib/schemeWords.js`.
    const broken = []
    const walk = (dir) => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const full = join(dir, entry.name)
        if (entry.isDirectory()) {
          walk(full)
          continue
        }
        if (!/\.(js|vue)$/.test(entry.name) || entry.name === 'i18n.js') continue
        const source = readFileSync(full, 'utf8')
        // `t(` preceded by a word character or a dot is somebody else's `t` - a loop variable,
        // a property. Only a bare call counts.
        if (!/(?<![\w.$])t\(\s*['"]/.test(source)) continue
        const imported = source.match(/import\s*\{([^}]*)\}\s*from\s*'[^']*i18n'/)
        const named = imported ? imported[1].split(',').map((x) => x.trim()) : []
        if (!named.includes('t')) broken.push(full.slice(SRC.length + 1))
      }
    }
    walk(SRC)
    expect(broken).toEqual([])
  })

  it('never nests one t() inside another', () => {
    // Thirty of these, from a blanket replace that ran twice over the same files. It worked:
    // the inner call returns the Hindi and the outer looks that Hindi up as a key, finds
    // nothing, and hands it back. It stops working the moment a Hindi string happens to match
    // another key.
    const nested = []
    for (const name of readdirSync(SCREENS)) {
      const source = readFileSync(join(SCREENS, name), 'utf8')
      const hits = source.match(/\bt\(\s*t\(/g)
      if (hits) nested.push(`${name}: ${hits.length}`)
    }
    expect(nested).toEqual([])
  })

  it('builds no key by joining strings together', () => {
    // `t('half a ' + 'sentence')` is a key at runtime and two fragments to anything reading the
    // source - including the check above, which is how this was found. A long sentence becomes
    // two keys, or one long line; never a sum.
    const joined = []
    for (const name of readdirSync(SCREENS)) {
      const source = readFileSync(join(SCREENS, name), 'utf8')
      if (/\bt\(\s*['"][^'"]*['"]\s*\+/.test(source)) joined.push(name)
    }
    expect(joined).toEqual([])
  })

  it('never evaluates a label at import time', () => {
    // The trap a rep found by hand. `Me.vue`'s `LINKS` was a module-level const, evaluated once
    // when the file was first imported, so its titles held whichever language loaded first and
    // never moved again. The switch then worked on the rest of the screen and not on those four
    // rows - which reads worse than no translation, because it looks like a half-broken app.
    //
    // Anything holding a label has to be a `computed`, so it re-runs when the language ref
    // changes. Walked line by line rather than matched with one regex: the first version of this
    // check used a lookahead and reported all ten `computed(...)` consts as frozen, because one
    // match's body ran over the next declaration.
    const LAZY = ['computed(', 'ref(', 'reactive(', 'function', '(', 'async', 'new ']
    const frozen = []

    for (const name of readdirSync(SCREENS)) {
      const script = /<script[^>]*>([\s\S]*?)<\/script>/.exec(
        readFileSync(join(SCREENS, name), 'utf8'))
      if (!script) continue
      const lines = script[1].split('\n')

      for (let i = 0; i < lines.length; i += 1) {
        const decl = /^(?:const|let|var)\s+(\w+)\s*=\s*(.*)$/.exec(lines[i])
        if (!decl) continue
        const [, variable, rest] = decl
        const body = [rest]
        let j = i + 1
        // Stop at the next top-level statement; anything indented belongs to this one.
        while (j < lines.length && !/^(?:const|let|var|function|async|class|export|import|on[A-Z])/
          .test(lines[j])) {
          body.push(lines[j])
          j += 1
        }
        const eager = !LAZY.some((start) => rest.startsWith(start))
        if (eager && /(?<![\w.$])t\(\s*['"]/.test(body.join('\n'))) {
          frozen.push(`${name}: ${variable}`)
        }
        i = j - 1
      }
    }

    expect(frozen).toEqual([])
  })

  it('holds each sentence once, and quotes it legally', () => {
    // Both faults were in the catalogue at once. The duplicate was older than this pass; the
    // bad quoting was mine, `'Today's route'`, and a syntax error in the catalogue takes out
    // every test that imports it - which reads as the translations being broken rather than
    // one line being unparseable.
    const source = readFileSync(join(__dirname, '..', 'src', 'locales', 'hi.js'), 'utf8')
    const keys = []
    const illegal = []
    for (const m of source.matchAll(/^\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*:/gm)) {
      const key = m[1] !== undefined ? m[1] : m[2]
      if (m[1] !== undefined && m[1].includes("'")) illegal.push(key)
      keys.push(key)
    }
    expect(illegal).toEqual([])
    const duplicated = keys.filter((k, i) => keys.indexOf(k) !== i)
    expect(duplicated).toEqual([])
  })

  it('carries no Hindi for a sentence no screen says', () => {
    // Not a failure, a report: a catalogue that only grows becomes a list nobody trusts. These
    // are the ones to look at when a screen's wording changes.
    const asked = new Set(sources().flatMap(translatedStrings))
    const unused = Object.keys(hi).filter((key) => !asked.has(key))
    // The slice deliberately carries a few sentences for screens not yet converted.
    expect(unused.length).toBeLessThan(Object.keys(hi).length)
  })
})
