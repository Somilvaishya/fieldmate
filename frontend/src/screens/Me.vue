<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, setCsrfToken } from '../api/client'
import { getMeta, setMeta, wipe } from '../db'
import * as outbox from '../sync/outbox'
import * as photoQueue from '../sync/photos'
import { pendingPings, flush as flushPings } from '../sync/pinger'
import Icon from '../components/Icon.vue'

const router = useRouter()
const profile = ref(null)
const loading = ref(true)

// The screens that belong to the rep rather than to a shop or a day.
const LINKS = [
  { to: '/performance', icon: 'target', title: 'My performance',
    note: 'Targets, and what the month is worth' },
  { to: '/expense', icon: 'receipt', title: 'Claim expenses',
    note: 'Travel, food and what you spent' },
  { to: '/cockpit', icon: 'list', title: 'How today is going',
    note: 'Calls, orders and cash so far' },
  { to: '/deposit', icon: 'tag', title: 'Hand in cash',
    note: 'Declare what you are carrying' },
]

async function load() {
  // The cached profile first, so this screen is never blank on a market connection.
  profile.value = await getMeta('profile')
  try {
    const live = await api.bootstrap()
    await setMeta('profile', live)
    profile.value = live
  } catch {
    // Cached is fine. Nothing on this screen is worth an error message for.
  } finally {
    loading.value = false
  }
}

// ------------------------------------------------------------------------------ signing out

// Signing out has to do three things, and used to do none of them: end the session on the
// server, empty this phone, and not strand work that never reached anybody.
//
// The third is the one that decides the shape. A rep taps this at the end of a day in a village
// with a morning of visits still queued. Wiping without asking loses that morning; refusing
// outright strands a rep who is handing the handset back. So: send what can be sent, then say
// plainly what is left and let them choose.
const waiting = ref(0)
const signingOut = ref(false)
const confirmWipe = ref(false)
const signOutError = ref('')

async function countWaiting() {
  return (await outbox.pendingCount()) + (await photoQueue.pendingCount()) + (await pendingPings())
}

async function signOut() {
  signOutError.value = ''
  signingOut.value = true
  try {
    // One last push. Nothing is lost that could have been saved.
    if (navigator.onLine) {
      await outbox.drain().catch(() => {})
      await photoQueue.drain().catch(() => {})
      await flushPings().catch(() => {})
    }
    waiting.value = await countWaiting()
    if (waiting.value && !confirmWipe.value) {
      confirmWipe.value = true
      return
    }
    await finishSignOut()
  } finally {
    signingOut.value = false
  }
}

async function finishSignOut() {
  // The session dies first. If the wipe fails half way, a phone with data on it is at least a
  // phone nobody can use to reach the server.
  await api.logout().catch(() => {})
  // The session's CSRF token goes with the session. Left behind it is harmless - the server
  // would refuse it - but a token for a session that no longer exists is one more thing on a
  // handed-back handset that looks like it belongs to the last rep.
  setCsrfToken(null)
  await wipe().catch(() => {})
  router.push('/login')
}

onMounted(load)
</script>

<template>
  <div class="wrap">
    <header class="who">
      <div class="avatar"><Icon name="person" size="26" /></div>
      <div>
        <h1>{{ profile?.full_name || profile?.field_user || 'You' }}</h1>
        <p class="dim">
          {{ profile?.designation || 'Field Rep' }}
          <template v-if="profile?.territory"> · {{ profile.territory }}</template>
        </p>
      </div>
    </header>

    <div class="facts" v-if="profile">
      <div class="fact">
        <span class="dim">Selling as</span>
        <b>{{ profile.sales_mode || 'Order Booking' }}</b>
      </div>
      <div class="fact">
        <span class="dim">Calls a day</span>
        <b class="tnum">{{ profile.daily_target_calls || '—' }}</b>
      </div>
    </div>

    <RouterLink v-for="l in LINKS" :key="l.to" :to="l.to" class="row">
      <Icon :name="l.icon" size="20" />
      <span class="body">
        <b>{{ l.title }}</b>
        <em>{{ l.note }}</em>
      </span>
      <Icon name="chevron" size="18" class="go" />
    </RouterLink>

    <div class="foot">
      <p class="dim fine" v-if="profile?.support_contact">
        Stuck? {{ profile.support_contact }}
      </p>
      <template v-if="!confirmWipe">
        <button class="out" :disabled="signingOut" @click="signOut">
          {{ signingOut ? 'Sending what is left…' : 'Sign out' }}
        </button>
        <p class="dim fine">
          Signing out sends anything still waiting, then clears this phone.
        </p>
      </template>

      <!-- Only when something genuinely could not be sent. The number is named, because "some
           data may be lost" is a sentence nobody can act on. -->
      <div v-else class="sure">
        <p class="warn">
          <b class="tnum">{{ waiting }} {{ waiting === 1 ? 'thing' : 'things' }} never reached
          the office.</b>
          Signing out now clears this phone and they are gone for good. If you can get signal,
          stay signed in until they go.
        </p>
        <p v-if="signOutError" class="note crit">{{ signOutError }}</p>
        <div class="pair">
          <button class="keep" :disabled="signingOut" @click="confirmWipe = false">
            Stay signed in
          </button>
          <button class="go" :disabled="signingOut" @click="finishSignOut">
            {{ signingOut ? 'Signing out…' : 'Sign out anyway' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.who { display: flex; align-items: center; gap: 12px; }
.who h1 { font-size: 20px; margin: 0; }
.avatar { width: 48px; height: 48px; border-radius: 999px; background: var(--primary-soft);
          color: var(--primary); display: grid; place-items: center; flex: none; }
.dim { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.fine { font-size: 12px; text-align: center; }

.facts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.fact { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: flex; flex-direction: column; gap: 2px; }

.row { display: flex; align-items: center; gap: 12px; min-height: 64px; padding: 12px;
       background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
       text-decoration: none; color: var(--ink); }
.row .body { flex: 1; display: flex; flex-direction: column; }
.row em { font-style: normal; font-size: 13px; color: var(--muted); }
.go { color: var(--muted); flex: none; }

.foot { margin-top: 8px; display: flex; flex-direction: column; gap: 8px; }
.out { min-height: 48px; border: 1px solid var(--line); background: var(--surface);
       border-radius: 8px; color: var(--crit); font-weight: 600; }

.sure { display: flex; flex-direction: column; gap: 10px; background: var(--warn-soft);
        border: 1px solid var(--warn); border-radius: 10px; padding: 14px; }
.sure .warn { margin: 0; font-size: 14px; color: var(--warn); }
.sure .warn b { display: block; margin-bottom: 2px; }
.pair { display: flex; gap: 8px; }
.pair button { flex: 1; min-height: 48px; border-radius: 8px; font-weight: 600; }
/* Staying signed in is the safe answer, so it is the plain one. */
.keep { border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
.go { border: 0; background: var(--crit); color: #fff; }
.note.crit { color: var(--crit); background: var(--crit-soft); border-radius: 8px;
             padding: 10px 12px; margin: 0; font-size: 14px; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
