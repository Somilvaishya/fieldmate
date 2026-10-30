<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api/client'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

// Everything waiting on this manager, in one place. These four used to be four Desk lists; Area
// and Regional Managers have no Desk now, so this screen is the only way they say yes or no.
//
// Online only, deliberately. Each of these is an answer somebody else is waiting on - a rep at
// the counter, a depot holding a truck - and an approval queued on a phone in a basement is an
// answer nobody has. A failure says so, and the row stays where it was.
const box = ref(null)
const kind = ref('outlets')
const loading = ref(true)
const error = ref('')

// The row being refused, and why. A refusal always needs a reason - the server insists for
// expenses and check-ins, and a shop or an order refused with no reason is a phone call later.
const refusing = ref(null)
const reason = ref('')
// What an expense is approved at. Starts at what was claimed; a manager may approve less.
const amounts = ref({})
const busy = ref(null)
const done = ref('')
const rowError = ref({})

const KINDS = computed(() => [
  { key: 'outlets', label: t('Shops') },
  { key: 'orders', label: t('Orders') },
  { key: 'expenses', label: t('Expenses') },
  { key: 'geo_fence', label: t('Check-ins') },
])

async function load() {
  loading.value = true
  error.value = ''
  try {
    box.value = await api.teamInbox()
    // Open on whichever kind has something in it, so a manager is not greeted by an empty tab
    // when the work is one tap away.
    const counts = box.value.counts || {}
    if (!counts[kind.value]) {
      kind.value = KINDS.value.find((k) => counts[k.key])?.key || kind.value
    }
  } catch (e) {
    error.value = e instanceof ApiError
      ? e.message
      : t('Could not load your approvals. This needs signal.')
  } finally {
    loading.value = false
  }
}

onMounted(load)

const rows = computed(() => box.value?.[kind.value] || [])
const count = (key) => Number(box.value?.counts?.[key] || 0)

function day(value) {
  return value ? String(value).slice(0, 10).split('-').reverse().join('/') : ''
}

function amountFor(row) {
  return amounts.value[row.name] ?? Number(row.claimed_amount || 0)
}

function startRefusal(row) {
  refusing.value = row.name
  reason.value = ''
  rowError.value = { ...rowError.value, [row.name]: '' }
}

async function decide(row, decision) {
  if (decision === 'Rejected' && !reason.value.trim()) {
    rowError.value = { ...rowError.value, [row.name]: t('Say why. The rep will read this.') }
    return
  }
  busy.value = row.name
  rowError.value = { ...rowError.value, [row.name]: '' }
  const note = decision === 'Rejected' ? reason.value.trim() : undefined
  try {
    if (kind.value === 'outlets') await api.decideOutlet(row.name, decision, note)
    else if (kind.value === 'orders') await api.decideOrder(row.name, decision, note)
    else if (kind.value === 'expenses') {
      await api.decideExpense(row.name, decision,
                              decision === 'Approved' ? amountFor(row) : undefined, note)
    } else await api.decideGeoFence(row.name, decision, note)

    // Gone from the list at once rather than after a reload: the next row is what the manager
    // wants under their thumb.
    box.value[kind.value] = rows.value.filter((r) => r.name !== row.name)
    box.value.counts[kind.value] = Math.max(0, count(kind.value) - 1)
    box.value.total = Math.max(0, Number(box.value.total || 0) - 1)
    refusing.value = null
    done.value = decision === 'Approved' ? t('Approved.') : t('Refused.')
    setTimeout(() => { done.value = '' }, 2500)
  } catch (e) {
    rowError.value = {
      ...rowError.value,
      [row.name]: e instanceof ApiError && e.code === 'OFFLINE'
        ? t('No signal. Nothing was decided - try again when you have one.')
        : (e?.message || t('That did not go through.')),
    }
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="wrap">
    <header class="head">
      <div>
        <h1>{{ t('Approvals') }}</h1>
        <p class="dim">{{ t('Waiting on you, oldest first') }}</p>
      </div>
      <button class="quiet" :disabled="loading" @click="load" :aria-label="t('Refresh')">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <div class="tabs">
      <button v-for="k in KINDS" :key="k.key" class="chip" :class="{ on: kind === k.key }"
              @click="kind = k.key; refusing = null">
        {{ k.label }}
        <span v-if="count(k.key)" class="count tnum">{{ count(k.key) }}</span>
      </button>
    </div>

    <p v-if="done" class="note ok" role="status">{{ done }}</p>
    <p v-if="loading && !box" class="note">{{ t('Loading…') }}</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else-if="rows.length">
      <div v-for="row in rows" :key="row.name" class="card">
        <!-- What is being decided. Each kind leads with the fact the decision turns on. -->
        <template v-if="kind === 'outlets'">
          <b class="name">{{ row.outlet_name }}</b>
          <span class="dim">{{ [row.owner_name, row.city || row.territory].filter(Boolean).join(' · ') }}</span>
          <span class="dim">{{ t('Added by {rep} on {date}', { rep: row.rep_name || '—', date: day(row.onboarding_date || row.creation) }) }}</span>
          <span v-if="!row.latitude" class="pill warn">{{ t('No location pinned') }}</span>
          <a v-if="row.mobile_no" class="dim" :href="'tel:' + row.mobile_no">{{ row.mobile_no }}</a>
        </template>

        <template v-else-if="kind === 'orders'">
          <div class="top">
            <b class="name">{{ row.outlet_name || row.customer || row.outlet }}</b>
            <b class="tnum">{{ formatRupees(row.grand_total) }}</b>
          </div>
          <span class="dim">{{ t('{rep} · {date} · {n} lines', { rep: row.rep_name, date: day(row.order_date), n: row.total_lines || 0 }) }}</span>
          <span v-if="row.credit_limit_at_order" class="dim">
            {{ t('Owes {owed} against a limit of {limit}', { owed: formatRupees(row.outstanding_at_order), limit: formatRupees(row.credit_limit_at_order) }) }}
          </span>
          <span v-if="row.approval_rule" class="pill warn">{{ row.approval_rule }}</span>
        </template>

        <template v-else-if="kind === 'expenses'">
          <div class="top">
            <b class="name">{{ row.rep_name }}</b>
            <b class="tnum">{{ formatRupees(row.claimed_amount) }}</b>
          </div>
          <span class="dim">{{ row.expense_type }} · {{ day(row.claim_date) }}</span>
          <span v-if="row.claimed_distance_km" class="dim">
            {{ t('Claimed {claimed} km, GPS trail {trail} km', { claimed: row.claimed_distance_km, trail: row.trail_distance_km || 0 }) }}
          </span>
          <span v-if="row.approval_reason" class="pill warn">{{ row.approval_reason }}</span>
          <label class="amount">
            <span class="dim">{{ t('Approve at') }}</span>
            <input type="number" inputmode="decimal" min="0" :max="row.claimed_amount"
                   :value="amountFor(row)"
                   @input="amounts[row.name] = Number($event.target.value)" />
          </label>
        </template>

        <template v-else>
          <b class="name">{{ row.outlet_name }}</b>
          <span class="dim">{{ t('{rep} · {date}', { rep: row.rep_name, date: day(row.exception_date) }) }}</span>
          <span class="pill warn">
            {{ t('Checked in {m} m from the shop', { m: Math.round(row.distance_m) }) }}
          </span>
          <span v-if="row.reason" class="dim">{{ row.reason }}</span>
        </template>

        <!-- The decision. Refusing opens a reason box first rather than refusing on the tap:
             the two buttons sit side by side under a moving thumb. -->
        <div v-if="refusing === row.name" class="why">
          <textarea v-model="reason" rows="2" :placeholder="t('Why? The rep will read this.')"></textarea>
          <div class="pair">
            <button class="ghost" :disabled="busy === row.name" @click="refusing = null">
              {{ t('Back') }}
            </button>
            <button class="no" :disabled="busy === row.name" @click="decide(row, 'Rejected')">
              {{ busy === row.name ? t('Sending…') : t('Refuse') }}
            </button>
          </div>
        </div>
        <div v-else class="pair">
          <button class="ghost" :disabled="busy === row.name" @click="startRefusal(row)">
            {{ t('Refuse') }}
          </button>
          <button class="yes" :disabled="busy === row.name" @click="decide(row, 'Approved')">
            <Icon name="check" size="18" />
            {{ busy === row.name ? t('Sending…') : t('Approve') }}
          </button>
        </div>
        <p v-if="rowError[row.name]" class="note crit">{{ rowError[row.name] }}</p>
      </div>
    </template>

    <div v-else class="empty">
      <Icon name="check" size="34" />
      <b>{{ t('Nothing waiting') }}</b>
      <p class="dim">{{ t('When your team needs a decision, it lands here.') }}</p>
    </div>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.head h1 { font-size: 20px; margin: 0; }
.dim { color: var(--muted); font-size: 13px; margin: 0; }
.quiet { border: 0; background: none; color: var(--muted); min-height: 44px; padding: 0 6px; }

.tabs { display: flex; gap: 8px; overflow-x: auto; }
.chip { flex: none; display: inline-flex; align-items: center; gap: 6px; padding: 0 14px;
        min-height: 44px; border: 1px solid var(--line); background: var(--surface);
        border-radius: 999px; color: var(--ink); font-weight: 600; font-size: 14px; }
.chip.on { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }
.count { min-width: 20px; padding: 0 6px; border-radius: 999px; font-size: 12px;
         background: var(--warn-soft); color: var(--warn); }
.chip.on .count { background: var(--on-primary); color: var(--primary); }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: flex; flex-direction: column; gap: 4px; }
.top { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; }
.name { font-size: 16px; overflow-wrap: anywhere; }
.pill { align-self: flex-start; font-size: 12px; font-weight: 700; padding: 3px 8px;
        border-radius: 6px; }
.pill.warn { background: var(--warn-soft); color: var(--warn); }

.amount { display: flex; align-items: center; gap: 10px; margin-top: 4px; }
.amount input { flex: 0 0 140px; width: 140px; min-width: 0; text-align: right;
                font-weight: 700; }

.why { display: flex; flex-direction: column; gap: 8px; margin-top: 6px; }
.why textarea { font: inherit; padding: 10px; border: 1px solid var(--line); border-radius: 8px;
                min-height: 64px; resize: vertical; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-top: 8px; }
.pair button { min-height: 48px; border-radius: 8px; font-weight: 700; font-size: 15px;
               display: inline-flex; align-items: center; justify-content: center; gap: 6px; }
.yes { border: 0; background: var(--primary); color: var(--on-primary); }
.no { border: 0; background: var(--crit); color: #fff; }
.ghost { border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
.pair button:disabled { opacity: .6; }

.note { color: var(--muted); font-size: 14px; text-align: center; padding: 20px 0; margin: 0; }
.note.ok { color: var(--ok); background: var(--ok-soft); border-radius: 8px; padding: 10px 12px; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.empty { text-align: center; padding: 40px 16px; color: var(--muted); display: flex;
         flex-direction: column; gap: 6px; align-items: center; }
.empty b { color: var(--ink); }
.empty p { margin: 0; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
