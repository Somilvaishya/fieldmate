// The only way the PWA talks to the server. Every call goes to a fieldmate.api.* method -
// never frappe.client.*, never an erpnext method. That restriction is what lets the server
// change underneath us across Frappe v15/v16/v17 without breaking builds already in the field.

const BASE = '/api/method/fieldmate.api.'

export class ApiError extends Error {
  constructor(code, message, status) {
    super(message)
    this.code = code
    this.status = status
  }
}

async function call(method, params = {}, { post = false } = {}) {
  const url = BASE + method
  const opts = {
    method: post ? 'POST' : 'GET',
    headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    credentials: 'same-origin',
  }

  let target = url
  if (post) {
    opts.headers['Content-Type'] = 'application/json'
    opts.body = JSON.stringify(params)
  } else {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null)
    ).toString()
    if (qs) target += '?' + qs
  }

  let res
  try {
    res = await fetch(target, opts)
  } catch {
    // fetch rejects with a bare TypeError("Failed to fetch") when there is no connection.
    // That string is a browser internal, not something to show a rep standing in a market.
    throw new ApiError('OFFLINE', 'No connection. Your work is saved on this phone.', 0)
  }

  let body
  try {
    body = await res.json()
  } catch {
    throw new ApiError('INTERNAL', 'The server sent something we could not read.', res.status)
  }

  // Frappe-level failures (not our envelope) arrive as { exception, exc_type }.
  // Returning those as data is how a signed-out phone ended up rendering a card of blanks.
  if (body && (body.exc_type || body.exception)) {
    const authish = ['PermissionError', 'AuthenticationError', 'SessionExpired']
    throw new ApiError(
      authish.includes(body.exc_type) ? 'AUTH_REQUIRED' : 'INTERNAL',
      authish.includes(body.exc_type) ? 'Please sign in again.' : 'Something went wrong.',
      res.status
    )
  }
  if (res.status === 401 || res.status === 403) {
    throw new ApiError('AUTH_REQUIRED', 'Please sign in again.', res.status)
  }

  // Frappe wraps whitelisted return values in { message: ... }
  const payload = body.message ?? body
  if (payload && payload.ok === false) {
    throw new ApiError(payload.code, payload.message, res.status)
  }
  return payload?.data ?? payload
}

export const api = {
  login: (usr, pwd, deviceUuid, extra = {}) =>
    call('auth.login', { usr, pwd, device_uuid: deviceUuid, ...extra }, { post: true }),
  bootstrap: () => call('auth.bootstrap'),
  registerDevice: (deviceUuid, extra = {}) =>
    call('sync.register_device', { device_uuid: deviceUuid, ...extra }, { post: true }),
  pull: (deviceUuid, since) => call('sync.pull', { device_uuid: deviceUuid, since }),
  push: (deviceUuid, batchUuid, records, appVersion) =>
    call('sync.push',
      { device_uuid: deviceUuid, batch_uuid: batchUuid, records, app_version: appVersion },
      { post: true }),
  batchStatus: (batchUuid) => call('sync.status', { batch_uuid: batchUuid }),
}
