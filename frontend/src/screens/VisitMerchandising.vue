<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { db } from '../db'
import { enqueue } from '../sync/outbox'
import * as visitStore from '../stores/visit'

const router = useRouter()
const visit = visitStore.activeVisit
const lines = ref([])
const competitors = ref([])
const shelfTotal = ref('')
const busy = ref(false)
const saved = ref(false)

const ourFacings = computed(() =>
  lines.value.reduce((sum, l) => sum + (Number(l.facings) || 0), 0))
const theirFacings = computed(() =>
  competitors.value.reduce((sum, c) => sum + (Number(c.facings) || 0), 0))

// Shown so the rep can sanity-check it on the spot; the server computes the figure that is
// actually recorded, from the same rows.
const share = computed(() => {
  const total = Math.max(Number(shelfTotal.value) || 0, ourFacings.value + theirFacings.value)
  return total ? Math.round((ourFacings.value / total) * 1000) / 10 : 0
})

onMounted(async () => {
  if (!visit.value) await visitStore.resume()
  if (!visit.value) return router.replace('/today')

  const draft = await db.meta.get('merch:' + visit.value.clientUuid)
  if (draft?.value) {
    lines.value = draft.value.lines || []
    competitors.value = draft.value.competitors || []
    shelfTotal.value = draft.value.shelfTotal || ''
    return
  }
  // Seed with the catalogue this phone already holds, so the rep ticks rather than types.
  const items = await db.records.where('doctype').equals('FieldMate Catalogue Item').toArray()
  lines.value = items.slice(0, 60).map((i) => ({
    item_code: i.item_code || i.name,
    item_name: i.item_name || i.item_code || i.name,
    is_available: 0,
    facings: 0,
    shelf_position: '',
  }))
})

function addCompetitor() {
  competitors.value.push({ competitor: '', product: '', mrp: null, selling_price: null,
                           facings: 0, has_scheme: 0, scheme_note: '' })
}

function removeCompetitor(index) {
  competitors.value.splice(index, 1)
}

async function keep() {
  await db.meta.put({
    key: 'merch:' + visit.value.clientUuid,
    value: JSON.parse(JSON.stringify({
      lines: lines.value, competitors: competitors.value, shelfTotal: shelfTotal.value,
    })),
  })
}

async function save() {
  busy.value = true
  try {
    await keep()
    await enqueue('FieldMate Merchandising Audit', {
      docstatus: 1,
      outlet: visit.value.outlet,
      audit_date: visit.value.visitDate,
      total_facings: Number(shelfTotal.value) || 0,
      created_offline: 1,
      lines: lines.value
        .filter((l) => l.is_available || Number(l.facings) > 0)
        .map((l) => ({
          item_code: l.item_code,
          is_available: l.is_available ? 1 : 0,
          facings: Number(l.facings) || 0,
          shelf_position: l.shelf_position || null,
        })),
      competitors: competitors.value
        .filter((c) => c.competitor && c.product)
        .map((c) => ({
          competitor: c.competitor,
          product: c.product,
          mrp: c.mrp || null,
          selling_price: c.selling_price || null,
          facings: Number(c.facings) || 0,
          has_scheme: c.has_scheme ? 1 : 0,
          scheme_note: c.scheme_note || null,
        })),
    }, { dependsOn: visit.value.clientUuid })

    const row = visit.value.tasks.find((t) => t.task_type === 'Merchandising')
    if (row) row.status = 'Done'
    await visitStore.saveProgress()
    saved.value = true
    router.back()
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap screen" v-if="visit">
    <h2>Shelf check</h2>
    <p class="muted">{{ visit.outletName }}</p>

    <p class="tally tnum">
      Ours <b>{{ ourFacings }}</b> · Theirs <b>{{ theirFacings }}</b> · Share <b>{{ share }}%</b>
    </p>

    <label class="lbl" for="total">Facings on the whole shelf <span class="muted">(optional)</span></label>
    <input id="total" v-model="shelfTotal" type="number" inputmode="numeric"
           placeholder="Counting the shelf whole is often faster" @blur="keep" />

    <h3>Our products</h3>
    <p v-if="!lines.length" class="muted">No catalogue on this phone yet. Sync to load it.</p>
    <ul class="lines">
      <li v-for="(line, i) in lines" :key="line.item_code + i" class="line">
        <label class="tick">
          <input type="checkbox" v-model="line.is_available" :true-value="1" :false-value="0"
                 @change="keep" />
          <span>{{ line.item_name }}</span>
        </label>
        <input class="facings tnum" type="number" inputmode="numeric" min="0"
               v-model="line.facings" :disabled="!line.is_available"
               aria-label="Facings" @blur="keep" />
      </li>
    </ul>

    <h3>Competition</h3>
    <div v-for="(c, i) in competitors" :key="i" class="comp">
      <input v-model="c.competitor" placeholder="Brand" @blur="keep" />
      <input v-model="c.product" placeholder="Product" @blur="keep" />
      <div class="row">
        <input v-model="c.selling_price" type="number" inputmode="decimal"
               placeholder="Selling price" @blur="keep" />
        <input v-model="c.facings" type="number" inputmode="numeric"
               placeholder="Facings" @blur="keep" />
      </div>
      <label class="tick">
        <input type="checkbox" v-model="c.has_scheme" :true-value="1" :false-value="0" @change="keep" />
        <span>Running a scheme</span>
      </label>
      <input v-if="c.has_scheme" v-model="c.scheme_note" placeholder="What is the offer?" @blur="keep" />
      <button type="button" class="btn-plain" @click="removeCompetitor(i)">Remove</button>
    </div>
    <button type="button" class="btn-plain" @click="addCompetitor">Add a competitor</button>

    <div class="bottom">
      <button class="btn-primary" :disabled="busy" @click="save">
        {{ busy ? 'Saving…' : 'Save shelf check' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
h2 { margin: 8px 0 4px; }
h3 { margin: 24px 0 8px; font-size: 16px; }
.muted { color: var(--muted); font-size: 14px; }
.tally { margin-top: 12px; padding: 12px; background: var(--surface);
         border: 1px solid var(--line); border-radius: 8px; }
.lbl { display: block; margin: 20px 0 6px; font-weight: 600; }
.lines { list-style: none; padding: 0; margin: 0; display: grid; gap: 6px; }
.line { display: flex; align-items: center; gap: 10px; padding: 8px 12px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
.tick { display: flex; align-items: center; gap: 10px; flex: 1; min-height: 44px;
        cursor: pointer; }
.tick input { width: 24px; height: 24px; min-height: 24px; flex: none; }
.facings { width: 84px; flex: none; text-align: right; }
.comp { display: grid; gap: 8px; padding: 12px; margin-bottom: 10px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 8px; }
.row { display: flex; gap: 8px; }
.btn-plain { background: none; border: 1px solid var(--line); color: var(--ink); width: 100%; }
.bottom { margin-top: auto; padding-top: 16px; }
</style>
