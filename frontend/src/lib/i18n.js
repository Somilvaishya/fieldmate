/**
 * Hindi and English on the phone.
 *
 * **The English sentence is the key.** `t('Take the photo at the shop')` rather than
 * `t('visit.photo.prompt')`. Three reasons, and they all matter more than tidiness:
 *
 * 1. A missing translation falls back to the English that is already written, which a rep can
 *    read. A missing key falls back to `visit.photo.prompt`, which nobody can.
 * 2. The templates stay readable. Somebody fixing a screen sees the sentence a rep sees, not a
 *    token they have to go and look up.
 * 3. It is the convention the server half already uses - Frappe's `_()` keys on the source
 *    string too - so one glossary can feed both sides rather than two that drift.
 *
 * The cost is real and worth stating: changing the English wording orphans its translation. That
 * is why `missing()` exists, and why the test suite asserts the catalogue covers what the screens
 * actually say.
 */
import { ref, computed } from 'vue'

import hi from '../locales/hi'

const CATALOGUES = { hi }

/** Where a rep's own choice is kept. Per device, because handsets get handed around. */
const STORAGE_KEY = 'fm_language'

const current = ref('en')

/** Languages a rep can pick, in the order the toggle shows them. */
export const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्दी' },
]

export const language = computed(() => current.value)
export const isHindi = computed(() => current.value === 'hi')

/**
 * Translate, falling back to the English that was passed in.
 *
 * Interpolation is `{name}`, and an argument that is missing is left as written rather than
 * printed as `undefined` - a sentence with a gap in it is still readable, and `undefined` in
 * front of a shopkeeper is not.
 */
export function t(english, values) {
  const catalogue = CATALOGUES[current.value]
  let out = (catalogue && catalogue[english]) || english
  if (values) {
    out = out.replace(/\{(\w+)\}/g, (whole, key) =>
      values[key] === undefined || values[key] === null ? whole : String(values[key]))
  }
  return out
}

/**
 * Switch language.
 *
 * Only a language we actually carry. An unknown code - a stale profile, a User record set to
 * something nobody has translated - falls back to English rather than leaving every screen
 * showing keys.
 */
export function setLanguage(code) {
  const known = LANGUAGES.some((l) => l.code === code)
  current.value = known ? code : 'en'
  try {
    localStorage.setItem(STORAGE_KEY, current.value)
  } catch {
    // A private window, or storage the browser refuses. The choice holds for this session.
  }
  return current.value
}

/**
 * Work out the language at startup: what the rep chose on this handset, then what their User
 * record says, then English.
 *
 * The rep's own choice wins over the server's. A handset is shared, and somebody who has set the
 * app to Hindi on this phone should not have it pulled back to English because the login they are
 * using was created with the default.
 */
export function startLanguage(profileLanguage) {
  let saved = null
  try {
    saved = localStorage.getItem(STORAGE_KEY)
  } catch {
    saved = null
  }
  return setLanguage(saved || normalise(profileLanguage))
}

/** Frappe stores `hi`, but also things like `hi-IN` and `en-GB`. Only the first part matters. */
function normalise(code) {
  return String(code || 'en').toLowerCase().split(/[-_]/)[0]
}

/**
 * English strings the catalogue does not carry, for the test that keeps the two in step.
 *
 * Exported rather than logged: a console warning in a PWA is seen by nobody, and the thing that
 * actually keeps a translation honest is a test that fails.
 */
export function missing(englishStrings, code = 'hi') {
  const catalogue = CATALOGUES[code] || {}
  return englishStrings.filter((s) => !(s in catalogue))
}
