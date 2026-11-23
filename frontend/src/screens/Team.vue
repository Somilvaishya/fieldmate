<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { formatRupees } from '../lib/money'
import { isSignedOut } from '../lib/session'
import { getMeta } from '../db'
import { configure as configurePinger } from '../sync/pinger'
import * as dayStore from '../stores/day'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

// The manager's own day. An Area Manager is in the market most days - with a rep, at a shop, at
// a depot - and their attendance, their HR check-in and the kilometres their travel claim is paid
// on all come from Day Start and the GPS trail it opens, exactly as a rep's do. The manager's
// tabs have no Today, so the way in is here, on the screen they open first. A Regional Manager or
// Sales Head who works from an office simply never taps it.
const myDay = dayStore.openDay
const dayKnown = dayStore.loaded
const myStart = computed(() => myDay.value?.started_at ? String(myDay.value.started_at).slice(11, 16) : '')

// The trail's settings, as Today applies them for a rep. App.vue resumes the pinger for an open
// day on every screen, but only Today ever told it the company's interval or that the trail is
// switched off - so a manager who never opens Today would be tracked against the defaults.
getMeta('profile').then((p) => configurePinger(p?.settings || {})).catch(() => {})

// A manager's home: who is out, how far each of them has got, and what is waiting on a decision.
//
// Live, not last night's snapshot. The question this answers is "it is ten o'clock and Ravi has
// not started", which is worth nothing tomorrow. The server sorts the team so the rep who needs a
// call is at the top - nobody out yet, then least done - and this screen keeps that order.
const router = useRouter()
const board = ref(null)
const waiting = ref(0)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    // The inbox count is a nicety; the board is the screen. One failing must not blank the other.
    const [today, inbox] = await Promise.allSettled([api.teamToday(), api.teamInbox()])
    if (today.status === 'rejected') throw today.reason
    board.value = today.value
    waiting.value = inbox.status === 'fulfilled' ? Number(inbox.value.total || 0) : 0
  } catch (e) {
    if (isSignedOut(e)) return router.replace('/login')
    error.value = e instanceof ApiError
      ? e.message
      : t('Could not load your team. This needs signal - it is read live from the office.')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const members = computed(() => board.value?.members || [])
const totals = computed(() => board.value?.totals || {})

const STATUS = computed(() => ({
  'Not Started': { word: t('Not started'), tone: 'crit' },
  'Working': { word: t('Working'), tone: 'ok' },
  'Ended': { word: t('Day ended'), tone: 'flat' },
}))

/** A rupee figure a manager reads across a room: ₹ always, whole rupees, lakh and thousand
 *  shortened the way the cockpit does. "0.00" with no sign read as a count, not as money. */
function rupees(value) {
  const n = Number(value || 0)
  if (n >= 1_00_000) return '₹' + (n / 1_00_000).toFixed(n >= 10_00_000 ? 0 : 1) + 'L'
  if (n >= 1_000) return '₹' + (n / 1_000).toFixed(n >= 10_000 ? 0 : 1) + 'K'
  return '₹' + formatRupees(n, { decimals: 0 })
}

// Names a manager cannot tell apart. Two reps called Somil in one territory is ordinary, and a
// board showing two identical cards is a board nobody can act on - so where a name repeats, the
// login goes under it.
const repeated = computed(() => {
  const seen = new Map()
  for (const m of members.value) seen.set(m.full_name, (seen.get(m.full_name) || 0) + 1)
  return new Set([...seen].filter(([, n]) => n > 1).map(([name]) => name))
})

/** "09:41" out of "2026-10-30 09:41:12". The date is today's by construction. */
function clock(value) {
  return value ? String(value).slice(11, 16) : ''
}

/** How far through the route, as a share the bar can draw. Capped: a rep who added shops off
 *  the beat has done more than planned, not more than all of it. */
function progress(m) {
  if (!m.planned_calls) return 0
  return Math.min(100, Math.round((m.visits / m.planned_calls) * 100))
}
</script>

<template>
  <div class="wrap">
    <header class="head">
      <div>
        <h1>{{ t('My team') }}</h1>
        <p class="dim">{{ t('Where everybody is today') }}</p>
      </div>
      <button class="quiet" :disabled="loading" @click="load" :aria-label="t('Refresh')">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <!-- My own day: Day Start, Day End and the trail, the same screens a rep uses. -->
    <section class="myday" :class="{ on: myDay }">
      <Icon :name="myDay ? 'clock' : 'pin'" size="20" />
      <span class="body">
        <b>{{ myDay ? t('My day started at {time}', { time: myStart }) : t('My day') }}</b>
        <em>{{ myDay
              ? t('Your attendance and travel are being recorded.')
              : t('Going into the market? Start your day for attendance and travel.') }}</em>
      </span>
      <RouterLink v-if="myDay" to="/day/end" class="daybtn ghost">{{ t('End day') }}</RouterLink>
      <RouterLink v-else-if="dayKnown" to="/day/start" class="daybtn">{{ t('Start my day') }}</RouterLink>
    </section>

    <!-- The way to the decisions, only when there are some. A count of zero on a banner is a
         banner a manager learns to stop reading. -->
    <RouterLink v-if="waiting" to="/approvals" class="waiting">
      <Icon name="alert" size="20" />
      <span class="body">
        <b>{{ waiting === 1
              ? t('{n} thing is waiting on you', { n: waiting })
              : t('{n} things are waiting on you', { n: waiting }) }}</b>
        <em>{{ t('Shops, orders, expenses and check-ins') }}</em>
      </span>
      <Icon name="chevron" size="18" />
    </RouterLink>

    <p v-if="loading && !board" class="note">{{ t('Loading…') }}</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else-if="members.length">
      <div class="facts">
        <div class="fact">
          <span class="dim">{{ t('Out today') }}</span>
          <b class="tnum">{{ totals.started }} / {{ totals.members }}</b>
        </div>
        <div class="fact">
          <span class="dim">{{ t('Visits') }}</span>
          <b class="tnum">{{ totals.visits }}<template v-if="totals.planned_calls"> / {{ totals.planned_calls }}</template></b>
        </div>
        <div class="fact">
          <span class="dim">{{ t('Orders') }}</span>
          <b class="tnum">{{ rupees(totals.order_value) }}</b>
        </div>
      </div>

      <div v-for="m in members" :key="m.field_user" class="card">
        <div class="top">
          <!-- The way into the rep's page: profile, orders, what their phone could not send.
               The name rather than the whole card, because the card also holds a Call link and
               a link inside a link is two taps fighting for one thumb. -->
          <RouterLink class="who" :to="{ name: 'team-member', params: { rep: m.field_user } }">
            <b class="name">{{ m.full_name }} <Icon name="chevron" size="14" class="go" /></b>
            <span v-if="repeated.has(m.full_name)" class="dim login">{{ m.field_user }}</span>
            <span class="dim">{{ m.beat || m.territory }}</span>
          </RouterLink>
          <span class="pill" :class="STATUS[m.day_status].tone">
            {{ STATUS[m.day_status].word }}<template v-if="m.day_status === 'Working' && m.started_at">
              · {{ clock(m.started_at) }}</template>
          </span>
        </div>

        <div v-if="m.day_status !== 'Not Started'" class="work">
          <div class="bar" :aria-label="t('{done} of {planned} visits', { done: m.visits, planned: m.planned_calls })">
            <span :style="{ width: progress(m) + '%' }"></span>
          </div>
          <div class="nums">
            <span class="tnum">
              {{ m.planned_calls
                  ? t('{done} of {planned} visits', { done: m.visits, planned: m.planned_calls })
                  : t('{n} visits', { n: m.visits }) }}
              <template v-if="m.productive"> · {{ t('{n} with an order', { n: m.productive }) }}</template>
            </span>
            <b class="tnum">{{ rupees(m.order_value) }}</b>
          </div>
          <span v-if="m.last_check_in" class="dim">
            {{ t('Last check-in {time}', { time: clock(m.last_check_in) }) }}
          </span>
        </div>

        <a v-if="m.mobile_no" class="call" :href="'tel:' + m.mobile_no">
          <Icon name="phone" size="18" /><span>{{ t('Call') }}</span>
        </a>
      </div>
    </template>

    <div v-else class="empty">
      <Icon name="team" size="34" />
      <b>{{ t('Nobody reports to you yet') }}</b>
      <p class="dim">
        {{ t('Ask your admin to set Reports To on your reps. Until then there is nobody to show here.') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.head h1 { font-size: 20px; margin: 0; }
.dim { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.quiet { border: 0; background: none; color: var(--muted); min-height: 44px; padding: 0 6px; }

.myday { display: flex; align-items: center; gap: 10px; padding: 12px; border-radius: 10px;
         border: 1px solid var(--line); background: var(--surface); color: var(--muted); }
.myday.on { border-color: var(--ok); background: var(--ok-soft); color: var(--ok); }
.myday .body { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.myday b { color: var(--ink); font-size: 15px; }
.myday em { font-style: normal; font-size: 13px; }
.daybtn { flex: none; display: inline-flex; align-items: center; justify-content: center;
          min-height: 44px; padding: 0 14px; border-radius: 8px; font-weight: 700;
          font-size: 14px; text-decoration: none; background: var(--primary);
          color: var(--on-primary); }
.daybtn.ghost { background: var(--surface); color: var(--ink); border: 1px solid var(--line); }
.waiting { display: flex; align-items: center; gap: 10px; padding: 12px; border-radius: 10px;
           background: var(--warn-soft); color: var(--warn); text-decoration: none;
           min-height: 56px; }
.waiting .body { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.waiting b { color: var(--ink); font-size: 15px; }
.waiting em { font-style: normal; font-size: 13px; }

.facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.fact { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 10px; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.fact b { font-size: 17px; overflow-wrap: anywhere; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.top { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.who { display: flex; flex-direction: column; min-width: 0; min-height: 44px; color: inherit;
       text-decoration: none; }
.who .go { color: var(--muted); vertical-align: middle; }
.name { font-size: 16px; overflow-wrap: anywhere; }
.login { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px;
         overflow-wrap: anywhere; }
.pill { flex: none; font-size: 12px; font-weight: 700; padding: 3px 8px; border-radius: 6px;
        white-space: nowrap; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.crit { background: var(--crit-soft); color: var(--crit); }
.pill.flat { background: var(--primary-soft); color: var(--primary); }

.work { display: flex; flex-direction: column; gap: 4px; }
.bar { height: 6px; border-radius: 3px; background: var(--primary-soft); overflow: hidden; }
.bar span { display: block; height: 100%; background: var(--ok); }
.nums { display: flex; justify-content: space-between; gap: 8px; font-size: 14px; }

.call { align-self: flex-start; display: inline-flex; align-items: center; gap: 6px;
        min-height: 44px; padding: 0 14px; border-radius: 8px; border: 1px solid var(--line);
        color: var(--primary); font-weight: 600; text-decoration: none; }

.note { color: var(--muted); font-size: 14px; text-align: center; padding: 20px 0; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.empty { text-align: center; padding: 40px 16px; color: var(--muted); display: flex;
         flex-direction: column; gap: 6px; align-items: center; }
.empty b { color: var(--ink); }
.empty p { margin: 0; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
