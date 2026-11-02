// Is this error the server saying nobody is signed in?
//
// Today has always sent a rep to the sign-in screen on one of these. The manager's screens did
// not: they printed "Please sign in again" and left the manager on a screen with no way to do it.
// That is exactly what happens the first time a manager opens the app after Desk is taken from
// them - Frappe ends every session of a user whose type changes - so the manager's first morning
// on the app would have been a dead end.
import { ApiError } from '../api/client'

export function isSignedOut(e) {
  return e instanceof ApiError && ['AUTH_REQUIRED', 'LOGIN_FAILED'].includes(e.code)
}
