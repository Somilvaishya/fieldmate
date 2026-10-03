<script setup>
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api/client'
import { deviceUuid } from '../db'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'

const inHand = ref(null)
const collections = ref([])
const loading = ref(true)
const error = ref('')
// Separate from `error`: cash in hand failing hides the whole screen, a receipt list failing
// only costs the list below it.
const listError = ref('')

const TONE = {
  Collected: 'warn',
  Deposited: 'calm',
  Confirmed: 'ok',
  Bounced: 'crit',
  Cancelled: 'crit',
}

// A shop's cash is the distributor's, passing through the rep's satchel; a distributor's is
// ours. The rep does not need the accounting words, but they do need to know that both are
// money they are carrying and answerable for.
const carrying = computed(() => Number(inHand.value?.total_amount || 0))
const overdue = computed(() => !!inHand.value?.is_overdue)

function day(value) {
  if (!value) return ''
  const [y, m, d] = String(value).slice(0, 10).split('-')
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${d} ${months[Number(m) - 1]}`
}

async function load() {
  loading.value = true
  error.value = ''
  listError.value = ''
  try {
    // Cash in hand is the figure the rep is answerable for, so it is the one that must load.
    inHand.value = await api.cashInHand()
    try {
      const data = await api.collectionsMine()
      collections.value = data.collections || data || []
    } catch (e) {
      // Not swallowed. This used to fall through to an empty list, so a broken call and a rep
      // who has genuinely collected nothing looked exactly alike - and the wrong one of those
      // is the one a rep would act on.
      collections.value = []
      listError.value = e instanceof ApiError
        ? e.message
        : 'Could not load your recent receipts.'
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not load your collections.'
  } finally {
    loading.value = false
  }
}

// ------------------------------------------------------- money taken from the depot itself

// A shop's cash belongs to its distributor and only passes through the rep's satchel. Money
// taken FROM a distributor is ours, and it is the only kind that ever reaches the ledger
// (ADR-025) - which is exactly why there has to be a way to record it, and until now there was
// not one on the phone at all.
const depots = ref([])
const taking = ref(false)
const form = ref({ distributor: '', amount: '', mode: 'Cash', reference: '', from: '' })
const saveError = ref('')
const saving = ref(false)

// Minted once when the form opens and kept until it succeeds, never per attempt. If the first
// save reaches the server and the answer does not, tapping again must land as the same receipt -
// a fresh uuid on the retry is how a rep ends up having collected the depot's money twice.
const draftUuid = ref(null)

const MODES = ['Cash', 'UPI', 'Cheque', 'DD', 'Bank Transfer']
const needsReference = computed(() => form.value.mode !== 'Cash')

const canSave = computed(() =>
  !!form.value.distributor
  && Number(form.value.amount) > 0
  && (!needsReference.value || !!form.value.reference.trim())
)

async function openTake() {
  taking.value = true
  saveError.value = ''
  draftUuid.value = crypto.randomUUID()
  if (depots.value.length) return
  try {
    const data = await api.distributors()
    depots.value = data.distributors || []
    if (depots.value.length === 1) form.value.distributor = depots.value[0].distributor
  } catch (e) {
    saveError.value = e instanceof ApiError
      ? e.message
      : 'Could not load your depots. This one needs signal.'
  }
}

function closeTake() {
  taking.value = false
  saveError.value = ''
  draftUuid.value = null
  form.value = { distributor: '', amount: '', mode: 'Cash', reference: '', from: '' }
}

async function takeFromDepot() {
  saving.value = true
  saveError.value = ''
  try {
    await api.collectionCreate({
      party_type: 'Distributor',
      distributor: form.value.distributor,
      amount: Number(form.value.amount),
      mode: form.value.mode,
      instrument_no: form.value.reference.trim() || null,
      collected_from_name: form.value.from.trim() || null,
      client_uuid: draftUuid.value,
      device_id: await deviceUuid(),
    })
    closeTake()
    await load()
  } catch (e) {
    saveError.value = e instanceof ApiError
      ? e.message
      : 'Could not record it. This one needs signal — nothing was saved.'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="wrap">
    <header class="head">
      <div>
        <h1>Collections</h1>
        <p class="dim">What you took, and what is still with you</p>
      </div>
      <button class="quiet" :disabled="loading" @click="load" aria-label="Refresh">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <p v-if="loading" class="note">Loading…</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else>
      <!-- The satchel. Top of the screen because it is the only number here the rep is
           personally answerable for. -->
      <RouterLink to="/deposit" class="hand" :class="{ late: overdue }">
        <Icon name="tag" size="22" />
        <span class="body">
          <b class="tnum">{{ formatRupees(carrying) }} with you</b>
          <em v-if="overdue">
            Carrying it {{ inHand.oldest_days }} days — your manager is told
          </em>
          <em v-else-if="inHand?.count">
            {{ inHand.count }} receipt{{ inHand.count === 1 ? '' : 's' }} to hand in
          </em>
          <em v-else>Nothing to hand in right now</em>
        </span>
        <Icon name="chevron" size="18" class="go" />
      </RouterLink>

      <!-- Below the satchel, because handing money in is the commoner errand. -->
      <button v-if="!taking" class="take" @click="openTake">
        <Icon name="tag" size="20" />
        <span>
          <b>Take from a depot</b>
          <em>Money collected from a distributor, not a shop</em>
        </span>
      </button>

      <div v-else class="form">
        <div class="frow">
          <h2>Take from a depot</h2>
          <button class="quiet" @click="closeTake" aria-label="Close">
            <Icon name="close" size="20" />
          </button>
        </div>

        <label>
          <span class="lbl">Which depot</span>
          <select v-model="form.distributor" :disabled="saving">
            <option value="">Choose one</option>
            <option v-for="d in depots" :key="d.distributor" :value="d.distributor">
              {{ d.distributor_name }}
            </option>
          </select>
        </label>

        <label>
          <span class="lbl">How much</span>
          <input v-model="form.amount" type="number" inputmode="decimal" min="0"
                 :disabled="saving" placeholder="0" />
        </label>

        <label>
          <span class="lbl">How it was paid</span>
          <select v-model="form.mode" :disabled="saving">
            <option v-for="m in MODES" :key="m" :value="m">{{ m }}</option>
          </select>
        </label>

        <!-- Anything but cash leaves a number on a slip, and a claim with no number on it is
             the first thing anybody disputes. -->
        <label v-if="needsReference">
          <span class="lbl">{{ form.mode }} number</span>
          <input v-model="form.reference" type="text" :disabled="saving"
                 placeholder="Cheque / UPI reference" />
        </label>

        <label>
          <span class="lbl">Who handed it over <em class="opt">(optional)</em></span>
          <input v-model="form.from" type="text" :disabled="saving" placeholder="Name" />
        </label>

        <p v-if="saveError" class="note crit">{{ saveError }}</p>

        <p class="dim fine">
          This money is ours. It reaches the books when somebody at the office confirms your
          deposit — not now.
        </p>

        <button class="btn-primary" :disabled="!canSave || saving" @click="takeFromDepot">
          {{ saving ? 'Saving…' : 'Record it' }}
        </button>
      </div>

      <template v-if="collections.length">
        <div class="section"><h2>Recent receipts</h2></div>
        <div v-for="c in collections" :key="c.name" class="row">
          <div class="left">
            <b>{{ c.party_name || c.outlet || c.distributor || c.party }}</b>
            <span class="dim">{{ day(c.collection_date) }} · {{ c.mode }}
              <template v-if="c.receipt_no"> · {{ c.receipt_no }}</template>
            </span>
          </div>
          <div class="right">
            <b class="tnum">{{ formatRupees(c.amount) }}</b>
            <span class="pill" :class="TONE[c.status] || 'flat'">{{ c.status }}</span>
          </div>
        </div>
      </template>

      <p v-else-if="listError" class="note crit">{{ listError }}</p>

      <div v-else class="empty">
        <Icon name="tag" size="34" />
        <b>No collections yet</b>
        <p class="dim">Take one at a shop and it will show up here.</p>
      </div>

      <p class="dim fine">
        Money taken at a shop belongs to that shop's distributor. You are carrying it, not
        earning it — hand it in and it is off your name.
      </p>
    </template>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.head h1 { font-size: 20px; margin: 0; }
.dim { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.fine { font-size: 12px; }
.quiet { border: 0; background: none; color: var(--muted); min-height: 44px; padding: 0 6px; }

.hand { display: flex; align-items: center; gap: 10px; text-decoration: none;
        background: var(--ok-soft); color: var(--ok); border-radius: 10px; padding: 14px;
        min-height: 64px; }
.hand.late { background: var(--warn-soft); color: var(--warn); }
.hand .body { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.hand em { font-style: normal; font-size: 13px; color: var(--muted); }
.go { flex: none; }

.section h2 { font-size: 15px; margin: 4px 0 0; }

.take { display: flex; align-items: center; gap: 10px; text-align: left; min-height: 64px;
        padding: 12px 14px; background: var(--surface); border: 1px solid var(--line);
        border-radius: 10px; color: var(--ink); }
.take > span { display: grid; gap: 2px; }
.take em { font-style: normal; font-size: 13px; color: var(--muted); }

.form { display: flex; flex-direction: column; gap: 10px; background: var(--surface);
        border: 1px solid var(--line); border-radius: 10px; padding: 14px; }
.frow { display: flex; align-items: center; justify-content: space-between; }
.frow h2 { font-size: 16px; margin: 0; }
.form label { display: grid; gap: 4px; }
.lbl { font-size: 13px; font-weight: 600; color: var(--muted); }
.lbl .opt { font-style: normal; font-weight: 400; }
.form select { min-height: 48px; padding: 0 12px; border: 1px solid var(--line);
               border-radius: 6px; background: var(--surface); color: var(--ink);
               font: inherit; width: 100%; }
.fine { font-size: 12px; margin: 0; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 10px;
       background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
       padding: 12px; }
.left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
.pill { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.crit { background: var(--crit-soft); color: var(--crit); }
.pill.calm, .pill.flat { background: var(--primary-soft); color: var(--primary); }
.note { color: var(--muted); font-size: 14px; text-align: center; padding: 20px 0; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.empty { text-align: center; padding: 32px 16px; color: var(--muted); display: flex;
         flex-direction: column; gap: 6px; align-items: center; }
.empty b { color: var(--ink); }
.empty p { margin: 0; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
