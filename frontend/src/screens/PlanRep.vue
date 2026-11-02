<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { isSignedOut } from '../lib/session'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

// One rep's month: build it, read it, approve it.
//
// Building writes a draft from the rep's beats, holidays and leave; nothing reaches the rep until
// it is approved. The days are shown before the button so a manager approves what they have read,
// not what they assume - a working day with no beat on it is a hole in the route, and it shows.
const route = useRoute()
const router = useRouter()
const rep = route.params.rep
const month = route.query.month

const member = ref(null)
const plan = ref(null)
const loading = ref(true)
const busy = ref('')
const error = ref('')

// What to build: the window and the holiday list, as on Desk's form. The window starts as the
// month the manager came from; the holiday list as the rep's own, off their Employee record.
// Other lists are offered only if this login may read them - usually HR's call, not ours.
const fromDate = ref('')
const toDate = ref('')
const holidayList = ref('')
const holidayOptions = ref([])

function monthBounds(anchor) {
  const [y, m] = String(anchor || '').split('-').map(Number)
  if (!y || !m) return ['', '']
  const last = new Date(y, m, 0).getDate()
  const mm = String(m).padStart(2, '0')
  return [`${y}-${mm}-01`, `${y}-${mm}-${String(last).padStart(2, '0')}`]
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [overview, lists] = await Promise.all([
      api.planOverview(month),
      api.planHolidayLists(rep).catch(() => ({ default: null, options: [] })),
    ])
    member.value = (overview.members || []).find((m) => m.field_user === rep) || null
    plan.value = member.value?.plan ? await api.planDays(member.value.plan.name) : null
    holidayOptions.value = lists.options || []
    holidayList.value = plan.value?.holiday_list || lists.default || ''
    ;[fromDate.value, toDate.value] = plan.value
      ? [plan.value.from_date, plan.value.to_date]
      : monthBounds(month)
  } catch (e) {
    if (isSignedOut(e)) return router.replace('/login')
    error.value = e instanceof ApiError ? e.message : t('Could not load the plan. This needs signal.')
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function act(kind) {
  busy.value = kind
  error.value = ''
  try {
    if (kind === 'build') {
      if (!fromDate.value || !toDate.value) {
        error.value = t('Pick both dates first.')
        return
      }
      if (toDate.value < fromDate.value) {
        error.value = t('To date is before from date.')
        return
      }
      plan.value = await api.planBuild(rep, {
        fromDate: fromDate.value, toDate: toDate.value, holidayList: holidayList.value || undefined,
      })
    }
    else if (kind === 'approve') plan.value = await api.planApprove(plan.value.name)
    else if (kind === 'cancel') {
      await api.planCancel(plan.value.name)
      plan.value = null
    }
  } catch (e) {
    error.value = e instanceof ApiError && e.code === 'OFFLINE'
      ? t('No signal. Nothing was changed - try again when you have one.')
      : (e?.message || t('That did not go through.'))
  } finally {
    busy.value = ''
  }
}

const monthName = computed(() => {
  const [y, m] = String(month || '').split('-')
  const names = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
                 'September', 'October', 'November', 'December']
  return names[Number(m) - 1] ? `${t(names[Number(m) - 1])} ${y}` : ''
})

const WORD = computed(() => ({
  Holiday: t('Holiday'),
  Leave: t('On leave'),
}))

function date(value) {
  return String(value).slice(8, 10)
}

/** "05/10" - a day and a month, for the window line. */
function short(value) {
  return value ? String(value).slice(8, 10) + '/' + String(value).slice(5, 7) : ''
}
</script>

<template>
  <div class="wrap">
    <header class="head">
      <RouterLink :to="{ name: 'plan', query: { month } }" class="back" :aria-label="t('Back')">
        <Icon name="back" size="20" />
      </RouterLink>
      <div>
        <h1>{{ member?.full_name || rep }}</h1>
        <p class="dim">{{ monthName }}</p>
      </div>
    </header>

    <p v-if="loading" class="note">{{ t('Loading…') }}</p>

    <template v-else>
      <p v-if="error" class="note crit">{{ error }}</p>

      <div v-if="!plan" class="empty">
        <Icon name="calendar" size="34" />
        <b>{{ t('No plan for this month yet') }}</b>
        <p class="dim" v-if="member && member.beats">
          {{ t('Build it from their {n} beats. Holidays and approved leave are left off by themselves.', { n: member.beats }) }}
        </p>
        <p class="dim" v-else>{{ t('They have no beats yet. Make one first, from Beats.') }}</p>
      </div>

      <!-- What to build. Shown until the plan is approved: a draft can be rebuilt over a new
           window or a different holiday list as often as the manager likes. -->
      <section v-if="member && member.beats && (!plan || plan.state === 'Draft')" class="form">
        <div class="pair">
          <label class="field">
            <span>{{ t('From') }}</span>
            <input type="date" v-model="fromDate" />
          </label>
          <label class="field">
            <span>{{ t('To') }}</span>
            <input type="date" v-model="toDate" />
          </label>
        </div>
        <label class="field">
          <span>{{ t('Holiday list') }}</span>
          <select v-model="holidayList">
            <option value="">{{ t('None') }}</option>
            <option v-for="h in holidayOptions" :key="h" :value="h">{{ h }}</option>
          </select>
        </label>
        <button class="btn" :disabled="!!busy" @click="act('build')">
          {{ busy === 'build' ? t('Building…') : (plan ? t('Build again') : t('Build the plan')) }}
        </button>
      </section>

      <template v-if="plan">
        <p class="dim">
          {{ t('{from} to {to}', { from: short(plan.from_date), to: short(plan.to_date) }) }}
          <template v-if="plan.holiday_list"> · {{ plan.holiday_list }}</template>
        </p>
        <div class="facts">
          <div class="fact">
            <span class="dim">{{ t('Working days') }}</span>
            <b class="tnum">{{ plan.working_days }}</b>
          </div>
          <div class="fact">
            <span class="dim">{{ t('With a beat') }}</span>
            <b class="tnum">{{ plan.planned_days }}</b>
          </div>
          <div class="fact">
            <span class="dim">{{ t('Visits') }}</span>
            <b class="tnum">{{ plan.planned_visits }}</b>
          </div>
        </div>

        <p v-if="plan.gaps" class="note warn">
          {{ plan.gaps === 1
              ? t('1 working day has no beat. Add a beat for that weekday, then build again.')
              : t('{n} working days have no beat. Add a beat for those weekdays, then build again.', { n: plan.gaps }) }}
        </p>

        <ol class="days">
          <li v-for="d in plan.days" :key="d.plan_date" :class="{ off: !d.is_working_day, hole: d.is_working_day && !d.beat }">
            <span class="date tnum">{{ date(d.plan_date) }}</span>
            <span class="dow">{{ t(d.day_of_week).slice(0, 3) }}</span>
            <span class="what">
              <template v-if="!d.is_working_day">{{ WORD[d.status] || d.status }}</template>
              <template v-else-if="d.beat">{{ d.beat_name || d.beat }}</template>
              <template v-else>{{ t('No beat') }}</template>
            </span>
            <span v-if="d.beat" class="dim tnum">{{ d.outlet_count }}</span>
          </li>
        </ol>

        <div class="actions">
          <template v-if="plan.state === 'Draft'">
            <button class="btn wide" :disabled="!!busy" @click="act('approve')">
              <Icon name="check" size="18" />
              {{ busy === 'approve' ? t('Sending…') : t('Approve the month') }}
            </button>
          </template>
          <template v-else>
            <p class="note ok">{{ t('Approved. It is on their phone.') }}</p>
            <button v-if="plan.can_cancel" class="ghost danger" :disabled="!!busy" @click="act('cancel')">
              {{ busy === 'cancel' ? t('Sending…') : t('Withdraw this plan') }}
            </button>
          </template>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: center; gap: 8px; }
.head h1 { font-size: 20px; margin: 0; overflow-wrap: anywhere; }
.back { display: inline-flex; align-items: center; justify-content: center; min-width: 44px;
        min-height: 44px; color: var(--ink); }
.dim { color: var(--muted); font-size: 13px; margin: 0; }

.facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.fact { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 10px; display: flex; flex-direction: column; gap: 2px; }
.fact b { font-size: 18px; }

.days { list-style: none; margin: 0; padding: 0; background: var(--surface);
        border: 1px solid var(--line); border-radius: 10px; }
.days li { display: grid; grid-template-columns: 28px 40px minmax(0, 1fr) auto; gap: 8px;
           align-items: center; padding: 8px 12px; min-height: 40px; font-size: 14px; }
.days li + li { border-top: 1px solid var(--line); }
.days li.off { color: var(--muted); background: var(--bg); }
.days li.hole .what { color: var(--warn); font-weight: 700; }
.date { font-weight: 700; }
.dow { color: var(--muted); font-size: 13px; }
.what { overflow-wrap: anywhere; }

.form { display: flex; flex-direction: column; gap: 10px; background: var(--surface);
        border: 1px solid var(--line); border-radius: 10px; padding: 12px; }
.form .pair { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.field > span { font-size: 13px; font-weight: 700; color: var(--muted); }
.actions { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.actions .wide { grid-column: 1 / -1; }
.actions .note { grid-column: 1 / -1; }
.actions .danger { grid-column: 1 / -1; color: var(--crit); }
.btn, .ghost { min-height: 48px; border-radius: 8px; font-weight: 700; font-size: 15px;
               display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
.btn { border: 0; background: var(--primary); color: var(--on-primary); padding: 0 18px; }
.ghost { border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
.btn:disabled, .ghost:disabled { opacity: .6; }

.note { color: var(--muted); font-size: 14px; text-align: center; padding: 20px 0; margin: 0; }
.note.ok { color: var(--ok); background: var(--ok-soft); border-radius: 8px; padding: 10px 12px; }
.note.warn { color: var(--warn); background: var(--warn-soft); border-radius: 8px;
             padding: 10px 12px; text-align: left; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.empty { text-align: center; padding: 32px 16px; color: var(--muted); display: flex;
         flex-direction: column; gap: 8px; align-items: center; }
.empty b { color: var(--ink); }
.empty p { margin: 0; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
