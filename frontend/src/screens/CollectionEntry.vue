<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid } from '../db'
import { formatRupees } from '../lib/money'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'

const MODES = [
  { value: 'Cash', label: 'Cash' },
  { value: 'UPI', label: 'UPI' },
  { value: 'Cheque', label: 'Cheque' },
  { value: 'Bank Transfer', label: 'Bank' },
]
const NOTES = [500, 200, 100, 50, 20, 10]

const route = useRoute()
const router = useRouter()

const position = ref(null)
const amount = ref(null)
const mode = ref('Cash')
const instrumentNo = ref('')
const instrumentBank = ref('')
const collectedFrom = ref('')
const counted = ref({})
const confirmed = ref(false)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const done = ref(null)

const picked = computed(() => String(route.query.bills || '').split(',').filter(Boolean))
const bills = computed(() =>
  (position.value?.bills || []).filter((b) => picked.value.includes(b.reference_name))
)
const pickedTotal = computed(() => bills.value.reduce((t, b) => t + b.pending, 0))

// The denomination tally is what turns "the deposit is short" into a conversation about a
// specific bundle three days later. Optional, and only shown for cash.
const tallied = computed(() =>
  NOTES.reduce((total, note) => total + note * (Number(counted.value[note]) || 0), 0)
)
const tallyGap = computed(() => tallied.value - (Number(amount.value) || 0))
const anyCounted = computed(() => NOTES.some((n) => Number(counted.value[n]) > 0))

const ready = computed(() => {
  if (!(Number(amount.value) > 0)) return false
  if (!confirmed.value) return false
  if (['Cheque', 'DD'].includes(mode.value) && !instrumentNo.value.trim()) return false
  return true
})

onMounted(async () => {
  try {
    position.value = await api.outstanding(route.params.outlet)
    const suggested = Number(route.query.amount)
    amount.value = suggested > 0 ? suggested : null
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not load what this shop owes.'
  } finally {
    loading.value = false
  }
})

function setNote(note, value) {
  const n = Math.max(0, Number(String(value ?? '').trim()) || 0)
  counted.value = { ...counted.value, [note]: n || null }
}

function bump(note, delta) {
  setNote(note, (Number(counted.value[note]) || 0) + delta)
}

function useTally() {
  amount.value = tallied.value
}

/** Money spread across the ticked bills, oldest first, and whatever is left over named. */
function allocate() {
  let left = Number(amount.value) || 0
  const rows = []
  for (const bill of bills.value) {
    if (left <= 0) break
    const take = Math.min(left, bill.pending)
    rows.push({
      reference_type: 'FieldMate Order',
      reference_name: bill.reference_name,
      bill_no: bill.bill_no,
      bill_date: bill.bill_date,
      due_date: bill.due_date,
      outstanding_amount: bill.pending,
      allocated_amount: take,
    })
    left -= take
  }
  return rows
}

async function submit() {
  error.value = ''
  busy.value = true
  try {
    const open = visitStore.activeVisit.value
    done.value = await api.collectionCreate({
      party_type: 'Outlet',
      outlet: position.value.outlet,
      visit: open?.serverName || open?.clientUuid || null,
      amount: Number(amount.value),
      mode: mode.value,
      instrument_no: instrumentNo.value || null,
      instrument_bank: instrumentBank.value || null,
      collected_from_name: collectedFrom.value || null,
      denominations: anyCounted.value
        ? NOTES.filter((n) => counted.value[n]).map((n) => `${n}x${counted.value[n]}`).join(' ')
        : null,
      allocations: allocate(),
      client_uuid: crypto.randomUUID(),
      device_id: await deviceUuid(),
    })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not record the collection.'
  } finally {
    busy.value = false
  }
}

function finish() {
  const open = visitStore.activeVisit.value
  router.replace(open ? { name: 'visit', params: { uuid: open.clientUuid } } : '/today')
}
</script>

<template>
  <div v-if="done" class="wrap screen">
    <div class="top">
      <div class="card ok-card">
        <p class="badge"><Icon name="check" size="22" /><span>Collection recorded</span></p>
        <b class="big tnum">{{ formatRupees(done.amount) }}</b>
        <p class="rec tnum">Receipt {{ done.receipt_no }}</p>
        <p v-if="done.unallocated_amount" class="muted tnum">
          {{ formatRupees(done.unallocated_amount) }} of it is on account, against no particular bill.
        </p>
        <p class="muted">
          <Icon name="cloud-off" size="15" />
          Saved on this phone. Hand it in with your deposit tonight.
        </p>
      </div>
    </div>
    <div class="bottom">
      <button class="btn-primary" @click="finish">Done</button>
    </div>
  </div>

  <div v-else class="wrap screen">

    <div v-if="loading" class="muted pad">Loading…</div>

    <template v-else-if="position">
      <div class="head">
        <h1>{{ position.outlet_name }}</h1>
        <p class="muted tnum">
          Owes {{ formatRupees(position.outstanding) }}<template v-if="bills.length">
            · {{ bills.length }} bill{{ bills.length > 1 ? 's' : '' }} selected,
            {{ formatRupees(pickedTotal) }}</template>
        </p>
      </div>

      <div class="card">
        <label class="label" for="amt">How much did you take?</label>
        <div class="amt">
          <span>₹</span>
          <input id="amt" class="tnum" type="number" inputmode="decimal" min="0"
                 v-model="amount" placeholder="0.00" />
        </div>
        <div class="chips">
          <button v-if="position.overdue" type="button" @click="amount = position.overdue">
            Overdue {{ formatRupees(position.overdue) }}
          </button>
          <button v-if="pickedTotal" type="button" @click="amount = pickedTotal">
            Selected {{ formatRupees(pickedTotal) }}
          </button>
          <button type="button" @click="amount = position.outstanding">
            Full {{ formatRupees(position.outstanding) }}
          </button>
        </div>
      </div>

      <h2 class="shead">How was it paid?</h2>
      <div class="modes">
        <button v-for="m in MODES" :key="m.value" type="button"
                class="mode" :class="{ on: mode === m.value }" @click="mode = m.value">
          <span>{{ m.label }}</span>
          <Icon v-if="mode === m.value" name="check" size="18" />
        </button>
      </div>

      <div v-if="['Cheque', 'Bank Transfer', 'UPI'].includes(mode)" class="card">
        <label class="label" for="ref">
          {{ mode === 'Cheque' ? 'Cheque number' : 'Reference number' }}
        </label>
        <input id="ref" v-model="instrumentNo" :placeholder="mode === 'Cheque' ? '004921' : 'UTR / txn id'" />
        <template v-if="mode === 'Cheque'">
          <label class="label" for="bank">Bank</label>
          <input id="bank" v-model="instrumentBank" placeholder="HDFC Bank" />
          <p class="muted small">
            <Icon name="info" size="15" />
            Without the number nobody can chase it if it bounces.
          </p>
        </template>
      </div>

      <!-- Cash only. A note counter on a UPI payment is a form asking a question nobody has. -->
      <template v-if="mode === 'Cash'">
        <div class="shead row">
          <h2>Count the notes <span class="muted">(optional)</span></h2>
          <span v-if="anyCounted" class="tnum" :class="tallyGap === 0 ? 'ok' : 'warn'">
            {{ tallyGap === 0 ? 'Matches' : formatRupees(Math.abs(tallyGap)) + (tallyGap > 0 ? ' more' : ' short') }}
          </span>
        </div>
        <div class="card notes">
          <div v-for="note in NOTES" :key="note" class="nrow">
            <span class="denom tnum">₹{{ note }}</span>
            <div class="stepper">
              <button type="button" @click="bump(note, -1)" :aria-label="'One fewer ' + note">−</button>
              <input class="tnum" type="number" inputmode="numeric" min="0"
                     :value="counted[note]" placeholder="0"
                     @input="setNote(note, $event.target.value)" />
              <button type="button" @click="bump(note, 1)" :aria-label="'One more ' + note">+</button>
            </div>
            <span class="sub tnum muted">{{ counted[note] ? formatRupees(note * counted[note]) : '—' }}</span>
          </div>
          <div v-if="anyCounted" class="ntotal tnum">
            <span>Counted</span>
            <b>{{ formatRupees(tallied) }}</b>
            <button v-if="tallyGap !== 0" type="button" class="use" @click="useTally">
              Use this
            </button>
          </div>
        </div>
      </template>

      <div class="card">
        <label class="label" for="from">Who handed it over?</label>
        <input id="from" v-model="collectedFrom" placeholder="Ramesh Sharma" />
        <p class="muted small">
          A receipt naming only a shop settles no argument three weeks later.
        </p>

        <label class="confirm" :class="{ on: confirmed }">
          <input type="checkbox" v-model="confirmed" />
          <span class="box"><Icon v-if="confirmed" name="check" size="16" /></span>
          <span>
            I have taken {{ formatRupees(Number(amount) || 0) }} in {{ mode.toLowerCase() }}
            <template v-if="collectedFrom">from {{ collectedFrom }}</template>.
          </span>
        </label>
      </div>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>

      <div class="bottom">
        <p class="muted note">
          <Icon name="cloud-off" size="15" />
          Nothing is posted anywhere. This is money in your hand until you deposit it.
        </p>
        <button class="btn-primary" :disabled="busy || !ready" @click="submit">
          {{ busy ? 'Recording…' : 'Record collection' }}
        </button>
        <button class="btn-plain" @click="router.back()">Cancel</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.pad { padding: 16px; }
.head { padding: 4px 0 12px; }
h1 { margin: 0; font-size: 20px; }
.head .muted { margin: 3px 0 0; font-size: 14px; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; margin-bottom: 12px; }
.label { display: block; font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em;
         color: var(--muted); margin-bottom: 6px; }
.card .label + input { margin-bottom: 12px; }
.small { font-size: 13px; margin: 0; display: flex; align-items: center; gap: 6px; }

.amt { display: flex; align-items: center; gap: 8px; border: 1px solid var(--line);
       border-radius: 6px; padding: 0 12px; background: var(--surface); }
.amt span { font-size: 22px; color: var(--primary); font-weight: 700; }
.amt input { border: 0; font-size: 24px; font-weight: 700; padding: 0; min-height: 56px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.chips button { min-height: 48px; padding: 0 12px; background: var(--primary-soft);
                color: var(--primary); border: 0; font-size: 14px; font-weight: 600; }

.shead { margin: 18px 0 8px; font-size: 14px; text-transform: uppercase;
         letter-spacing: 0.04em; color: var(--muted); }
.shead.row { display: flex; align-items: center; justify-content: space-between; }
.shead h2 { margin: 0; font: inherit; }
.shead .ok { color: var(--ok); }
.shead .warn { color: var(--warn); }

.modes { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; }
.mode { display: flex; align-items: center; justify-content: space-between; gap: 6px;
        min-height: 52px; padding: 0 12px; background: var(--surface);
        border: 1px solid var(--line); color: var(--ink); font-weight: 600; }
.mode.on { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }

.notes { padding: 4px 14px; }
.nrow { display: flex; align-items: center; gap: 10px; padding: 8px 0; }
.nrow + .nrow { border-top: 1px solid var(--line); }
.denom { width: 56px; font-weight: 700; color: var(--primary); }
.stepper { display: flex; align-items: center; border: 1px solid var(--line); border-radius: 6px; }
.stepper button { width: 48px; min-height: 48px; border: 0; background: var(--surface);
                  font-size: 20px; color: var(--ink); border-radius: 0; }
.stepper input { width: 56px; text-align: center; border: 0; border-left: 1px solid var(--line);
                 border-right: 1px solid var(--line); border-radius: 0; font-weight: 700; }
.sub { flex: 1; text-align: right; font-size: 14px; }
.ntotal { display: flex; align-items: center; gap: 10px; padding: 12px 0 10px;
          border-top: 2px solid var(--line); font-weight: 600; }
.ntotal b { flex: 1; text-align: right; font-size: 18px; }
.use { min-height: 48px; padding: 0 12px; background: var(--primary-soft); color: var(--primary);
       border: 0; font-size: 14px; font-weight: 600; }

.confirm { display: flex; align-items: flex-start; gap: 10px; margin-top: 14px;
           padding: 12px; border-radius: 6px; background: var(--bg); cursor: pointer;
           font-size: 15px; line-height: 1.45; }
.confirm.on { background: var(--ok-soft); color: var(--ok); }
.confirm input { position: absolute; opacity: 0; width: 0; height: 0; }
.confirm .box { width: 24px; height: 24px; flex-shrink: 0; border: 2px solid var(--line);
                border-radius: 4px; display: grid; place-items: center; background: var(--surface); }
.confirm.on .box { background: var(--ok); border-color: var(--ok); color: #fff; }

.bottom { padding-top: 18px; }
.note { display: flex; align-items: center; justify-content: center; gap: 6px;
        margin: 0 0 8px; font-size: 14px; text-align: center; }
.err { display: flex; align-items: center; gap: 8px; margin: 14px 0 0; background: var(--crit-soft);
       color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.ok-card { background: var(--ok-soft); border-color: var(--ok); text-align: center; }
.badge { display: flex; align-items: center; justify-content: center; gap: 8px;
         margin: 0; color: var(--ok); font-weight: 600; }
.big { display: block; font-size: 26px; margin: 8px 0 2px; }
.rec { margin: 0 0 10px; font-size: 14px; }
.top { flex: 1; display: flex; flex-direction: column; justify-content: center; }
</style>
