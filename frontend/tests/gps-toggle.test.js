/**
 * Whether the phone reports its position at all.
 *
 * Some companies do not track their reps, and some reps work in places where a trail is not worth
 * the battery. FieldMate Settings now carries a switch for it, and when it is off the phone must
 * take no fixes - not take them quietly and throw them away, which costs the same battery.
 *
 * **The two traps this pins.**
 *
 * 1. A missing key is not an opt-out. A bootstrap from before this setting existed, or a cached
 *    profile from an older build, has no `track_gps_trail` at all. Reading that as "off" would
 *    silently stop recording for every rep on an app that had simply not refreshed yet.
 * 2. The day resumes before bootstrap answers. `resumeIfDayOpen()` runs on mount so a reload
 *    mid-day carries on recording without waiting for a signal - which means it starts pinging
 *    before the live settings arrive. Both orders have to end up in the right state.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const tryPosition = vi.fn(async () => ({ latitude: 28.6, longitude: 77.2, accuracy_m: 8 }))

vi.mock('../src/lib/geo', () => ({ tryPosition: (...a) => tryPosition(...a) }))
vi.mock('../src/api/client', () => ({
  api: { uploadPings: vi.fn(async () => ({ ok: true })) },
  ApiError: class ApiError extends Error {},
}))

const pinger = await import('../src/sync/pinger')
const { db, setMeta } = await import('../src/db')

beforeEach(async () => {
  pinger.stop()
  await db.pings.clear()
  await db.meta.clear()
  // Back to the default every test starts from, whatever the last one set.
  pinger.configure({ track_gps_trail: true })
})

describe('the trail switch', () => {
  it('records by default, because that is what the DocType says', () => {
    expect(pinger.isTracking()).toBe(true)
  })

  it('stops taking fixes when the company switched it off', async () => {
    pinger.configure({ track_gps_trail: false })
    pinger.start()
    expect(pinger.isRunning()).toBe(false)
    // Not "collected and discarded" - a fix is the expensive part, so none was asked for.
    expect(tryPosition).not.toHaveBeenCalled()
  })

  it('keeps recording when the setting is simply absent', () => {
    // The first trap: an older bootstrap, or a cached profile from a build before this setting.
    pinger.configure({ gps_ping_interval_seconds: 120 })
    expect(pinger.isTracking()).toBe(true)
    pinger.start()
    expect(pinger.isRunning()).toBe(true)
    pinger.stop()
  })

  it('stops a run already under way when the live settings say not to', () => {
    // The second trap, in the order it actually happens: the day resumed on a cached profile
    // and started pinging, then bootstrap answered saying this company does not track.
    pinger.start()
    expect(pinger.isRunning()).toBe(true)
    pinger.configure({ track_gps_trail: false })
    expect(pinger.isRunning()).toBe(false)
  })

  it('does not resume a reloaded day when the cached settings say it is off', async () => {
    await setMeta('openDay', { day: 'FM-DAY-0001' })
    await setMeta('profile', { settings: { track_gps_trail: false } })
    await pinger.resumeIfDayOpen()
    expect(pinger.isRunning()).toBe(false)
    expect(tryPosition).not.toHaveBeenCalled()
  })

  it('resumes a reloaded day when tracking is on', async () => {
    await setMeta('openDay', { day: 'FM-DAY-0001' })
    await setMeta('profile', { settings: { track_gps_trail: true } })
    await pinger.resumeIfDayOpen()
    expect(pinger.isRunning()).toBe(true)
    pinger.stop()
  })

  it('still sends fixes already taken after the switch goes off', async () => {
    // Turning it off is not a reason to lose the morning. Those kilometres were real, and an
    // expense claim is paid against them.
    pinger.start()
    await new Promise((r) => setTimeout(r, 0))
    const held = await db.pings.count()
    expect(held).toBeGreaterThan(0)

    pinger.configure({ track_gps_trail: false })
    expect(await db.pings.count()).toBe(held)
  })
})
