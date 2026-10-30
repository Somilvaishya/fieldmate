// Who is holding the phone: a rep, or somebody with a team.
//
// Area and Regional Managers work from this app rather than Desk, and until now it showed them
// exactly what it showed a rep - the same five tabs, no team, nowhere to approve anything. The
// roles were in every `auth.bootstrap` reply all along; nothing read them.
//
// Kept in a ref filled from the cached profile, so the right tabs draw on a cold open with no
// signal, and refreshed wherever a fresh profile is stored.
import { ref, computed } from 'vue'
import { getMeta } from '../db'

// The roles that see the manager's tabs. Sales Head and Admin are here too: they keep Desk, but
// a Sales Head opening the app on a market visit wants the team, not a rep's empty Today.
export const MANAGER_ROLES = [
  'FieldMate Area Manager',
  'FieldMate Regional Manager',
  'FieldMate Sales Head',
  'FieldMate Admin',
]

const roles = ref([])

export const isManager = computed(() => roles.value.some((r) => MANAGER_ROLES.includes(r)))

/** Where "home" is for whoever is signed in. */
export const homeRoute = computed(() => (isManager.value ? '/team' : '/today'))

export function remember(profile) {
  roles.value = Array.isArray(profile?.roles) ? profile.roles : []
}

export async function load() {
  try {
    remember(await getMeta('profile'))
  } catch {
    remember(null)
  }
}

// Read once per page load, and awaited by the router before the first screen is chosen. The
// cached profile lives in IndexedDB, which answers asynchronously - without this a manager's cold
// open resolved `/` before the roles arrived and landed on a rep's Today.
let loading = null
export function ready() {
  loading = loading || load()
  return loading
}

export function forget() {
  roles.value = []
}
