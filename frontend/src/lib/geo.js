import { t } from './i18n'

/** A GPS fix, as a promise, with the failure modes a rep actually hits. */
export function getPosition({ timeout = 15000, highAccuracy = true } = {}) {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error(t('This phone cannot report its location.')))
      return
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        latitude: +pos.coords.latitude.toFixed(6),
        longitude: +pos.coords.longitude.toFixed(6),
        accuracy_m: Math.round(pos.coords.accuracy),
        // Chrome on Android exposes this on a mocked fix. Recorded, never used to block:
        // blocking pushes a rep to stop using the app rather than to stop faking.
        is_mock_location: pos.coords.mocked ? 1 : 0,
        location_provider: pos.coords.altitude == null ? 'network' : 'gps',
      }),
      (err) => {
        // Built per call, not once at import: a map of translated sentences held in a
        // module const would freeze the language the way a label const does.
        const reasons = {
          1: t('Location permission is off. Turn it on for this app and try again.'),
          2: t('Could not get a GPS fix. Step outside or near a window.'),
          3: t('GPS is taking too long. Try again in a moment.'),
        }
        reject(new Error(reasons[err.code] || t('Could not read your location.')))
      },
      { enableHighAccuracy: highAccuracy, timeout, maximumAge: 0 }
    )
  })
}

/** A quiet fix for background pings: never prompts loudly, never throws. */
export function tryPosition() {
  return getPosition({ timeout: 20000 }).catch(() => null)
}
