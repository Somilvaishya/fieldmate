import { ref } from 'vue'
import { api, ApiError } from '../api/client'
import { deviceUuid, getMeta, setMeta } from '../db'
import * as pinger from '../sync/pinger'

export const openDay = ref(null)
export const plannedToday = ref(null)

/** What the server says, falling back to what this phone last knew. */
export async function refresh() {
  try {
    const data = await api.dayCurrent()
    openDay.value = data.open ? data : null
    plannedToday.value = data.planned || null
    await setMeta('openDay', openDay.value)
    if (openDay.value && !pinger.isRunning()) pinger.start()
    if (!openDay.value) pinger.stop()
    return { offline: false }
  } catch (e) {
    if (e instanceof ApiError && e.code === 'OFFLINE') {
      openDay.value = await getMeta('openDay')
      return { offline: true }
    }
    throw e
  }
}

export async function start(payload) {
  const device = await deviceUuid()
  const data = await api.dayStart(device, payload)
  openDay.value = data
  await setMeta('openDay', data)
  pinger.start()
  return data
}

export async function end(payload) {
  const device = await deviceUuid()
  await pinger.flush()          // send the trail before the server computes distance from it
  const data = await api.dayEnd(device, payload)
  openDay.value = null
  await setMeta('openDay', null)
  pinger.stop()
  return data
}
