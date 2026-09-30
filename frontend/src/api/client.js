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

// A stalled link is worse than a dead one: fetch never settles, so a button stays disabled
// and the rep is stuck with no way forward. Long enough for a photo on a slow uplink,
// short enough that nobody stares at a frozen screen.
const TIMEOUT_MS = 45_000

async function call(method, params = {}, { post = false } = {}) {
  const url = BASE + method
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  const opts = {
    method: post ? 'POST' : 'GET',
    headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' },
    credentials: 'same-origin',
    signal: controller.signal,
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
  } catch (e) {
    // fetch rejects with a bare TypeError("Failed to fetch") when there is no connection.
    // That string is a browser internal, not something to show a rep standing in a market.
    // A timeout is treated the same way: from the rep's side a link that never answers and
    // a link that is not there are the same problem, and both keep the work on the phone.
    throw new ApiError(
      'OFFLINE',
      e && e.name === 'AbortError'
        ? 'The connection is too slow to finish that. Your work is saved on this phone.'
        : 'No connection. Your work is saved on this phone.',
      0,
    )
  } finally {
    clearTimeout(timer)
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
  // Frappe wraps whitelisted return values in { message: ... }
  const payload = body.message ?? body

  // Our own envelope is read BEFORE the status code. A 403 from FieldMate carries a
  // sentence a rep can act on - "That shop is not in your territory" - and rewriting every
  // 403 into "Please sign in again" both hid that and bounced the rep out to the login
  // screen over a permission problem that signing in again cannot fix.
  if (payload && payload.ok === false) {
    throw new ApiError(payload.code, payload.message, res.status)
  }
  if (res.status === 401 || res.status === 403) {
    throw new ApiError('AUTH_REQUIRED', 'Please sign in again.', res.status)
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

  outlets: (q, beat) => call('outlet.search', { q, beat, limit: 200 }),
  outlet: (name) => call('outlet.detail', { outlet: name }),
  createOutlet: (payload) => call('outlet.create', { payload }, { post: true }),
  updateOutlet: (name, payload) => call('outlet.update', { outlet: name, payload }, { post: true }),

  dayCurrent: () => call('day.current'),
  dayStart: (deviceUuid, payload) =>
    call('day.start', { device_uuid: deviceUuid, payload }, { post: true }),
  dayEnd: (deviceUuid, payload) =>
    call('day.end', { device_uuid: deviceUuid, payload }, { post: true }),
  uploadPings: (deviceUuid, pings) =>
    call('day.trail_upload', { device_uuid: deviceUuid, pings }, { post: true }),
  todayBeat: () => call('day.today'),
  beatOutlets: (beat) => call('day.outlets', { beat }),
  daySummary: (date) => call('day.summary', { date }),
  myBeats: () => call('day.my_beats'),

  checkIn: (deviceUuid, payload) =>
    call('visit.check_in', { device_uuid: deviceUuid, payload }, { post: true }),
  currentVisit: () => call('visit.current'),
  saveVisitTasks: (visit, payload) =>
    call('visit.save_tasks', { visit, payload }, { post: true }),
  // The device id is not optional: `visit.upload_photo` is declared `require_device=True`, so
  // without it the endpoint refuses before it reads the photo. It was missing here, which meant
  // every shelf photo ever taken failed and then retried until the queue gave up on it.
  uploadPhoto: (deviceUuid, visit, payload) =>
    call('visit.upload_photo', { device_uuid: deviceUuid, visit, payload }, { post: true }),
  checkOut: (deviceUuid, visit, payload) =>
    call('visit.check_out', { device_uuid: deviceUuid, visit, payload }, { post: true }),
  visitHistory: (date) => call('visit.history', { date }),
  checklistForms: () => call('visit.forms'),
  noOrderReasons: () => call('visit.no_order_reasons'),

  // ------------------------------------------------------------------- Phase 4: the order
  //
  // Note what is NOT here: nothing takes a price list, a field user or a rate. Every one of those
  // is resolved on the server from the session, because a device that could name its own price
  // list could quote the whole cart off whichever one is cheapest, and a device that could name a
  // rep could read another rep's shops and another rep's order book. A stolen phone is the
  // ordinary way that happens rather than the exotic one.

  // Everything this shop may be sold, priced, plus the last order's quantities. One call, because
  // the cart screen needs both before it can draw anything and a second round trip on a market
  // uplink is a second chance for the rep to give up on it.
  catalogue: (outlet) => call('catalogue.items', { outlet }),

  // The repeat-order prefill. There is no endpoint of its own for it - `catalogue.items` carries
  // `last_order` deliberately, for the reason above - so this is the same call reading one key out
  // of the payload. Callers that already hold a cached catalogue should read `last_order` off that
  // instead of pulling four hundred priced SKUs down to fill in eight quantities.
  catalogueLastOrder: (outlet) =>
    call('catalogue.items', { outlet }).then((data) => data.last_order),

  // Fresh rates for a cart that already exists. POSTed rather than sent as a query string: a
  // forty-line cart of long SKU codes runs past what some proxies will carry in a URL, and a
  // truncated cart re-prices as a different cart. `items` is [{item_code, qty}] in BASE units,
  // because that is what a quantity break on Item Price is measured in.
  cataloguePrices: (outlet, items) => call('catalogue.prices', { outlet, items }, { post: true }),

  // The compiled specs for this shop, for the phone to cache and evaluate against with no signal.
  // `skipped` comes back beside them: a scheme a manager has to fix must not look live in Desk and
  // absent in the field for as long as nobody happens to notice.
  schemesFor: (outlet) => call('scheme.applicable', { outlet }),

  // The same specs run on the server against server prices - the figure of record. The phone's own
  // answer is what the rep said out loud; docs/SCHEME_SPEC.md allows the two no divergence, so
  // where they differ one of the two engines is wrong and we would like to know which.
  // `lines` is [{item_code, qty, uom}].
  schemeEvaluate: (outlet, lines) => call('scheme.evaluate', { outlet, lines }, { post: true }),

  // fieldmate.api.order.* — written by another workstream and not on disk at the time these were
  // added, so the parameter names below are this client's half of the contract rather than
  // something read off the server. `payload` is the FieldMate Order as the store builds it (doc
  // field names, money in rupees); `order` is the document name. If the server lands on different
  // names, this is the one file that changes.
  //
  // estimate books nothing at all: it is submit's arithmetic without the document, for a review
  // screen that wants the server's total before the rep commits to it.
  orderEstimate: (payload) => call('order.estimate', { payload }, { post: true }),
  orderSubmit: (deviceUuid, payload) =>
    call('order.submit', { device_uuid: deviceUuid, payload }, { post: true }),
  orderList: (filters = {}) => call('order.list_mine', { limit: 50, ...filters }),
  orderDetail: (name) => call('order.detail', { order: name }),
  orderCancel: (name, reason) => call('order.cancel', { order: name, reason }, { post: true }),

  // fieldmate.api.stock.* — the shop count and the van day.
  //
  // The count sheet carries the previous count with it rather than offering it on a second call.
  // A rep standing at a shelf with no signal would otherwise either wait for a round trip or
  // count blind, and counting blind makes "same as last time" impossible to offer.
  stockSheet: (outlet) => call('stock.sheet', { outlet }),
  stockSave: (payload) => call('stock.save', { payload }, { post: true }),

  // The van is the distributor's stock, not ours (ADR-024), so none of these post anything.
  vanLoad: (on) => call('stock.van_load', { on }),
  vanLoadSave: (payload) => call('stock.save_van_load', { payload }, { post: true }),
  // Computed and not saved: the rep opens this to see where he stands before entering the one
  // number that is his to enter.
  vanSettlement: (on) => call('stock.settlement', { on }),
  vanSettlementSave: (payload) => call('stock.save_settlement', { payload }, { post: true }),

  // fieldmate.api.collection.* — money taken at a counter.
  //
  // None of these post anything. A shop's cash belongs to its distributor and never reaches our
  // ledger at all; a distributor's does, but only when somebody at our end confirms the deposit
  // (ADR-025). There is deliberately no endpoint here that a rep can call to post a payment.
  outstanding: (outlet) => call('collection.outstanding', { outlet }),
  collectionCreate: (payload) => call('collection.create', { payload }, { post: true }),
  collectionsMine: (status) => call('collection.list_mine', { status, limit: 50 }),
  cashInHand: () => call('collection.in_hand'),
  distributors: () => call('collection.distributors'),
  depositDeclare: (payload) => call('collection.deposit', { payload }, { post: true }),

  // ------------------------------------------------------- Phase 7: targets and expenses
  //
  // Note what is missing again: none of these takes a rep. An endpoint that accepted one would
  // be an endpoint that could be asked for somebody else's numbers, and a salary figure is the
  // one thing on this app nobody may read sideways.
  //
  // `myPerformance` is one call rather than two because the screen shows targets and incentive
  // together, and two round trips on a phone in a market is one too many.
  myPerformance: (asOn) => call('target.achievement', { as_on: asOn }),
  myTargets: (asOn) => call('target.my_targets', { as_on: asOn }),
  myPayouts: (limit) => call('target.my_payouts', { limit }),

  // The distance comes back from the server, computed from the GPS trail. The phone never
  // states its own mileage - a device that could would be a device that could invent it, and
  // this is the one figure on the app that turns straight into money.
  expenseEstimate: (claimDate, expenseType) =>
    call('expense.estimate', { claim_date: claimDate, expense_type: expenseType }),
  expenseCreate: (payload) => call('expense.create_claim', { payload }, { post: true }),
  expensesMine: (limit) => call('expense.my_claims', { limit }),

  // ------------------------------------------------------------- Phase 8: the numbers
  //
  // `dayCockpit` is the one call in the app that measures live rather than reading the
  // materialised snapshot. The rep is looking at what they did in the last hour, and last
  // night's row is the one figure they would immediately know to be wrong. Everything with a
  // month in it reads the table.
  dayCockpit: (onDate) => call('dashboard.rep_today', { on_date: onDate }),
  monthDashboard: (fromDate, toDate) =>
    call('dashboard.rep_month', { from_date: fromDate, to_date: toDate }),
  kpiTrend: (days) => call('dashboard.rep_trend', { days }),
}
