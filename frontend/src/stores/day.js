import { ref } from 'vue'
import { api, ApiError } from '../api/client'
import { deviceUuid, getMeta, setMeta, rememberName } from '../db'
import { enqueue } from '../sync/outbox'
import * as pinger from '../sync/pinger'

export const openDay = ref(null)
export const plannedToday = ref(null)

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
    return { offline: false }
  } catch (e) {
    if (offline(e)) {
      openDay.value = await getMeta('openDay')
      plannedToday.value = await getMeta('plannedToday')
      if (openDay.value && !pinger.isRunning()) pinger.start()
      return { offline: true }
    }
    throw e
  }
}

/** Open the day. Works with no signal: the record is queued and the rep carries on.
 *
 * Before this, an offline start threw away the selfie, the fix and the odometer, and every
 * check-in afterwards was refused because the server had no open day. The queued Day Start
 * keeps its client id, and each visit references that id - `sync._apply` resolves it through
 * `depends_on` when the batch lands, so a whole offline day arrives intact and in order.
 */
export async function start(payload) {
  const device = await deviceUuid()
  const clientUuid = crypto.randomUUID()
  const body = { ...payload, client_uuid: clientUuid, device_id: device }

  try {
    const data = await api.dayStart(device, body)
    openDay.value = data
    await rememberName(clientUuid, 'FieldMate Day Start', data.day_start)
    await setMeta('openDay', data)
    pinger.start()
    return data
  } catch (e) {
    if (!offline(e)) throw e
  }

  const local = {
    day_start: clientUuid,          // the client id stands in until the server names it
    day_date: stamp().slice(0, 10),
    started_at: stamp(),
    planned_beat: plannedToday.value?.beat || null,
    planned_beat_name: plannedToday.value?.beat_name || null,
    journey_plan: plannedToday.value?.journey_plan || null,
    is_mock_location: !!payload.is_mock_location,
    created_offline: 1,
    created: true,
  }

  await enqueue('FieldMate Day Start', {
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
  await setMeta('openDay', local)
  pinger.start()
  return local
}

/** Close the day. Also works with no signal. */
export async function end(payload) {
  const device = await deviceUuid()
  await pinger.flush()          // send the trail before the server computes distance from it

  try {
    const data = await api.dayEnd(device, payload)
    openDay.value = null
    await setMeta('openDay', null)
    pinger.stop()
    return data
  } catch (e) {
    if (!offline(e)) throw e
  }

  await enqueue('FieldMate Day End', {
    docstatus: 1,
    day_start: openDay.value?.day_start || null,
    end_time: stamp(),
    latitude: payload.latitude ?? null,
    longitude: payload.longitude ?? null,
    accuracy_m: payload.accuracy_m ?? null,
    odometer_end: payload.odometer_end ?? null,
    remarks: payload.remarks || null,
    created_offline: 1,
  }, { dependsOn: openDay.value?.day_start || null })

  openDay.value = null
  await setMeta('openDay', null)
  pinger.stop()
  return { offline: true }
}
