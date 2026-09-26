<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { api, ApiError } from '../api/client'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'
import OfflineStrip from '../components/OfflineStrip.vue'

const TYPES = [
  { key: 'Travel', label: 'Travel' },
  { key: 'Food', label: 'Food' },
  { key: 'Stay', label: 'Stay' },
  { key: 'Other', label: 'Other' },
]

const today = new Date().toISOString().slice(0, 10)

const type = ref('Travel')
const claimDate = ref(today)
const estimate = ref(null)
const history = ref(null)

const editingDistance = ref(false)
const distance = ref(0)
const amount = ref(0)
const remarks = ref('')
const receipt = ref(null)

const loading = ref(true)
const saving = ref(false)
const error = ref('')
const done = ref('')

const isTravel = computed(() => type.value === 'Travel')
const trailKm = computed(() => estimate.value?.trail_distance_km || 0)
const rate = computed(() => estimate.value?.rate_per_km || 0)

// What the rule gives, recomputed on the phone as the rep edits so the button can carry the
// figure. The server computes it again and its answer is the one that counts - this is a
// preview, and the two agreeing is what makes the preview worth showing.
const computedAmount = computed(() => {
  if (isTravel.value) return Math.round(distance.value * rate.value * 100) / 100
  return estimate.value?.amount || 0
})

const payable = computed(() => (amount.value ? Number(amount.value) : computedAmount.value))

const overTrail = computed(() => (isTravel.value ? distance.value - trailKm.value : 0))
const overPct = computed(() =>
  trailKm.value ? Math.round((overTrail.value / trailKm.value) * 1000) / 10 : 0
)

// The one sentence the rep needs before they tap. A claim over the trail still goes in - what
// it does not do is settle itself.
const willWait = computed(() => {
  const tolerance = estimate.value?.tolerance_pct ?? 10
  if (isTravel.value && overTrail.value > 0 && overPct.value > tolerance) {
    return `${overTrail.value.toFixed(1)} km more than your trail recorded — your manager will see this before it is paid.`
  }
  if (isTravel.value && !trailKm.value && distance.value > 0) {
    return 'No GPS trail was recorded for that day, so this needs your manager.'
  }
  if (payable.value > computedAmount.value + 0.005) {
    return 'More than the rule allows — your manager will see this before it is paid.'
  }
  return ''
})

const needsReceipt = computed(() => {
  const above = estimate.value?.receipt_required_above || 0
  return above > 0 && payable.value > above
})

const alreadyFiled = computed(() => estimate.value?.already_claimed)

const canSubmit = computed(() =>
  !saving.value && payable.value > 0 && !alreadyFiled.value
  && !(needsReceipt.value && !receipt.value)
  && !(isTravel.value && !rate.value)
)

async function loadEstimate() {
  loading.value = true
  error.value = ''
  done.value = ''
  try {
    estimate.value = await api.expenseEstimate(claimDate.value, type.value)
    distance.value = estimate.value.claimed_distance_km || 0
    amount.value = 0
    editingDistance.value = false
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not read your trail for that day.'
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  try {
    history.value = await api.expensesMine(12)
  } catch {
    // A failed history is not a reason to block filing a claim.
    history.value = null
  }
}

async function file() {
  saving.value = true
  error.value = ''
  try {
    const result = await api.expenseCreate({
      claim_date: claimDate.value,
      expense_type: type.value,
      claimed_distance_km: isTravel.value ? distance.value : 0,
      claimed_amount: payable.value,
      remarks: remarks.value,
      receipt: receipt.value,
      client_uuid: crypto.randomUUID(),
      submit: 1,
    })
    done.value = result.claim_status === 'Pending Approval'
      ? `Filed. ${formatRupees(result.claimed_amount)} waiting on your manager.`
      : `Filed and approved. ${formatRupees(result.approved_amount)}.`
    await Promise.all([loadEstimate(), loadHistory()])
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not file that. Try again.'
  } finally {
    saving.value = false
  }
}

function tone(status) {
  if (status === 'Approved' || status === 'Settled') return 'ok'
  if (status === 'Rejected' || status === 'Cancelled') return 'crit'
  return 'warn'
}

watch([type, claimDate], loadEstimate)
onMounted(async () => {
  await Promise.all([loadEstimate(), loadHistory()])
})
</script>

<template>
  <div class="wrap">
    <OfflineStrip />

    <header class="head">
      <h1>Claim expenses</h1>
      <input v-model="claimDate" type="date" class="date" :max="today" aria-label="Day claimed" />
    </header>

    <div class="chips">
      <button v-for="t in TYPES" :key="t.key" class="chip"
              :class="{ on: type === t.key }" @click="type = t.key">
        {{ t.label }}
      </button>
    </div>

    <p v-if="loading" class="note">Loading…</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else>
      <div v-if="alreadyFiled" class="note warn">
        You already filed a {{ type.toLowerCase() }} claim for this day ({{ alreadyFiled }}).
      </div>

      <!-- Travel: the trail, and what the rep says instead -->
      <section v-if="isTravel" class="card">
        <div class="row">
          <div class="dist">
            <Icon name="route" />
            <div>
              <div class="big tnum">{{ trailKm.toFixed(1) }} km <span class="badge">GPS trail</span></div>
              <div class="dim">
                Recorded across {{ estimate.check_ins }} check-in<span v-if="estimate.check_ins !== 1">s</span>
                · {{ estimate.trail_ping_count }} pings
              </div>
            </div>
          </div>
          <button class="link" @click="editingDistance = !editingDistance">
            {{ editingDistance ? 'Done' : 'Edit' }}
          </button>
        </div>

        <div v-if="editingDistance" class="edit">
          <label for="km">Distance you actually travelled (km)</label>
          <input id="km" v-model.number="distance" type="number" step="0.5" min="0" inputmode="decimal" />
          <p class="dim fine">
            The trail misses pings in basements and in markets with no signal, so a little more
            is normal. A lot more waits for your manager.
          </p>
        </div>

        <div v-if="!rate" class="note crit">
          No travel rate is set up yet. Ask your admin — nothing can be claimed for travel
          until it is.
        </div>
        <div v-else class="calc">
          <span class="dim tnum">{{ distance.toFixed(1) }} km × {{ formatRupees(rate) }}/km</span>
          <span class="big tnum">{{ formatRupees(computedAmount) }}</span>
        </div>
      </section>

      <!-- Everything else: a flat allowance or a typed amount -->
      <section v-else class="card">
        <div v-if="estimate.allowance_cap" class="calc">
          <span class="dim">Daily {{ type.toLowerCase() }} allowance</span>
          <span class="big tnum">{{ formatRupees(estimate.allowance_cap) }}</span>
        </div>
        <div class="edit">
          <label for="amt">Amount claimed</label>
          <input id="amt" v-model.number="amount" type="number" step="1" min="0"
                 inputmode="decimal" :placeholder="String(computedAmount)" />
        </div>
      </section>

      <section class="card">
        <label for="rx">Receipt {{ needsReceipt ? '(required)' : '(optional)' }}</label>
        <button class="attach" :class="{ need: needsReceipt && !receipt }">
          <Icon name="camera" />
          <span>{{ receipt ? 'Receipt attached' : 'Attach a photo of the bill' }}</span>
        </button>

        <label for="note">Remarks</label>
        <input id="note" v-model="remarks" type="text"
               placeholder="Where you went, e.g. Beat 4 to Swargate" />
      </section>

      <div v-if="willWait" class="note warn">{{ willWait }}</div>
      <div v-if="done" class="note ok">{{ done }}</div>

      <button class="btn-primary" :disabled="!canSubmit" @click="file">
        {{ saving ? 'Filing…' : `File claim (${formatRupees(payable)})` }}
      </button>

      <p class="dim fine centre">
        Travel claims are checked against your own check-in times and locations.
      </p>

      <!-- Recent claims -->
      <section v-if="history?.claims?.length" class="list">
        <div class="row">
          <h2>Recent claims</h2>
          <span class="dim">This month: {{ formatRupees(history.approved_this_month) }} approved</span>
        </div>
        <div v-for="c in history.claims" :key="c.name" class="item">
          <div>
            <div class="strong">
              {{ c.claim_date.slice(8) }}/{{ c.claim_date.slice(5, 7) }} · {{ c.expense_type }}
              <span v-if="c.expense_type === 'Travel'" class="dim">({{ c.claimed_distance_km }} km)</span>
            </div>
            <div class="tnum">{{ formatRupees(c.approved_amount || c.claimed_amount) }}</div>
            <div v-if="c.rejection_reason" class="dim">{{ c.rejection_reason }}</div>
          </div>
          <span class="pill" :class="tone(c.claim_status)">{{ c.claim_status }}</span>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.head h1 { font-size: 20px; margin: 0; }
.date { width: auto; min-height: 44px; }
.chips { display: flex; gap: 8px; overflow-x: auto; }
.chip { flex: none; padding: 0 18px; min-height: 48px; border: 1px solid var(--line);
        background: var(--surface); border-radius: 999px; color: var(--ink); font-weight: 600; }
.chip.on { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.row { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.row h2 { font-size: 15px; margin: 0; }
.dist { display: flex; gap: 10px; align-items: flex-start; }
.big { font-size: 19px; font-weight: 700; }
.badge { background: var(--ok-soft); color: var(--ok); font-size: 11px; font-weight: 700;
         padding: 2px 8px; border-radius: 6px; letter-spacing: .04em; text-transform: uppercase; }
.link { border: 0; background: none; color: var(--primary); text-decoration: underline;
        font-weight: 600; min-height: 44px; padding: 0 6px; }
.edit { background: var(--bg); border-radius: 8px; padding: 10px; display: flex;
        flex-direction: column; gap: 6px; }
.calc { display: flex; align-items: center; justify-content: space-between;
        background: var(--bg); border-radius: 8px; padding: 10px 12px; }
.attach { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 64px;
          padding: 12px; border: 1px dashed var(--line); background: var(--bg);
          border-radius: 8px; text-align: left; color: var(--ink); font-weight: 500; }
.attach.need { border-color: var(--crit); color: var(--crit); }
label { font-size: 13px; color: var(--muted); }
.note { border-radius: 8px; padding: 10px 12px; font-size: 14px; }
.note.crit { background: var(--crit-soft); color: var(--crit); }
.note.warn { background: var(--warn-soft); color: var(--warn); }
.note.ok { background: var(--ok-soft); color: var(--ok); }
.list { display: flex; flex-direction: column; gap: 8px; }
.item { display: flex; align-items: center; justify-content: space-between; gap: 10px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; }
.strong { font-weight: 600; }
.dim { color: var(--muted); font-size: 13px; }
.fine { font-size: 12px; margin: 0; }
.centre { text-align: center; }
.pill { font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 6px; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.crit { background: var(--crit-soft); color: var(--crit); }
.tnum { font-variant-numeric: tabular-nums; }
</style>
