import { ref } from 'vue'
import { api, ApiError } from '../api/client'
import { db, deviceUuid, getMeta, setMeta, rememberName } from '../db'
import { enqueue } from '../sync/outbox'
import * as photoQueue from '../sync/photos'
import * as dayStore from './day'
import { flushSoon } from '../sync/pinger'

// The visit the rep is standing in, if any.
export const activeVisit = ref(null)

/** A check-in refused because the rep has not checked out of the last shop.
 *
 * Carries that visit, so the screen can offer the way back to it rather than only naming it.
 */
export class OpenVisitError extends Error {
  constructor(visit) {
    super(`You are still checked in at ${visit.outletName || visit.outlet}. ` +
          `Check out from there first.`)
    this.code = 'VISIT_OPEN_ELSEWHERE'
    this.visit = visit
  }
}

function isOffline(e) {
  return e instanceof ApiError && e.code === 'OFFLINE'
}

function nowStamp() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
         `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function todayStamp() {
  return nowStamp().slice(0, 10)
}

// --------------------------------------------------------------------------- forms cache

/** Fetch the survey definitions and keep them. Called on login and after each pull. */
export async function refreshForms() {
  try {
    const data = await api.checklistForms()
    await setMeta('checklistForms', data.templates || [])
    return data.templates
  } catch (e) {
    if (isOffline(e)) return await getMeta('checklistForms', [])
    throw e
  }
}

export async function refreshReasons() {
  try {
    const data = await api.noOrderReasons()
    await setMeta('noOrderReasons', data.reasons || [])
    return data.reasons
  } catch (e) {
    if (isOffline(e)) return await getMeta('noOrderReasons', [])
    throw e
  }
}

export async function noOrderReasons() {
  return (await getMeta('noOrderReasons', [])) || []
}

/** Build the questions for a shop from the cached definitions.
 *
 * Only a provisional answer: this matches on channel and class but not on territory, which
 * the phone cannot evaluate because a territory is a tree and the phone holds only leaves.
 * It does not need to be exact - the server re-snapshots the whole checklist when the visit
 * lands, so this decides what the rep is *shown*, not what is ultimately recorded.
 */
async function buildChecklist(outlet) {
  const templates = (await getMeta('checklistForms', [])) || []
  const today = todayStamp()
  const rows = []

  for (const tpl of templates) {
    if (tpl.effective_from && tpl.effective_from > today) continue
    if (tpl.channel && tpl.channel !== outlet.channel) continue
    if (tpl.outlet_class && tpl.outlet_class !== outlet.outlet_class) continue
    if (tpl.applies_to === 'New Outlet Only' && outlet.approval_status === 'Approved') continue

    for (const q of tpl.questions || []) {
      rows.push({
        question_code: q.question_code,
        question: q.question,
        answer_type: q.answer_type,
        options: q.options || [],
        is_required: q.is_required,
        sequence: q.sequence,
        depends_on_code: q.depends_on_code,
        depends_on_value: q.depends_on_value,
        min_value: q.min_value,
        max_value: q.max_value,
        help_text: q.help_text,
        photo_required: q.photo_required,
        template: tpl.name,
        template_version: tpl.version,
        answer: null,
        answer_number: 0,
        is_answered: false,
      })
    }
  }
  return rows.sort((a, b) => (a.sequence || 0) - (b.sequence || 0))
}

// --------------------------------------------------------------------------- check in

/** The visit to come back to after an app restart.
 *
 * `.first()` on an index returns an arbitrary row, so a phone that somehow held two open
 * visits could resume the shop the rep had already walked out of. The newest wins, and any
 * older one is closed the way `check_in` closes a forgotten visit on the server.
 */
export async function resume() {
  const open = await db.visits.where('state').equals('open').toArray()
  if (!open.length) {
    activeVisit.value = null
    return null
  }
  open.sort((a, b) => String(b.checkInTime).localeCompare(String(a.checkInTime)))
  for (const stale of open.slice(1)) {
    await db.visits.update(stale.clientUuid, { state: 'abandoned' })
  }
  activeVisit.value = open[0]
  await reconcileOpen()
  return activeVisit.value
}

/**
 * Ask the server whether the visit this phone thinks is open is still open there.
 *
 * It can be closed on the server and open here: a day auto-closed takes its visits with it, and
 * `check_in` closes one on the deliberate override. Nothing used to ask - `api.currentVisit`
 * existed and was called from nowhere - so the phone kept showing a visit that no longer
 * existed, offered a check-out that quietly did nothing, and refused the next check-in because
 * of it. A rep standing in the next shop could not get in.
 *
 * Offline the local answer stands, which is the whole point of holding it. A visit created
 * offline has no server name yet and is left alone - the server has never heard of it.
 */
async function reconcileOpen() {
  const mine = activeVisit.value
  if (!mine || !mine.serverName) return
  try {
    const server = await api.currentVisit()
    if (server.open && server.visit === mine.serverName) return
    await db.visits.update(mine.clientUuid, { state: 'closed' })
    activeVisit.value = null
  } catch {
    // No signal, or the server would not say. Their own record stands.
  }
}

export async function checkIn(outlet, { fix = {}, deviationNote = null,
                                        checkInPhoto = null, closeOpen = false } = {}) {
  // Checking out is the way a visit ends. A second check-in used to close the first one on the
  // server, silently, stamped "No Order" and short - so a rep could walk a row of shops from the
  // list leaving empty visits behind that still counted towards coverage.
  //
  // Refused here as well as on the server, and the local check is the one that matters: offline
  // the server is not reachable, the visit queues with `created_offline` set, and the server
  // honours those rather than rejecting work the rep really did. So this is the only thing
  // standing between a stray tap and a closed visit.
  const open = activeVisit.value
  if (open && open.outlet !== outlet.name && !closeOpen) throw new OpenVisitError(open)

  const clientUuid = crypto.randomUUID()
  // Which day this visit belongs to. Offline that is the queued day's client id, which
  // sync._apply resolves through depends_on once the day itself lands.
  const dayRef = dayStore.openDay.value?.day_start || null
  const local = {
    clientUuid,
    serverName: null,
    dayStart: dayRef,
    outlet: outlet.name,
    outletName: outlet.outlet_name || outlet.name,
    visitDate: todayStamp(),
    checkInTime: nowStamp(),
    checkInLatitude: fix.latitude ?? null,
    checkInLongitude: fix.longitude ?? null,
    accuracyM: fix.accuracy_m ?? null,
    // Held on the phone too, so a visit taken with no signal still carries its photo when the
    // outbox finally sends it.
    checkInPhoto,
    locationProvider: fix.location_provider ?? null,
    isMockLocation: fix.is_mock_location ? 1 : 0,
    deviationNote,
    checklist: await buildChecklist(outlet),
    tasks: [],
    remarks: '',
    outcome: null,
    noOrderReason: null,
    distanceM: null,
    isGeoFenceBreach: false,
    minVisitMinutes: 0,
    createdOffline: 0,
    state: 'open',
  }

  try {
    const device = await deviceUuid()
    const server = await api.checkIn(device, {
      outlet: outlet.name,
      client_uuid: clientUuid,
      check_in_time: local.checkInTime,
      latitude: local.checkInLatitude,
      longitude: local.checkInLongitude,
      accuracy_m: local.accuracyM,
      location_provider: local.locationProvider,
      is_mock_location: local.isMockLocation,
      deviation_note: deviationNote,
      // A photo at the counter, where the site asks for one. A data URL on the way out; the
      // server turns it into a real file and keeps the path.
      check_in_photo: checkInPhoto,
      // Only ever set after the rep has been told on screen what it closes.
      close_open_visit: closeOpen ? 1 : 0,
    })
    local.serverName = server.visit
    local.distanceM = server.distance_from_outlet_m
    local.isGeoFenceBreach = server.is_geo_fence_breach
    local.minVisitMinutes = server.min_visit_minutes || 0
    local.tasks = server.tasks || []
    // The server's checklist wins: it is the one that will actually be recorded. The cached
    // definitions only carry the rendering rules, so those are merged back in.
    if (server.checklist?.length) local.checklist = mergeSpecs(server.checklist, local.checklist)
    await rememberName(clientUuid, 'FieldMate Visit', server.visit)
  } catch (e) {
    if (!isOffline(e)) throw e
    local.createdOffline = 1
  }

  await db.visits.put(plain(local))
  activeVisit.value = local
  // Walking into a shop is one of the two moments the desk looks the trail up. Sending the
  // fixes now rather than at the next batch window is what makes the trail arrive while the
  // rep is still standing there.
  flushSoon().catch(() => {})
  return local
}

function mergeSpecs(serverRows, localRows) {
  const specs = new Map(localRows.map((r) => [r.question_code, r]))
  return serverRows.map((r) => ({ ...(specs.get(r.question_code) || {}), ...r }))
}

function plain(value) {
  return JSON.parse(JSON.stringify(value))
}

// --------------------------------------------------------------------------- during

/** Persist locally first, then tell the server if it is reachable.
 *
 * Local-first is the whole point: a rep who walks into a cold spot mid-survey keeps every
 * answer they have given, and the server catches up when the signal does.
 */
export async function saveProgress() {
  const visit = activeVisit.value
  if (!visit) return
  await db.visits.put(plain(visit))

  if (!visit.serverName) return { pending: true }
  try {
    await api.saveVisitTasks(visit.serverName, {
      answers: visit.checklist
        .filter((q) => q.is_answered)
        .map((q) => ({
          question_code: q.question_code,
          answer: q.answer,
          answer_number: q.answer_number,
        })),
      tasks: visit.tasks.map((t) => ({ task: t.task, status: t.status, note: t.note })),
      remarks: visit.remarks,
    })
    return { pending: false }
  } catch (e) {
    if (isOffline(e)) return { pending: true }
    throw e
  }
}

/** Record that an order came out of this visit.
 *
 * The cart is emptied the moment it is submitted, so without this the visit hub would go back to
 * reading "no order yet" thirty seconds after the rep booked one, and the check-out screen would
 * ask them to pick an outcome the app already knows. Kept on the visit rather than looked up,
 * because the order may still be sitting in the outbox with no server name at all.
 */
export async function recordOrder({ clientUuid, name = null, net = 0, offline = false }) {
  const visit = activeVisit.value
  if (!visit) return
  visit.order = { clientUuid, name, net, offline, at: new Date().toISOString() }
  await saveProgress()
  return visit.order
}

export function answer(questionCode, { answer = null, answerNumber = null } = {}) {
  const visit = activeVisit.value
  if (!visit) return
  const row = visit.checklist.find((q) => q.question_code === questionCode)
  if (!row) return
  row.answer = answer
  row.answer_number = answerNumber ?? 0
  // Recorded rather than inferred: zero facings is an answer, and an empty Float is not.
  row.is_answered = answer !== null && answer !== '' ? true : answerNumber !== null
}

/** Questions whose trigger has not been met are not shown and not required. */
export function visibleQuestions(visit) {
  if (!visit) return []
  const given = new Map(visit.checklist.map((q) => [q.question_code, q]))
  return visit.checklist.filter((q) => {
    if (!q.depends_on_code) return true
    const parent = given.get(q.depends_on_code)
    if (!parent || !parent.is_answered) return false
    if (q.depends_on_value === null || q.depends_on_value === undefined) return true
    return String(parent.answer) === String(q.depends_on_value)
  })
}

export function unansweredRequired(visit) {
  return visibleQuestions(visit).filter((q) => q.is_required && !q.is_answered)
}

export async function addPhoto({ dataUrl, thumb, purpose, caption, kb, fix }) {
  const visit = activeVisit.value
  if (!visit) return
  await photoQueue.queue(visit.clientUuid, { dataUrl, thumb, purpose, caption, kb, fix })
  visit.photoCount = (visit.photoCount || 0) + 1
  await db.visits.put(plain(visit))
}

// --------------------------------------------------------------------------- check out

export async function checkOut({ outcome, noOrderReason = null, remarks = null, fix = {},
                                 nextVisitDate = null } = {}) {
  const visit = activeVisit.value
  if (!visit) throw new Error('No visit is open.')

  visit.outcome = outcome
  visit.noOrderReason = noOrderReason
  if (remarks !== null) visit.remarks = remarks
  visit.checkOutTime = nowStamp()
  visit.checkOutLatitude = fix.latitude ?? null
  visit.checkOutLongitude = fix.longitude ?? null
  visit.state = 'closed'

  const answers = visit.checklist
    .filter((q) => q.is_answered)
    .map((q) => ({
      question_code: q.question_code,
      answer: q.answer,
      answer_number: q.answer_number,
    }))

  if (visit.serverName) {
    try {
      const device = await deviceUuid()
      // eslint-disable-next-line no-unused-vars
      const closed = await api.checkOut(device, visit.serverName, {
        visit_outcome: outcome,
        no_order_reason: noOrderReason,
        remarks: visit.remarks,
        next_visit_date: nextVisitDate,
        latitude: visit.checkOutLatitude,
        longitude: visit.checkOutLongitude,
        check_out_time: visit.checkOutTime,
        answers,
      })
      visit.durationMinutes = closed.duration_minutes
      visit.isShortVisit = closed.is_short_visit
      await finish(visit)
      return closed
    } catch (e) {
      // A validation error is the rep's to fix now - a missing reason, an unanswered
      // question - so it is raised and the visit stays open. Anything else (the network,
      // the server, an expired session) falls through to the queue rather than stranding
      // a rep with a finished visit and nowhere to put it.
      if (e instanceof ApiError && e.code === 'VALIDATION_FAILED') {
        visit.state = 'open'
        visit.checkOutTime = null
        throw e
      }
    }
  }

  // Offline, or the connection dropped between check-in and check-out: queue the whole visit
  // as one complete record. docstatus 1 asks the server to submit it, because an offline day
  // that lands as a pile of drafts is a day of work that no report will count.
  await enqueue('FieldMate Visit', {
    docstatus: 1,
    day_start: visit.dayStart || undefined,
    outlet: visit.outlet,
    visit_date: visit.visitDate,
    check_in_time: visit.checkInTime,
    check_in_latitude: visit.checkInLatitude,
    check_in_longitude: visit.checkInLongitude,
    check_in_accuracy_m: visit.accuracyM,
    location_provider: visit.locationProvider,
    is_mock_location: visit.isMockLocation,
    check_in_photo: visit.checkInPhoto || undefined,
    check_out_time: visit.checkOutTime,
    check_out_latitude: visit.checkOutLatitude,
    check_out_longitude: visit.checkOutLongitude,
    visit_outcome: outcome,
    no_order_reason: noOrderReason,
    deviation_note: visit.deviationNote,
    remarks: visit.remarks,
    created_offline: 1,
    checklist_answers: visit.checklist
      .filter((q) => q.is_answered)
      .map((q) => ({
        question_code: q.question_code,
        answer: q.answer,
        answer_number: q.answer_number,
        is_answered: 1,
      })),
  }, { clientUuid: visit.clientUuid, dependsOn: visit.dayStart || null })

  await finish(visit)
  return { offline: true }
}

async function finish(visit) {
  await db.visits.put(plain(visit))
  activeVisit.value = null
  photoQueue.drain().catch(() => {})
  // And walking out is the other one.
  flushSoon().catch(() => {})
}

export async function todaysVisits() {
  const today = todayStamp()
  await reconcileToday(today)
  return db.visits.where('visitDate').equals(today).toArray()
}

/**
 * Drop local visits the server no longer has.
 *
 * This list is read straight out of IndexedDB and never asked the server anything, so a visit
 * cancelled in the office stayed on the phone for ever. A rep whose day was cancelled and who
 * started again saw every shop still marked visited, the route showed as done, and the next shop
 * the app offered was the wrong one. Reported from the field exactly that way.
 *
 * **Only rows this phone has already sent.** A visit created offline has no server name: the
 * server has never heard of it, so its absence from the answer says nothing, and deleting it would
 * throw away the rep's own unsent work — which is the one thing this app must never do.
 *
 * Offline, what the phone holds stands. That is the whole point of holding it, and a dropped link
 * is not evidence that anything was cancelled.
 */
async function reconcileToday(date) {
  let known
  try {
    const answer = await api.visitHistory(date)
    // `visit.history` names the id `visit`, and it leaves cancelled visits out — which is what
    // makes this reconcile work at all.
    known = new Set((answer.visits || answer || []).map((row) => row.visit || row.name))
  } catch {
    return
  }

  const mine = await db.visits.where('visitDate').equals(date).toArray()
  for (const visit of mine) {
    if (!visit.serverName) continue
    if (known.has(visit.serverName)) continue
    await db.visits.delete(visit.clientUuid)
  }
}
