/**
 * What every test in this directory can assume exists.
 *
 * Dexie opens a real IndexedDB, so the stores cannot even be imported without one. `fake-indexeddb/auto`
 * installs an in-memory implementation over the globals before any module under test is loaded.
 */
import 'fake-indexeddb/auto'
import { beforeEach, vi } from 'vitest'

// `crypto.randomUUID` is used wherever this app assigns identity before the server has - a cart,
// a visit, a queued order. happy-dom has `crypto` but not always this method.
if (!globalThis.crypto) globalThis.crypto = {}
if (!globalThis.crypto.randomUUID) {
  let n = 0
  globalThis.crypto.randomUUID = () => `test-uuid-${++n}`
}

beforeEach(() => {
  // Each test starts with an empty one. A value left behind by one test is a pass the next test
  // did not earn - the same rule the Python fixtures follow.
  try {
    globalThis.localStorage?.clear()
    globalThis.sessionStorage?.clear()
  } catch {
    // A storage the environment refuses is not a test failure.
  }
  vi.useRealTimers()
})
