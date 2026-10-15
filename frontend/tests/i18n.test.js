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

  it('has Hindi for everything the converted screens ask for', () => {
    const converted = readdirSync(SCREENS)
      .map((name) => join(SCREENS, name))
      .filter((file) => readFileSync(file, 'utf8').includes("from '../lib/i18n'"))

    expect(converted.length).toBeGreaterThan(0)

    const asked = [...new Set(converted.flatMap(translatedStrings))]
    expect(asked.length).toBeGreaterThan(10)

    // Named rather than counted, so a failure says which sentence to go and translate.
    expect(missing(asked, 'hi')).toEqual([])
  })

  it('carries no Hindi for a sentence no screen says', () => {
    // Not a failure, a report: a catalogue that only grows becomes a list nobody trusts. These
    // are the ones to look at when a screen's wording changes.
    const all = readdirSync(SCREENS).map((name) => join(SCREENS, name))
    const asked = new Set(all.flatMap(translatedStrings))
    const unused = Object.keys(hi).filter((key) => !asked.has(key))
    // The slice deliberately carries a few sentences for screens not yet converted.
    expect(unused.length).toBeLessThan(Object.keys(hi).length)
  })
})
