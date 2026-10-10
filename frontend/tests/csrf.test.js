/**
 * The CSRF token, on the phone's side.
 *
 * Frappe skips CSRF validation entirely for a session that has no token saved, and an API login
 * leaves one unset — so until the server started answering with one, every write this app made
 * was unprotected by it. The session cookie is `SameSite=Lax`, which stops the simplest
 * cross-site POST, but a cookie arriving is not a decision to perform an action.
 *
 * This is the half the Python suite cannot see: whether the client keeps what login gave it and
 * puts it on the right requests under the right name.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const fetchMock = vi.fn()

function answer(body, status = 200) {
  return {
    ok: status < 400,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: { get: () => 'application/json' },
  }
}

/** The envelope `fieldmate.api._base.ok` wraps everything in. */
function ok(message) {
  return { message: { ok: true, v: 1, ...message } }
}

let api
let setCsrfToken

beforeEach(async () => {
  vi.resetModules()
  globalThis.fetch = fetchMock
  fetchMock.mockReset()
  try {
    window.localStorage.clear()
  } catch { /* a storage the environment refuses is not a test failure */ }
  const mod = await import('../src/api/client')
  api = mod.api
  setCsrfToken = mod.setCsrfToken
})

afterEach(() => {
  try {
    window.localStorage.clear()
  } catch { /* as above */ }
})

/** The headers of the n-th fetch this test made. */
function headersOf(call = 0) {
  return fetchMock.mock.calls[call][1].headers
}

describe('what login does with the token', () => {
  it('keeps the one the server answers with', async () => {
    fetchMock.mockResolvedValueOnce(answer(ok({ user: 'rep@x', csrf_token: 'TOKEN-1' })))
    await api.login('rep@x', 'secret', 'device-1')

    fetchMock.mockResolvedValueOnce(answer(ok({})))
    await api.logout()
    expect(headersOf(1)['X-Frappe-CSRF-Token']).toBe('TOKEN-1')
  })

  it('survives the reload a service-worker update causes', async () => {
    fetchMock.mockResolvedValueOnce(answer(ok({ user: 'rep@x', csrf_token: 'TOKEN-2' })))
    await api.login('rep@x', 'secret', 'device-1')

    // A fresh module, as a reload gives: the token has to come back from storage or the first
    // write after an update is refused.
    vi.resetModules()
    const reloaded = await import('../src/api/client')
    fetchMock.mockResolvedValueOnce(answer(ok({})))
    await reloaded.api.logout()
    expect(headersOf(1)['X-Frappe-CSRF-Token']).toBe('TOKEN-2')
  })

  it('carries on when the server answers without one', async () => {
    // An older server, or one mid-deploy. A phone that refused to work without a token would
    // be a phone that stops working the moment the two sides are a release apart.
    fetchMock.mockResolvedValueOnce(answer(ok({ user: 'rep@x' })))
    await expect(api.login('rep@x', 'secret', 'device-1')).resolves.toBeTruthy()
  })
})

describe('which requests carry it', () => {
  beforeEach(async () => {
    fetchMock.mockResolvedValueOnce(answer(ok({ user: 'rep@x', csrf_token: 'TOKEN-3' })))
    await api.login('rep@x', 'secret', 'device-1')
    fetchMock.mockReset()
  })

  it('writes do', async () => {
    fetchMock.mockResolvedValueOnce(answer(ok({})))
    await api.logout()
    expect(headersOf()['X-Frappe-CSRF-Token']).toBe('TOKEN-3')
  })

  it('reads do not', async () => {
    // Frappe checks it for unsafe methods and nothing else, and sending it on every read would
    // put it in a query log for no gain.
    fetchMock.mockResolvedValueOnce(answer(ok({ orders: [] })))
    await api.orderList()
    expect(headersOf()['X-Frappe-CSRF-Token']).toBeUndefined()
  })

  it('the name is the one Frappe reads', async () => {
    fetchMock.mockResolvedValueOnce(answer(ok({})))
    await api.logout()
    // Spelled out rather than compared to a constant: a rename on either side is the kind of
    // change that fails nothing and protects nothing.
    expect(Object.keys(headersOf())).toContain('X-Frappe-CSRF-Token')
  })
})

describe('signing out', () => {
  it('lets the token be cleared', async () => {
    fetchMock.mockResolvedValueOnce(answer(ok({ user: 'rep@x', csrf_token: 'TOKEN-4' })))
    await api.login('rep@x', 'secret', 'device-1')

    setCsrfToken(null)
    fetchMock.mockReset()
    fetchMock.mockResolvedValueOnce(answer(ok({})))
    await api.logout()
    expect(headersOf()['X-Frappe-CSRF-Token']).toBeUndefined()
  })
})
