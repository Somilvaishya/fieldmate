import { ref } from 'vue'
import { api, ApiError } from '../api/client'
import { deviceUuid, getMeta, setMeta, rememberName } from '../db'
import { enqueue } from '../sync/outbox'
import * as photoQueue from '../sync/photos'
import * as pinger from '../sync/pinger'

export const openDay = ref(null)
export const plannedToday = ref(null)

// Has anybody actually asked the server yet this session?
//
// `openDay` starts as null, and null is also what "no day is open" looks like - so a screen
// reading it before anything has loaded cannot tell "not started" from "not known yet". Check-in
// read it directly and told reps their day had not started when it had; the rep had come from
// Beats rather than Today, and Today was the only screen that ever refreshed.
export const loaded = ref(false)
let inFlight = null

function offline(e) {
  return e instanceof ApiError && e.code === 'OFFLINE'
}

function stamp(d = new Date()) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
         `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** What the server says, falling back to what this phone last knew. */
export async function refresh() {
  try {
    const data = await api.dayCurrent()
    openDay.value = data.open ? data : null
    plannedToday.value = data.planned || null
    await setMeta('openDay', openDay.value)
    // Kept too, or Start Day reads "No route planned" the moment a rep loses signal -
    // which is exactly where they are when they start.
    await setMeta('plannedToday', plannedToday.value)
    if (openDay.value && !pinger.isRunning()) pinger.start()
    if (!openDay.value) pinger.stop()
    loaded.value = true
    return { offline: false }
  } catch (e) {
    if (offline(e)) {
      // Only today's day counts. A cached day from yesterday came back as open on a phone with
      // no signal, so the Today screen said the day had started while the server - which had
      // closed it at day end - refused every check-in with "start your day first". The rep was
      // stuck with two screens telling them opposite things and no way through.
      const cached = await getMeta('openDay')
      openDay.value = cached && cached.day_date === stamp().slice(0, 10) ? cached : null
      if (cached && !openDay.value) await setMeta('openDay', null)
      plannedToday.value = await getMeta('plannedToday')
      if (openDay.value && !pinger.isRunning()) pinger.start()
      if (!openDay.value) pinger.stop()
      loaded.value = true
      return { offline: true }
    }
    throw e
  }
}

/** Make sure the day is known, once, without every screen having to think about it.
 *
 * Reads the phone's own copy first so a screen has something true to show immediately, then
 * confirms with the server. Concurrent callers share one request rather than each firing their
 * own - two screens mounting together used to mean two `day.current` calls on a market
 * connection.
 */
export async function ensure() {
  if (loaded.value) return { cached: true }
  if (inFlight) return inFlight

  // The cached day, but only if it is today's. A yesterday left in storage reads as open and
  // puts the phone back in the state where it says the day has started and the server refuses
  // every check-in.
  const cached = await getMeta('openDay')
  if (cached && cached.day_date === stamp().slice(0, 10) && !openDay.value) {
    openDay.value = cached
  }

  inFlight = refresh()
    .catch(() => ({ offline: true }))
    .finally(() => { inFlight = null })
  return inFlight
}

/** Open the day. Works with no signal: the record is queued and the rep carries on.
 *
 * Before this, an offline start threw away the selfie, the fix and the odometer, and every
 * check-in afterwards was refused because the server had no open day. The queued day keeps
 * its client id, and each visit references that id - `sync._apply` resolves it through
 * `depends_on` when the batch lands, so a whole offline day arrives intact and in order.
 */
export async function start(payload) {
  const device = await deviceUuid()
  const clientUuid = crypto.randomUUID()
  const body = { ...payload, client_uuid: clientUuid, device_id: device }

  try {
    const data = await api.dayStart(device, body)
    openDay.value = data
    loaded.value = true
    await rememberName(clientUuid, 'FieldMate Day', data.day)
    await setMeta('openDay', data)
    pinger.start()
    // The trail document should exist on the server while the rep is still looking at the
    // screen that started the day, not ten minutes later (see sync/pinger.js).
    pinger.flush().catch(() => {})
    return data
  } catch (e) {
    if (!offline(e)) throw e
  }

  const local = {
    day: clientUuid,                // the client id stands in until the server names it
    day_date: stamp().slice(0, 10),
    started_at: stamp(),
    planned_beat: plannedToday.value?.beat || null,
    planned_beat_name: plannedToday.value?.beat_name || null,
    journey_plan: plannedToday.value?.journey_plan || null,
    is_mock_location: !!payload.is_mock_location,
    created_offline: 1,
    created: true,
  }

  await enqueue('FieldMate Day', {
    docstatus: 1,
    day_date: local.day_date,
    start_time: local.started_at,
    status: 'Open',
    latitude: payload.latitude ?? null,
    longitude: payload.longitude ?? null,
    accuracy_m: payload.accuracy_m ?? null,
    location_provider: payload.location_provider ?? null,
    is_mock_location: payload.is_mock_location ? 1 : 0,
    selfie: payload.selfie || undefined,
    odometer_start: payload.odometer_start ?? null,
    device_id: device,
    created_offline: 1,
  }, { clientUuid })

  openDay.value = local
  loaded.value = true
  await setMeta('openDay', local)
  pinger.start()
  return local
}

/** Close the day. Also works with no signal. */
export async function end(payload) {
  const device = await deviceUuid()
  // The close carries its own id, so a retry on a bad connection is recognised as the same
  // close rather than applied twice. Generated once, for whichever path the day takes out.
  const endUuid = crypto.randomUUID()
  const day = openDay.value?.day || null
  await pinger.flush()          // send the trail before the server computes distance from it

  // Yesterday's thumbnails. They are kept so a rep can see this morning's photos after they
  // upload; a week of them on a phone nobody clears is a different thing. The full images went
  // days ago - this is a few kilobytes each.
  photoQueue.forgetSentBefore(Date.now() - 2 * 24 * 60 * 60 * 1000).catch(() => {})

  try {
    const data = await api.dayEnd(device, { ...payload, client_uuid: endUuid })
    openDay.value = null
    await setMeta('openDay', null)
    pinger.stop()
    return data
  } catch (e) {
    if (!offline(e)) throw e
  }

  // A close, not a second document: `closes` names the day this finishes, by server name if
  // the day was opened online and by its own client id if the open is still in the outbox.
  // The server resolves either. No `docstatus` - the day was submitted the morning it opened.
  await enqueue('FieldMate Day', {
    closes: day,
    end_time: stamp(),
    end_latitude: payload.latitude ?? null,
    end_longitude: payload.longitude ?? null,
    end_accuracy_m: payload.accuracy_m ?? null,
    odometer_end: payload.odometer_end ?? null,
    remarks: payload.remarks || null,
  }, { clientUuid: endUuid, dependsOn: day })

  openDay.value = null
  await setMeta('openDay', null)
  pinger.stop()
  return { offline: true }
}
