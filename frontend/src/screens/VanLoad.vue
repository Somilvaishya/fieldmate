<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid } from '../db'
import { formatRupees } from '../lib/money'
import * as dayStore from '../stores/day'
import Icon from '../components/Icon.vue'

const router = useRouter()

const sheet = ref(null)
const rows = ref([])
const note = ref('')
const editing = ref(null)
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const saved = ref(false)

const differing = computed(() => rows.value.filter((r) => r.counted_qty !== r.godown_qty))
const totals = computed(() => ({
  skus: rows.value.filter((r) => r.counted_qty > 0).length,
  qty: rows.value.reduce((t, r) => t + (Number(r.counted_qty) || 0), 0),
  value: rows.value.reduce((t, r) => t + (Number(r.counted_qty) || 0) * (Number(r.rate) || 0), 0),
}))

onMounted(async () => {
  try {
    const data = await api.vanLoad()
    sheet.value = data
    rows.value = (data.items || []).map((item) => ({
      ...item,
      // What the godown says, until he says otherwise. Both survive to the server: a load sheet
      // nobody can disagree with is a load sheet nobody checks.
      counted_qty: item.counted_qty ?? item.godown_qty,
      rate: item.amount && item.counted_qty ? item.amount / item.counted_qty : 0,
    }))
    note.value = data.variance_note || ''
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not load the van sheet.'
  } finally {
    loading.value = false
  }
})

function recount(row, value) {
  const n = Number(String(value ?? '').trim())
  if (Number.isNaN(n) || n < 0) return
  row.counted_qty = n
}

function display(row, qty) {
  const factor = row.conversion_factor || 1
  const cases = factor > 1 ? Math.floor(qty / factor) : qty
  return factor > 1 ? `${cases} cases` : `${qty}`
}

async function confirm() {
  error.value = ''
  busy.value = true
  try {
    saved.value = await api.vanLoadSave({
      load_date: sheet.value.load_date,
      distributor: sheet.value.distributor,
      vehicle_no: sheet.value.vehicle_no,
      day_start: dayStore.openDay.value?.day_start || null,
      variance_note: note.value || null,
      client_uuid: crypto.randomUUID(),
      device_id: await deviceUuid(),
      items: rows.value.map((row) => ({
        item_code: row.item_code,
        godown_qty: row.godown_qty,
        counted_qty: row.counted_qty,
        display_uom: row.display_uom,
        conversion_factor: row.conversion_factor || 1,
      })),
    })
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not confirm the load.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="saved" class="wrap screen">
    <div class="top">
      <div class="card ok-card">
        <p class="badge"><Icon name="check" size="22" /><span>Load confirmed</span></p>
        <b class="big tnum">{{ saved.total_skus }} SKUs · {{ formatRupees(saved.stock_value) }}</b>
        <p class="muted">This is your opening stock for the day.</p>
      </div>
    </div>
    <div class="bottom">
      <button class="btn-primary" @click="router.replace('/today')">Start my route</button>
    </div>
  </div>

  <div v-else class="wrap screen">

    <div v-if="loading" class="muted pad">Loading today's van sheet…</div>

    <div v-else-if="!rows.length" class="card pad">
      <p><Icon name="alert" size="18" /> No load sheet for today.</p>
      <p class="muted">Ask the godown to prepare one, or load the van yourself and ask them to
        enter it.</p>
    </div>

    <template v-else>
      <div class="card ctx">
        <p class="label">Distributor godown</p>
        <h1>{{ sheet.distributor_name || sheet.distributor }}</h1>
        <div class="meta tnum">
          <span><Icon name="calendar" size="16" /> {{ sheet.load_date }}</span>
          <span v-if="sheet.vehicle_no"><Icon name="truck" size="16" /> {{ sheet.vehicle_no }}</span>
        </div>
      </div>

      <div class="card tiles tnum">
        <div><span class="label">SKUs</span><b>{{ totals.skus }}</b></div>
        <div><span class="label">Units</span><b>{{ totals.qty }}</b></div>
        <div><span class="label">Stock value</span><b>{{ formatRupees(totals.value) }}</b></div>
      </div>

      <!-- Only when something actually differs. A note field standing there every morning gets
           filled with "ok" and stops meaning anything. -->
      <div v-if="differing.length" class="card warn-card">
        <p class="wtitle">
          <Icon name="alert" size="20" />
          <span>You counted {{ differing.length }} product{{ differing.length > 1 ? 's' : '' }}
            differently from the sheet.</span>
        </p>
        <ul class="diffs tnum">
          <li v-for="row in differing" :key="row.item_code">
            <span>{{ row.item_name }}</span>
            <span class="muted">godown said {{ row.godown_qty }}, you counted {{ row.counted_qty }}</span>
          </li>
        </ul>
        <label class="lbl" for="vnote">Why is your count different?</label>
        <textarea id="vnote" v-model="note" rows="2"
                  placeholder="e.g. 2 cases torn at the loading bay" />
        <p class="muted small">Needed before you can confirm. Nobody will remember this evening.</p>
      </div>

      <h2 class="shead">Products loaded</h2>

      <article v-for="row in rows" :key="row.item_code"
               class="row" :class="{ adjusted: row.counted_qty !== row.godown_qty }">
        <div class="rtop">
          <div>
            <span class="code">{{ row.item_code }}</span>
            <h3>{{ row.item_name }}</h3>
          </div>
          <button type="button" class="pencil"
                  :aria-label="'Recount ' + row.item_name"
                  @click="editing = editing === row.item_code ? null : row.item_code">
            <Icon name="edit" size="18" />
          </button>
        </div>

        <div v-if="editing === row.item_code" class="entry">
          <input class="qty tnum" type="number" inputmode="numeric" min="0"
                 :value="row.counted_qty" @input="recount(row, $event.target.value)" />
          <span class="muted">{{ row.display_uom }}</span>
        </div>

        <div class="rfoot tnum">
          <b>{{ display(row, row.counted_qty) }}
            <span class="muted">= {{ row.counted_qty }} pieces</span></b>
          <span v-if="row.counted_qty !== row.godown_qty" class="chip warn">Adjusted</span>
          <span v-else class="chip ok">Matches sheet</span>
        </div>
        <p v-if="row.counted_qty !== row.godown_qty" class="muted small tnum">
          Godown said {{ row.godown_qty }}, you counted {{ row.counted_qty }}
        </p>
      </article>

      <p class="muted note">
        <Icon name="info" size="16" />
        <span>This stock is the distributor's. Whatever is unsold comes back to their godown
          tonight.</span>
      </p>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>

      <div class="bottom">
        <p class="muted note">This becomes your opening stock for the day.</p>
        <button class="btn-primary" :disabled="busy" @click="confirm">
          {{ busy ? 'Confirming…' : 'Confirm load' }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.pad { padding: 16px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; margin-bottom: 12px; }
.label { margin: 0; font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em;
         color: var(--muted); }
.ctx h1 { margin: 2px 0 8px; font-size: 19px; }
.meta { display: flex; gap: 16px; font-size: 14px; color: var(--muted); }
.meta span { display: flex; align-items: center; gap: 5px; }

.tiles { display: flex; }
.tiles div { flex: 1; text-align: center; }
.tiles div + div { border-left: 1px solid var(--line); }
.tiles b { display: block; font-size: 18px; margin-top: 3px; }

.warn-card { background: var(--warn-soft); border-color: var(--warn); }
.wtitle { display: flex; align-items: flex-start; gap: 8px; margin: 0 0 10px;
          color: var(--warn); font-weight: 600; }
.diffs { list-style: none; margin: 0 0 12px; padding: 0; font-size: 14px; }
.diffs li { display: flex; flex-direction: column; padding: 7px 0;
            border-top: 1px solid rgba(149, 95, 7, 0.25); }
.lbl { display: block; font-weight: 600; margin-bottom: 5px; color: var(--warn); }
textarea { width: 100%; font: inherit; padding: 9px 11px; border: 1px solid var(--warn);
           border-radius: 6px; background: var(--surface); color: var(--ink); }
.small { font-size: 13px; }

.shead { margin: 18px 0 8px; font-size: 14px; text-transform: uppercase;
         letter-spacing: 0.04em; color: var(--muted); }
.row { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--line);
       border-radius: 6px; padding: 12px; margin-bottom: 10px; }
.row.adjusted { border-left-color: var(--warn); }
.rtop { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; }
.code { font-size: 13px; font-weight: 600; background: var(--primary-soft); color: var(--primary);
        padding: 1px 6px; border-radius: 4px; }
.row h3 { margin: 4px 0 0; font-size: 16px; }
.pencil { width: 48px; height: 48px; min-height: 48px; display: grid; place-items: center;
          background: var(--surface); border: 1px solid var(--line); color: var(--ink); }

.entry { display: flex; align-items: center; gap: 10px; margin-top: 10px; }
.qty { flex: 1; font-size: 20px; font-weight: 700; }

.rfoot { display: flex; align-items: center; justify-content: space-between; gap: 8px;
         margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--line); }
.chip { font-size: 13px; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
.chip.ok { background: var(--ok-soft); color: var(--ok); }
.chip.warn { background: var(--warn-soft); color: var(--warn); }

.bottom { padding-top: 18px; }
.note { display: flex; align-items: center; justify-content: center; gap: 6px;
        margin: 0 0 8px; font-size: 14px; }
.err { display: flex; align-items: center; gap: 8px; margin: 14px 0 0;
       background: var(--crit-soft); color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.ok-card { background: var(--ok-soft); border-color: var(--ok); text-align: center; }
.badge { display: flex; align-items: center; justify-content: center; gap: 8px;
         margin: 0; color: var(--ok); font-weight: 600; }
.big { display: block; font-size: 20px; margin: 8px 0 4px; }
.top { flex: 1; display: flex; flex-direction: column; justify-content: center; }
</style>
