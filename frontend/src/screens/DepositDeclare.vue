<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid } from '../db'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'

const CHANNELS = [
  { value: 'Cash Deposit Machine', label: 'Cash deposit machine', hint: 'CDM or recycler' },
  { value: 'Bank Branch', label: 'Bank branch', hint: 'Over the counter' },
  { value: 'Distributor Counter', label: 'Distributor counter', hint: 'Handed over at the depot' },
  { value: 'Pickup Agent', label: 'Pickup agent', hint: 'Collected from you' },
]

const router = useRouter()

const inHand = ref(null)
const picked = ref(new Set())
const channel = ref('Cash Deposit Machine')
const referenceNo = ref('')
const depositedAt = ref('')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const done = ref(null)

const rows = computed(() => inHand.value?.collections || [])
const selected = computed(() => rows.value.filter((r) => picked.value.has(r.name)))
const selectedTotal = computed(() => selected.value.reduce((t, r) => t + r.amount, 0))
const cheques = computed(() => selected.value.filter((r) => ['Cheque', 'DD'].includes(r.mode)))
const cash = computed(() => selected.value.filter((r) => !['Cheque', 'DD'].includes(r.mode)))

const ready = computed(() => selected.value.length > 0 && referenceNo.value.trim().length > 0)

onMounted(async () => {
  try {
    inHand.value = await api.cashInHand()
    // Everything ticked to start. A rep depositing a subset is the exception, and making them
    // tick nine rows before they can do the ordinary thing is how the ordinary thing gets
    // skipped.
    picked.value = new Set(rows.value.map((r) => r.name))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not load what you are carrying.'
  } finally {
    loading.value = false
  }
})

function toggle(row) {
  const next = new Set(picked.value)
  next.has(row.name) ? next.delete(row.name) : next.add(row.name)
  picked.value = next
}

async function submit() {
  error.value = ''
  busy.value = true
  try {
    done.value = await api.depositDeclare({
      collections: [...picked.value],
      channel: channel.value,
      reference_no: referenceNo.value,
      deposited_at: depositedAt.value || null,
      client_uuid: crypto.randomUUID(),
      device_id: await deviceUuid(),
    })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not record the deposit.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="done" class="wrap screen">
    <div class="top">
      <div class="card ok-card">
        <p class="badge"><Icon name="check" size="22" /><span>Deposit declared</span></p>
        <b class="big tnum">{{ formatRupees(done.total_amount) }}</b>
        <p class="rec tnum">{{ done.reference_no }}</p>
        <!-- Honest about what has and has not happened. The rep saying where the money went is
             not the money arriving, and a screen that implies otherwise is the one thing that
             would make this control worthless. -->
        <p class="muted">
          Your office will confirm it once the money shows up. Nothing is posted until then.
        </p>
      </div>
    </div>
    <div class="bottom">
      <button class="btn-primary" @click="router.replace('/today')">Done</button>
    </div>
  </div>

  <div v-else class="wrap screen">

    <div v-if="loading" class="muted pad">Loading what you are carrying…</div>

    <div v-else-if="!rows.length" class="card pad">
      <p><Icon name="check" size="18" /> You are not carrying anything.</p>
      <p class="muted">Every collection you have taken is already in a deposit.</p>
    </div>

    <template v-else>
      <div class="head">
        <h1>Hand in the money</h1>
        <p class="muted tnum">{{ rows.length }} collection{{ rows.length > 1 ? 's' : '' }} in hand</p>
      </div>

      <!-- Named, not merely flagged. "You have been carrying money since Tuesday" is something a
           rep acts on; "overdue" is not. -->
      <div v-if="inHand.is_overdue" class="card warn-card">
        <p class="wtitle">
          <Icon name="alert" size="20" />
          <span>You have been carrying money for {{ inHand.oldest_days }} days.</span>
        </p>
        <p class="small">Anything over {{ inHand.threshold_days }} days is reported to your manager.</p>
      </div>

      <div class="card tiles tnum">
        <div><span class="label">Cash</span><b>{{ formatRupees(inHand.cash_amount) }}</b></div>
        <div><span class="label">Cheques</span><b>{{ formatRupees(inHand.cheque_amount) }}</b></div>
        <div><span class="label">In hand</span><b>{{ formatRupees(inHand.total_amount) }}</b></div>
      </div>

      <h2 class="shead">What is in this deposit</h2>
      <article v-for="row in rows" :key="row.name"
               class="row" :class="{ on: picked.has(row.name) }" @click="toggle(row)">
        <span class="box" :class="{ ticked: picked.has(row.name) }">
          <Icon v-if="picked.has(row.name)" name="check" size="16" />
        </span>
        <div class="rmain">
          <b>{{ row.party }}</b>
          <span class="muted tnum">
            {{ row.collection_date }} · {{ row.mode }}
            <template v-if="row.instrument_no">· {{ row.instrument_no }}</template>
            · {{ row.receipt_no }}
          </span>
        </div>
        <b class="tnum amt">{{ formatRupees(row.amount) }}</b>
      </article>

      <h2 class="shead">Where did it go?</h2>
      <button v-for="c in CHANNELS" :key="c.value" type="button"
              class="chan" :class="{ on: channel === c.value }" @click="channel = c.value">
        <span>
          <b>{{ c.label }}</b>
          <em>{{ c.hint }}</em>
        </span>
        <Icon v-if="channel === c.value" name="check" size="18" />
      </button>

      <div class="card">
        <label class="label" for="ref">Slip or transaction number</label>
        <input id="ref" v-model="referenceNo" placeholder="CDM-8849201" />
        <p class="muted small">
          <Icon name="info" size="15" />
          Without it, a declared deposit is something nobody can check.
        </p>
        <label class="label" for="where">Branch or machine</label>
        <input id="where" v-model="depositedAt" placeholder="SBI Main Market CDM #02" />
      </div>

      <div v-if="cheques.length" class="card">
        <span class="label">Cheques in the envelope</span>
        <div v-for="c in cheques" :key="c.name" class="chq tnum">
          <span>{{ c.instrument_no || 'no number' }} · {{ c.party }}</span>
          <b>{{ formatRupees(c.amount) }}</b>
        </div>
      </div>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>

      <div class="bottom">
        <p class="muted note tnum">
          Declaring {{ formatRupees(selectedTotal) }} ·
          {{ cash.length }} cash, {{ cheques.length }} cheque{{ cheques.length === 1 ? '' : 's' }}
        </p>
        <button class="btn-primary" :disabled="busy || !ready" @click="submit">
          {{ busy ? 'Recording…' : 'Declare ' + formatRupees(selectedTotal) }}
        </button>
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
.card .label + input { margin-bottom: 8px; }
.small { display: flex; align-items: center; gap: 6px; font-size: 13px; margin: 0 0 12px; }

.warn-card { background: var(--warn-soft); border-color: var(--warn); color: var(--warn); }
.wtitle { display: flex; align-items: flex-start; gap: 8px; margin: 0 0 4px; font-weight: 600; }

.tiles { display: flex; }
.tiles div { flex: 1; text-align: center; }
.tiles div + div { border-left: 1px solid var(--line); }
.tiles b { display: block; font-size: 17px; margin-top: 3px; }
.tiles .label { margin: 0; }

.shead { margin: 18px 0 8px; font-size: 14px; text-transform: uppercase;
         letter-spacing: 0.04em; color: var(--muted); }

.row { display: flex; align-items: center; gap: 10px; background: var(--surface);
       border: 1px solid var(--line); border-radius: 6px; padding: 12px; margin-bottom: 10px;
       cursor: pointer; }
.row.on { background: var(--primary-soft); border-color: var(--primary); }
.box { width: 24px; height: 24px; flex-shrink: 0; border: 2px solid var(--line);
       border-radius: 4px; display: grid; place-items: center; background: var(--surface); }
.box.ticked { background: var(--primary); border-color: var(--primary); color: var(--on-primary); }
.rmain { flex: 1; display: grid; gap: 2px; min-width: 0; }
.rmain .muted { font-size: 13px; }
.amt { white-space: nowrap; }

.chan { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 10px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 12px 14px; margin-bottom: 8px; min-height: 52px; color: var(--ink); }
.chan.on { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }
.chan > span { display: grid; text-align: left; }
.chan em { font-style: normal; font-size: 13px; opacity: 0.75; }

.chq { display: flex; justify-content: space-between; padding: 8px 0; font-size: 14px; }
.chq + .chq { border-top: 1px solid var(--line); }

.bottom { padding-top: 18px; }
.note { text-align: center; margin: 0 0 8px; font-size: 14px; }
.err { display: flex; align-items: center; gap: 8px; margin: 14px 0 0; background: var(--crit-soft);
       color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.ok-card { background: var(--ok-soft); border-color: var(--ok); text-align: center; }
.badge { display: flex; align-items: center; justify-content: center; gap: 8px;
         margin: 0; color: var(--ok); font-weight: 600; }
.big { display: block; font-size: 26px; margin: 8px 0 2px; }
.rec { margin: 0 0 10px; font-size: 14px; }
.top { flex: 1; display: flex; flex-direction: column; justify-content: center; }
</style>
