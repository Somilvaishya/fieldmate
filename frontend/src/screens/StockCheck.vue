<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid } from '../db'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()

const sheet = ref(null)
const rows = ref([])
const search = ref('')
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const saved = ref(false)

// He is counting boxes on a shelf while the shopkeeper watches, so the list has to be findable
// rather than scrollable. Grouping matches the catalogue he already knows.
const groups = computed(() => {
  const term = search.value.trim().toLowerCase()
  const matched = rows.value.filter(
    (r) => !term || r.item_code.toLowerCase().includes(term) || (r.item_name || '').toLowerCase().includes(term)
  )
  const byGroup = new Map()
  for (const row of matched) {
    const key = row.item_group || 'Other'
    if (!byGroup.has(key)) byGroup.set(key, [])
    byGroup.get(key).push(row)
  }
  return [...byGroup.entries()].map(([name, items]) => ({
    name,
    items,
    counted: items.filter((r) => r.is_counted).length,
  }))
})

const counted = computed(() => rows.value.filter((r) => r.is_counted).length)
const missing = computed(() => rows.value.length - counted.value)
const pct = computed(() => (rows.value.length ? Math.round((counted.value / rows.value.length) * 100) : 0))

onMounted(async () => {
  try {
    const data = await api.stockSheet(route.params.outlet)
    sheet.value = data
    rows.value = (data.items || []).map((item) => ({
      ...item,
      // Display units, because that is what he types. The server converts.
      qty_display: null,
      // Sent explicitly rather than inferred from the number. A shelf counted at zero and a
      // shelf nobody looked at are opposite facts, and a blank number cannot tell them apart.
      is_counted: false,
      unit: 'display',
    }))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not load the product list.'
  } finally {
    loading.value = false
  }
})

function setQty(row, value) {
  const text = String(value ?? '').trim()
  if (text === '') {
    row.qty_display = null
    row.is_counted = false
    return
  }
  const n = Number(text)
  if (Number.isNaN(n) || n < 0) return
  row.qty_display = n
  row.is_counted = true
}

function sameAsLast(row) {
  if (!row.has_history) return
  row.qty_display = row.last_display_qty ?? row.last_qty ?? 0
  row.unit = row.last_uom === row.order_uom ? 'display' : row.unit
  row.is_counted = true
}

function factorFor(row) {
  return row.unit === 'base' ? 1 : (row.conversion_factor || 1)
}

function uomFor(row) {
  return row.unit === 'base' ? row.stock_uom : (row.order_uom || row.stock_uom)
}

async function save() {
  error.value = ''
  busy.value = true
  try {
    const open = visitStore.activeVisit.value
    const result = await api.stockSave({
      outlet: sheet.value.outlet,
      visit: open?.serverName || open?.clientUuid || null,
      client_uuid: crypto.randomUUID(),
      device_id: await deviceUuid(),
      items: rows.value.map((row) => ({
        item_code: row.item_code,
        qty_display: row.qty_display ?? 0,
        display_uom: uomFor(row),
        conversion_factor: factorFor(row),
        is_counted: row.is_counted ? 1 : 0,
      })),
    })
    saved.value = result
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not save the count.'
  } finally {
    busy.value = false
  }
}

function done() {
  const open = visitStore.activeVisit.value
  router.replace(open ? { name: 'visit', params: { uuid: open.clientUuid } } : '/today')
}
</script>

<template>
  <div v-if="saved" class="wrap screen">
    <div class="top">
      <div class="card ok-card">
        <p class="badge"><Icon name="check" size="22" /><span>Stock saved</span></p>
        <b class="big tnum">{{ saved.counted_lines }} of {{ saved.total_lines }} counted</b>
        <p v-if="saved.is_partial" class="muted">
          Saved with {{ saved.total_lines - saved.counted_lines }} products not counted. That is
          fine — a partial count is worth more than none.
        </p>
        <p v-else class="muted">Every product on the list was counted.</p>
      </div>
    </div>
    <div class="bottom">
      <button class="btn-primary" @click="done">Done</button>
    </div>
  </div>

  <div v-else class="wrap screen">

    <div v-if="loading" class="muted pad">Loading the product list…</div>

    <div v-else-if="!rows.length" class="card pad">
      <p><Icon name="alert" size="18" /> No products listed for this shop yet.</p>
      <p class="muted">Ask your manager to set up the catalogue for it.</p>
    </div>

    <template v-else>
      <div class="head">
        <h1>{{ sheet.outlet_name }}</h1>
        <p class="muted tnum">
          <Icon name="clock" size="16" />
          <span v-if="sheet.days_since != null">Last counted {{ sheet.days_since }} days ago</span>
          <span v-else>First stock check here</span>
        </p>
      </div>

      <!-- Pinned, because it is the only thing telling him how much is left while he scrolls. -->
      <div class="progress">
        <div class="pline tnum">
          <b>{{ counted }} of {{ rows.length }} products counted</b>
          <span :class="pct === 100 ? 'ok' : 'muted'">{{ pct }}%</span>
        </div>
        <div class="track"><span class="fill" :style="{ width: pct + '%' }"></span></div>
        <input v-model="search" class="find" placeholder="Search SKU code or name" />
      </div>

      <section v-for="group in groups" :key="group.name" class="group">
        <h2 class="ghead">
          <span>{{ group.name }}</span>
          <span class="muted tnum">{{ group.counted }} of {{ group.items.length }}</span>
        </h2>

        <article v-for="row in group.items" :key="row.item_code"
                 class="row" :class="{ done: row.is_counted }">
          <div class="rtop">
            <span class="code">{{ row.item_code }}</span>
            <span class="muted tnum">{{ row.conversion_factor }} per case</span>
            <span v-if="row.is_counted && !row.qty_display" class="chip crit">Out of stock</span>
            <span v-if="row.is_must_sell" class="chip">Must sell</span>
          </div>
          <h3>{{ row.item_name }}</h3>

          <div class="entry">
            <!-- A keypad, not a stepper. He is typing 14, not tapping plus fourteen times. -->
            <input
              class="qty tnum"
              type="number"
              inputmode="numeric"
              min="0"
              :value="row.qty_display"
              :placeholder="'Enter count'"
              @input="setQty(row, $event.target.value)"
            />
            <div class="units" role="group" :aria-label="'Unit for ' + row.item_name">
              <button type="button" :class="{ on: row.unit === 'display' }"
                      @click="row.unit = 'display'">Cases</button>
              <button type="button" :class="{ on: row.unit === 'base' }"
                      @click="row.unit = 'base'">Pcs</button>
            </div>
          </div>

          <div class="rfoot">
            <span class="muted tnum">
              <template v-if="row.has_history">Last visit: {{ row.last_display_qty ?? row.last_qty }} {{ row.last_uom }}</template>
              <template v-else>Never counted here</template>
            </span>
            <button v-if="row.has_history" type="button" class="again" @click="sameAsLast(row)">
              <Icon name="copy" size="16" /><span>Same as last time</span>
            </button>
          </div>
        </article>
      </section>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>

      <div class="bottom">
        <p v-if="missing" class="note warn-note tnum">
          <Icon name="alert" size="16" />
          <span>{{ missing }} products not counted — save anyway?</span>
        </p>
        <p class="muted note"><Icon name="cloud-off" size="16" /> Saved on this phone. Syncs when you have signal.</p>
        <button class="btn-primary" :disabled="busy || !counted" @click="save">
          {{ busy ? 'Saving…' : 'Save stock' }}
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.pad { padding: 16px; }
.head { padding: 4px 0 10px; }
h1 { margin: 0; font-size: 20px; }
.head .muted { display: flex; align-items: center; gap: 6px; margin: 4px 0 0; font-size: 14px; }

.progress { position: sticky; top: 0; z-index: 2; background: var(--bg);
            padding: 10px 0; border-bottom: 1px solid var(--line); }
.pline { display: flex; justify-content: space-between; font-size: 15px; }
.pline .ok { color: var(--ok); font-weight: 600; }
.track { height: 6px; background: var(--line); border-radius: 3px; margin: 6px 0 10px; overflow: hidden; }
.fill { display: block; height: 100%; background: var(--ok); }
.find { margin: 0; }

.group { margin-top: 18px; }
.ghead { display: flex; justify-content: space-between; align-items: baseline;
         margin: 0 0 8px; font-size: 14px; text-transform: uppercase;
         letter-spacing: 0.04em; color: var(--muted); }

.row { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--line);
       border-radius: 6px; padding: 12px; margin-bottom: 10px; }
.row.done { border-left-color: var(--ok); }
.rtop { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 14px; }
.code { font-weight: 600; background: var(--primary-soft); color: var(--primary);
        padding: 1px 6px; border-radius: 4px; }
.row h3 { margin: 4px 0 10px; font-size: 16px; }

.entry { display: flex; gap: 8px; }
.qty { flex: 1; font-size: 20px; font-weight: 700; }
.units { display: flex; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.units button { min-width: 62px; min-height: 48px; border: 0; background: var(--surface);
                color: var(--muted); font-weight: 600; border-radius: 0; }
.units button.on { background: var(--primary); color: var(--on-primary); }

.rfoot { display: flex; align-items: center; justify-content: space-between; gap: 8px;
         margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--line); font-size: 14px; }
.again { display: flex; align-items: center; gap: 6px; min-height: 48px; padding: 0 10px;
         background: var(--primary-soft); color: var(--primary); border: 0;
         font-size: 14px; font-weight: 600; }

.chip { font-size: 13px; font-weight: 600; padding: 1px 7px; border-radius: 4px;
        background: var(--primary-soft); color: var(--primary); }
.chip.crit { background: var(--crit-soft); color: var(--crit); }

.bottom { padding-top: 18px; }
.note { display: flex; align-items: center; justify-content: center; gap: 6px;
        margin: 0 0 8px; font-size: 14px; }
.warn-note { background: var(--warn-soft); color: var(--warn); border-radius: 6px; padding: 9px 12px; }
.err { display: flex; align-items: center; gap: 8px; margin: 14px 0 0;
       background: var(--crit-soft); color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.ok-card { background: var(--ok-soft); border-color: var(--ok); text-align: center; }
.badge { display: flex; align-items: center; justify-content: center; gap: 8px;
         margin: 0; color: var(--ok); font-weight: 600; }
.big { display: block; font-size: 22px; margin: 8px 0 4px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 16px; }
.top { flex: 1; display: flex; flex-direction: column; justify-content: center; }
</style>
