<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid } from '../db'
import { formatRupees } from '../lib/money'
import * as dayStore from '../stores/day'
import Icon from '../components/Icon.vue'

const router = useRouter()

const state = ref(null)
const rows = ref([])
const note = ref('')
const deposited = ref(0)
const showDetail = ref(true)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const saved = ref(false)

// Recomputed on the phone as he types, so the figure moves under his thumb. The server works it
// out again from the same three numbers and is the one that counts.
const totals = computed(() => {
  const loaded = rows.value.reduce((t, r) => t + (Number(r.loaded_qty) || 0), 0)
  const sold = rows.value.reduce((t, r) => t + (Number(r.sold_qty) || 0), 0)
  const returned = rows.value.reduce((t, r) => t + returnedOf(r), 0)
  return { loaded, sold, returned, short: loaded - sold - returned }
})

const shortRows = computed(() =>
  rows.value
    .map((r) => ({ ...r, short: r.loaded_qty - r.sold_qty - returnedOf(r) }))
    .filter((r) => Math.abs(r.short) > 0.0001)
)

const cashToHandOver = computed(
  () => (state.value?.cash_collected || 0) - (Number(deposited.value) || 0)
)

const ready = computed(() => Math.abs(totals.value.short) < 0.0001 || note.value.trim().length > 0)

function returnedOf(row) {
  return (Number(row.returned_good) || 0) + (Number(row.returned_damaged) || 0)
}

onMounted(async () => {
  try {
    const data = await api.vanSettlement()
    state.value = data
    rows.value = (data.items || []).map((item) => ({
      ...item,
      returned_good: item.returned_good || null,
      returned_damaged: item.returned_damaged || null,
    }))
    note.value = data.shortfall_note || ''
    deposited.value = data.cash_deposited || 0
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not load tonight’s figures.'
  } finally {
    loading.value = false
  }
})

function setNum(row, field, value) {
  const text = String(value ?? '').trim()
  row[field] = text === '' ? null : Math.max(0, Number(text) || 0)
}

async function settle() {
  error.value = ''
  busy.value = true
  try {
    saved.value = await api.vanSettlementSave({
      van_load: state.value.van_load,
      day_start: dayStore.openDay.value?.day_start || null,
      cash_deposited: Number(deposited.value) || 0,
      shortfall_note: note.value || null,
      client_uuid: crypto.randomUUID(),
      device_id: await deviceUuid(),
      items: rows.value.map((row) => ({
        item_code: row.item_code,
        returned_good: Number(row.returned_good) || 0,
        returned_damaged: Number(row.returned_damaged) || 0,
      })),
    })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not settle the day.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="saved" class="wrap screen">
    <div class="top">
      <div class="card ok-card">
        <p class="badge"><Icon name="check" size="22" /><span>Day settled</span></p>
        <!-- Kept on screen rather than flashed as a toast. He may be asked about these numbers
             tomorrow morning. -->
        <dl class="recap tnum">
          <div><dt>Sold</dt><dd>{{ saved.sold_qty }}</dd></div>
          <div><dt>Returned</dt><dd>{{ saved.returned_qty }}</dd></div>
          <div><dt>Short</dt><dd :class="saved.short_qty ? 'crit' : ''">{{ saved.short_qty }}</dd></div>
          <div><dt>Handed over</dt><dd>{{ formatRupees(saved.cash_to_hand_over) }}</dd></div>
        </dl>
      </div>
    </div>
    <div class="bottom">
      <button class="btn-primary" @click="router.replace('/today')">Done</button>
    </div>
  </div>

  <div v-else class="wrap screen">

    <div v-if="loading" class="muted pad">Working out tonight's figures…</div>

    <div v-else-if="!state?.van_load" class="card pad">
      <p><Icon name="alert" size="18" /> Nothing was loaded on this vehicle today.</p>
      <p class="muted">There is nothing to settle.</p>
    </div>

    <template v-else>
      <div class="head">
        <h1>Settle day</h1>
        <p class="muted tnum">{{ state.vehicle_no }} · {{ state.settlement_date }}</p>
      </div>

      <!-- Laid out as the equation it is. Four separate tiles make a rep work out which number
           is wrong; a column of four lines and a rule does it for him. -->
      <div class="card eq tnum">
        <p class="label">Van stock</p>
        <div class="eline"><span>Loaded</span><b>{{ totals.loaded }}</b></div>
        <div class="eline">
          <span><i>−</i> Sold <em class="muted">from his orders</em></span><b>{{ totals.sold }}</b>
        </div>
        <div class="eline"><span><i>−</i> Returned</span><b>{{ totals.returned }}</b></div>
        <div class="rule"></div>
        <div class="eline result" :class="totals.short ? 'bad' : 'good'">
          <span><Icon :name="totals.short ? 'alert' : 'check'" size="18" />
            {{ totals.short ? 'Short' : 'All accounted for' }}</span>
          <b>{{ totals.short }}</b>
        </div>

        <div v-if="totals.short" class="shortbox">
          <label class="lbl" for="snote">What happened to the {{ totals.short }}?</label>
          <textarea id="snote" v-model="note" rows="3"
                    placeholder="e.g. 2 cases crushed in the rain on MG Road" />
          <p class="small">Needed before the day can be settled.</p>
        </div>
      </div>

      <div v-if="shortRows.length" class="card">
        <button type="button" class="disc" @click="showDetail = !showDetail">
          <span>Where the difference is</span>
          <Icon :name="showDetail ? 'chevron-up' : 'chevron'" size="18" />
        </button>
        <ul v-if="showDetail" class="detail tnum">
          <li v-for="row in shortRows" :key="row.item_code">
            <b>{{ row.item_name }}</b>
            <span class="crit">short {{ row.short }}</span>
            <span class="muted">loaded {{ row.loaded_qty }} · sold {{ row.sold_qty }} ·
              returned {{ returnedOf(row) }}</span>
          </li>
        </ul>
      </div>

      <h2 class="shead">What came back</h2>
      <article v-for="row in rows" :key="row.item_code" class="row">
        <h3>{{ row.item_name }}</h3>
        <p class="muted small tnum">Loaded {{ row.loaded_qty }} · sold {{ row.sold_qty }}</p>
        <div class="returns">
          <label>
            <span class="muted">Good</span>
            <input class="tnum" type="number" inputmode="numeric" min="0"
                   :value="row.returned_good" placeholder="0"
                   @input="setNum(row, 'returned_good', $event.target.value)" />
          </label>
          <label>
            <!-- Damaged stock coming back is a real cost and vanishes if nobody asks. -->
            <span class="muted">Damaged</span>
            <input class="tnum" type="number" inputmode="numeric" min="0"
                   :value="row.returned_damaged" placeholder="0"
                   @input="setNum(row, 'returned_damaged', $event.target.value)" />
          </label>
        </div>
      </article>

      <div class="card">
        <p class="label">Cash</p>
        <div class="cline tnum"><span>Collected today</span><b>{{ formatRupees(state.cash_collected) }}</b></div>
        <label class="cline tnum">
          <span>Already deposited</span>
          <input class="cash tnum" type="number" inputmode="decimal" min="0" v-model="deposited" />
        </label>
        <div class="cline total tnum"><span>To hand over</span><b>{{ formatRupees(cashToHandOver) }}</b></div>
        <p class="muted small">
          <Icon name="person" size="15" />
          Hand over to {{ state.distributor }}. The stock was theirs, and so is the money.
        </p>
      </div>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>

      <div class="bottom">
        <p class="muted note">Once settled, today's stock and cash are locked.</p>
        <button class="btn-primary" :disabled="busy || !ready" @click="settle">
          {{ busy ? 'Settling…' : 'Settle day' }}
        </button>
        <button class="btn-plain" @click="router.back()">Save and finish later</button>
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
.label { margin: 0 0 8px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em;
         color: var(--muted); }

.eline { display: flex; justify-content: space-between; align-items: baseline; padding: 7px 0; }
.eline i { font-style: normal; color: var(--muted); margin-right: 4px; }
.eline em { font-style: normal; font-size: 13px; margin-left: 6px; }
.eline b { font-size: 18px; }
.rule { border-top: 2px dashed var(--line); margin: 6px 0; }
.result { padding: 10px 12px; border-radius: 6px; margin-top: 4px; }
.result span { display: flex; align-items: center; gap: 7px; font-weight: 600; }
.result.good { background: var(--ok-soft); color: var(--ok); }
.result.bad { background: var(--crit-soft); color: var(--crit); }
.result.bad b { font-size: 24px; }

.shortbox { margin-top: 14px; }
.lbl { display: block; font-weight: 600; margin-bottom: 6px; color: var(--crit); }
textarea { width: 100%; font: inherit; padding: 9px 11px; border: 1px solid var(--crit);
           border-radius: 6px; background: var(--surface); color: var(--ink); }
.small { font-size: 13px; margin: 5px 0 0; }
.shortbox .small { color: var(--crit); }

.disc { display: flex; width: 100%; align-items: center; justify-content: space-between;
        background: none; border: 0; padding: 0; font-weight: 600; color: var(--ink); }
.detail { list-style: none; margin: 12px 0 0; padding: 0; }
.detail li { display: flex; flex-direction: column; gap: 2px; padding: 9px 0;
             border-top: 1px solid var(--line); font-size: 14px; }
.crit { color: var(--crit); font-weight: 600; }

.shead { margin: 18px 0 8px; font-size: 14px; text-transform: uppercase;
         letter-spacing: 0.04em; color: var(--muted); }
.row { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
       padding: 12px; margin-bottom: 10px; }
.row h3 { margin: 0; font-size: 16px; }
.returns { display: flex; gap: 10px; margin-top: 10px; }
.returns label { flex: 1; display: grid; gap: 4px; font-size: 14px; }

.cline { display: flex; justify-content: space-between; align-items: center; padding: 7px 0; }
.cline + .cline { border-top: 1px solid var(--line); }
.cline.total { background: var(--primary-soft); color: var(--primary); border-radius: 6px;
               padding: 10px 12px; margin-top: 6px; font-weight: 600; }
.cline.total b { font-size: 20px; }
.cash { width: 130px; text-align: right; }

.bottom { padding-top: 18px; }
.note { text-align: center; font-size: 14px; margin: 0 0 8px; }
.err { display: flex; align-items: center; gap: 8px; margin: 14px 0 0;
       background: var(--crit-soft); color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.ok-card { background: var(--ok-soft); border-color: var(--ok); text-align: center; }
.badge { display: flex; align-items: center; justify-content: center; gap: 8px;
         margin: 0 0 12px; color: var(--ok); font-weight: 600; }
.recap { display: grid; gap: 6px; text-align: left; }
.recap div { display: flex; justify-content: space-between; }
.recap dt, .recap dd { margin: 0; }
.recap dd { font-weight: 700; }
.top { flex: 1; display: flex; flex-direction: column; justify-content: center; }
</style>
