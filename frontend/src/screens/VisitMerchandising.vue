<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as role from '../stores/role'
import { db } from '../db'
import { enqueue } from '../sync/outbox'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const router = useRouter()
const visit = visitStore.activeVisit
const lines = ref([])
const competitors = ref([])
const shelfTotal = ref('')
const busy = ref(false)

const ourFacings = computed(() =>
  lines.value.reduce((sum, l) => sum + (l.is_available ? Number(l.facings) || 0 : 0), 0))
const theirFacings = computed(() =>
  competitors.value.reduce((sum, c) => sum + (Number(c.facings) || 0), 0))

// The rep may count the whole shelf directly - faster than listing every rival on a crowded
// one. Their figure wins when it is at least as large as what we can see; anything smaller
// is arithmetically impossible. The same rule the server applies, so the number shown here
// is the number that gets recorded.
const wholeShelf = computed(() =>
  Math.max(Number(shelfTotal.value) || 0, ourFacings.value + theirFacings.value))

const share = computed(() =>
  wholeShelf.value ? Math.round((ourFacings.value / wholeShelf.value) * 1000) / 10 : 0)

const present = computed(() => lines.value.filter((l) => l.is_available).length)

onMounted(async () => {
  if (!visit.value) await visitStore.resume()
  if (!visit.value) return router.replace(role.homeRoute.value)

  const draft = await db.meta.get('merch:' + visit.value.clientUuid)
  if (draft?.value) {
    lines.value = draft.value.lines || []
    competitors.value = draft.value.competitors || []
    shelfTotal.value = draft.value.shelfTotal || ''
    return
  }
  // Seeded from the catalogue this phone already holds, so the rep ticks rather than types.
  //
  // All of it, and in a settled order. It used to be `.slice(0, 60)` over whatever order
  // IndexedDB happened to return: a range of more than sixty lost the rest with nothing on the
  // screen saying so, there was no way to add a product back, and *which* sixty survived could
  // change between two visits to the same shop. A shelf check that cannot see a product cannot
  // report it missing, which is the one thing it exists to do.
  const items = await db.records.where('doctype').equals('FieldMate Catalogue Item').toArray()
  lines.value = items
    .map((i) => ({
      item_code: i.item_code || i.name,
      item_name: i.item_name || i.item_code || i.name,
      mrp: i.mrp || null,
      is_available: 0,
      facings: 0,
    }))
    .sort((a, b) => a.item_name.localeCompare(b.item_name))
})

// Typing beats scrolling once the list is the whole range. Ticked products stay visible whatever
// is typed: a rep who filters, ticks, then filters again must be able to see what they have
// already counted, or they count it twice.
const query = ref('')
const shown = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return lines.value
  return lines.value.filter(
    (l) => l.is_available ||
      l.item_name.toLowerCase().includes(q) ||
      String(l.item_code).toLowerCase().includes(q)
  )
})

function toggle(line) {
  line.is_available = line.is_available ? 0 : 1
  // Ticking a product means at least one facing; unticking means none, not "unknown".
  line.facings = line.is_available ? Math.max(1, Number(line.facings) || 0) : 0
  keep()
}

function step(row, delta) {
  row.facings = Math.max(0, (Number(row.facings) || 0) + delta)
  if (delta > 0 && row.is_available === 0) row.is_available = 1
  keep()
}

function addCompetitor() {
  competitors.value.push({
    competitor: '', product: '', selling_price: null, facings: 1, has_scheme: 0, scheme_note: '',
  })
}

function removeCompetitor(index) {
  competitors.value.splice(index, 1)
  keep()
}

async function keep() {
  if (!visit.value) return
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
      total_facings: wholeShelf.value,
      created_offline: 1,
      lines: lines.value
        .filter((l) => l.is_available || Number(l.facings) > 0)
        .map((l) => ({
          item_code: l.item_code,
          is_available: l.is_available ? 1 : 0,
          facings: Number(l.facings) || 0,
          mrp: l.mrp || null,
        })),
      competitors: competitors.value
        .filter((c) => c.competitor && c.product)
        .map((c) => ({
          competitor: c.competitor,
          product: c.product,
          selling_price: c.selling_price || null,
          facings: Number(c.facings) || 0,
          has_scheme: c.has_scheme ? 1 : 0,
          scheme_note: c.scheme_note || null,
        })),
    }, { dependsOn: visit.value.clientUuid })

    await visitStore.markTask('Merchandising')
    router.back()
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap screen" v-if="visit">
    <div class="top">
      <div class="head">
        <div>
          <span class="eyebrow">{{ t('Shelf check') }}</span>
          <h2>{{ visit.outletName }}</h2>
        </div>
      </div>

      <!-- Share of shelf, the number this screen exists to produce. -->
      <div class="card kpi">
        <div class="figures">
          <div>
            <span class="muted">{{ t('Ours') }}</span>
            <b class="tnum">{{ ourFacings }}</b>
          </div>
          <div>
            <span class="muted">{{ t('Theirs') }}</span>
            <b class="tnum">{{ theirFacings }}</b>
          </div>
          <div>
            <span class="muted">{{ t('Share') }}</span>
            <b class="tnum big">{{ share }}%</b>
          </div>
        </div>
        <div class="bar" v-if="wholeShelf">
          <div class="ours" :style="{ width: share + '%' }"></div>
          <div class="theirs" :style="{ width: (100 - share) + '%' }"></div>
        </div>
        <div class="legend" v-if="wholeShelf">
          <span class="tnum">
            <i class="swatch ours"></i>
            {{ t('Ours ({n})', { n: ourFacings }) }}
          </span>
          <span class="tnum">
            <i class="swatch theirs"></i>
            {{ t('Rest of shelf ({n})', { n: wholeShelf - ourFacings }) }}
          </span>
        </div>
      </div>

      <div class="card">
        <label class="lbl" for="total">{{ t('Facings on the whole shelf') }}</label>
        <div class="whole">
          <input id="total" v-model="shelfTotal" type="number" inputmode="numeric" min="0"
                 class="tnum" :placeholder="String(ourFacings + theirFacings)" @blur="keep" />
          <span class="unit">{{ t('facings') }}</span>
        </div>
        <p class="muted hint">
          {{ t('Counting the whole shelf is often quicker than listing every rival.') }}
          {{ t('Leave it blank and we add up what you entered.') }}
        </p>
      </div>

      <div class="section">
        <h3>{{ t('Our products') }}</h3>
        <span class="pill tnum" v-if="lines.length">
          {{ t('{present} of {total} on shelf',
               { present, total: lines.length }) }}
        </span>
      </div>
      <p v-if="!lines.length" class="muted pad">
        {{ t('No catalogue on this phone yet. Sync once to load it.') }}
      </p>

      <!-- Nothing is added here: the whole range is already listed and the rep ticks what is on
           the shelf. The search is how they reach a product without scrolling the range. -->
      <input v-if="lines.length > 12" v-model="query" type="search" class="find"
             :placeholder="t('Find a product')" :aria-label="t('Find a product')" />

      <div class="rows">
        <div v-for="line in shown" :key="line.item_code" class="prow"
             :class="{ off: !line.is_available }">
          <button type="button" class="tick" role="checkbox"
                  :aria-checked="!!line.is_available" @click="toggle(line)">
            <span class="box" :class="{ on: line.is_available }">
              <Icon v-if="line.is_available" name="check" size="18" />
            </span>
            <span class="pinfo">
              <b>{{ line.item_name }}</b>
              <span class="muted tnum" v-if="line.mrp">
                {{ t('₹{amount} MRP', { amount: line.mrp }) }}
              </span>
              <span class="muted oos" v-else-if="!line.is_available">
                {{ t('Not on shelf') }}
              </span>
            </span>
          </button>
          <div class="stepper">
            <button type="button" :aria-label="t('One less facing')"
                    :disabled="!line.is_available"
                    @click="step(line, -1)"><Icon name="minus" size="20" /></button>
            <input class="tnum" type="number" inputmode="numeric" min="0"
                   v-model="line.facings" :disabled="!line.is_available"
                   :aria-label="t('Facings')" @blur="keep" />
            <button type="button" :aria-label="t('One more facing')"
                    @click="step(line, 1)"><Icon name="plus" size="20" /></button>
          </div>
        </div>
      </div>

      <div class="section">
        <h3>{{ t('Competition') }}</h3>
        <span class="pill tnum" v-if="competitors.length">
          {{ t('{n} tracked', { n: competitors.length }) }}
        </span>
      </div>

      <div v-for="(c, i) in competitors" :key="i" class="card comp">
        <div class="crow">
          <input v-model="c.competitor" :placeholder="t('Brand')" @blur="keep" />
          <input v-model="c.product" :placeholder="t('Product')" @blur="keep" />
        </div>
        <div class="crow">
          <div class="money">
            <span class="rs">₹</span>
            <input v-model="c.selling_price" type="number" inputmode="decimal" class="tnum"
                   :placeholder="t('Shelf price')" @blur="keep" />
          </div>
          <div class="stepper">
            <button type="button" :aria-label="t('One less facing')" @click="step(c, -1)">
              <Icon name="minus" size="20" />
            </button>
            <input class="tnum" type="number" inputmode="numeric" min="0" v-model="c.facings"
                   :aria-label="t('Competitor facings')" @blur="keep" />
            <button type="button" :aria-label="t('One more facing')" @click="step(c, 1)">
              <Icon name="plus" size="20" />
            </button>
          </div>
        </div>
        <label class="scheme">
          <input type="checkbox" v-model="c.has_scheme" :true-value="1" :false-value="0"
                 @change="keep" />
          <span>{{ t('Running a scheme') }}</span>
        </label>
        <input v-if="c.has_scheme" v-model="c.scheme_note" :placeholder="t('What is the offer?')"
               @blur="keep" />
        <button type="button" class="ghost danger" @click="removeCompetitor(i)">
          {{ t('Remove') }}
        </button>
      </div>

      <button type="button" class="ghost" @click="addCompetitor">
        <Icon name="plus" size="20" /> {{ t('Add a competitor product') }}
      </button>
    </div>

    <div class="bottom">
      <button class="btn-primary" :disabled="busy" @click="save">
        {{ busy ? t('Saving…') : t('Save shelf check') }}
      </button>
      <p class="muted foot">
        {{ t('Saved on this phone, then sent when you have signal.') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: grid; gap: 12px; align-content: start; }
.head { margin: 8px 0 0; }
.eyebrow { display: block; font-size: 14px; font-weight: 700; letter-spacing: 0.05em;
           text-transform: uppercase; color: var(--muted); }
h2 { margin: 2px 0 0; font-size: 20px; overflow-wrap: anywhere; }
h3 { margin: 0; font-size: 16px; }
.muted { color: var(--muted); font-size: 14px; font-weight: 400; }
.pad { padding: 16px 0; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; }
.kpi { display: grid; gap: 10px; }
.figures { display: grid; grid-template-columns: repeat(3, 1fr); text-align: center; gap: 8px; }
.figures div { display: grid; gap: 2px; }
.figures b { font-size: 22px; }
.figures .big { color: var(--primary); }
.bar { display: flex; height: 12px; border-radius: 6px; overflow: hidden;
       background: var(--primary-soft); }
.bar .ours { background: var(--primary); }
.bar .theirs { background: var(--crit-soft); }
.legend { display: flex; justify-content: space-between; font-size: 14px; color: var(--muted); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.swatch.ours { background: var(--primary); }
.swatch.theirs { background: var(--crit-soft); border: 1px solid var(--line); }

.lbl { display: block; font-weight: 600; font-size: 16px; margin-bottom: 6px; }
.whole { position: relative; display: flex; align-items: center; }
.whole input { padding-right: 78px; }
.unit { position: absolute; right: 14px; font-weight: 600; color: var(--muted);
        pointer-events: none; font-size: 14px; }
.hint { margin: 6px 0 0; }

.find { width: calc(100% - 32px); margin: 0 16px 8px; min-height: 48px; padding: 0 12px;
        border: 1px solid var(--line); border-radius: 8px; background: var(--surface);
        color: var(--text); font-size: 15px; }
.section { display: flex; justify-content: space-between; align-items: center; gap: 8px;
           margin-top: 8px; }
.pill { flex: none; font-size: 14px; font-weight: 600; padding: 3px 8px; border-radius: 4px;
        background: var(--primary-soft); color: var(--primary); }

.rows { display: grid; gap: 6px; }
.prow { display: flex; align-items: center; gap: 8px; padding: 8px 10px;
        background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        min-height: 64px; }
.prow.off { background: var(--bg); }
.tick { flex: 1; display: flex; align-items: center; gap: 10px; min-width: 0; min-height: 48px;
        background: none; border: 0; text-align: left; padding: 0; }
.box { width: 26px; height: 26px; flex: none; display: grid; place-items: center;
       border-radius: 4px; border: 2px solid var(--muted); background: var(--surface); }
.box.on { background: var(--primary); border-color: var(--primary); color: var(--on-primary); }
.pinfo { display: grid; gap: 1px; min-width: 0; }
.pinfo b { overflow-wrap: anywhere; font-size: 16px; }
.oos { color: var(--muted); }

.stepper { display: flex; align-items: center; gap: 4px; flex: none; }
.stepper button { width: 48px; height: 48px; min-height: 48px; display: grid; place-items: center;
                  border-radius: 6px; background: var(--primary-soft); color: var(--primary);
                  border: 0; }
.stepper button:disabled { background: var(--bg); color: var(--line); }
.stepper input { width: 52px; min-height: 48px; text-align: center; padding: 0 4px;
                 font-weight: 700; }
.stepper input:disabled { color: var(--muted); background: var(--bg); }

.comp { display: grid; gap: 8px; }
.crow { display: flex; gap: 8px; }
.crow > input { flex: 1; min-width: 0; }
.money { position: relative; display: flex; align-items: center; flex: 1; min-width: 0; }
.money .rs { position: absolute; left: 12px; font-weight: 700; color: var(--muted); }
.money input { padding-left: 28px; }
.scheme { display: flex; align-items: center; gap: 10px; min-height: 48px; }
.scheme input { width: 24px; height: 24px; min-height: 0; flex: none; }

.ghost { display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%;
         min-height: 48px; background: var(--surface); color: var(--primary);
         border: 1px solid var(--primary); border-radius: 6px; font-weight: 600; }
.ghost.danger { color: var(--crit); border-color: var(--crit); }

.bottom { position: sticky; bottom: 0; padding: 12px 0 4px; margin-top: 16px;
          background: var(--bg); border-top: 1px solid var(--line); }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               padding: 14px; min-height: 52px; border-radius: 6px; width: 100%; }
.foot { text-align: center; margin: 8px 0 0; }
</style>
