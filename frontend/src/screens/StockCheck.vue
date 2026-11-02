<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as role from '../stores/role'
import { api, ApiError } from '../api/client'
import { deviceUuid } from '../db'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

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
      // The unit he is counting in, by name. It used to be a two-way flag between the stock UOM
      // and the order UOM, which is fine for an item sold in pieces and cases and wrong for one
      // sold in pieces, boxes and cases - the third unit could not be chosen at all, so a rep
      // holding a carton counted it as whichever of the two was nearer.
      uom: item.order_uom || item.stock_uom,
    }))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t('Could not load the product list.')
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

/**
 * The pack shot, or the initials standing in for one.
 *
 * Same rule as the item list: most items on most sites carry no image, and a broken frame beside
 * a count box is worse than no picture at all. An image that fails to load joins `broken` and the
 * row falls back to the same tinted box, so a dead `/files/...` path cannot leave a hole in a
 * list a rep is working down.
 */
const broken = ref(new Set())

function imageFor(row) {
  return row.image && !broken.value.has(row.item_code) ? row.image : null
}

function onImageError(row) {
  broken.value = new Set([...broken.value, row.item_code])
}

function initials(row) {
  const words = String(row.item_name || row.item_code || '').trim().split(/\s+/).filter(Boolean)
  if (!words.length) return '?'
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()
  return (words[0][0] + words[1][0]).toUpperCase()
}

function unitsFor(row) {
  const list = (row.order_uoms || [])
    .map((u) => ({ uom: u.uom, factor: Number(u.conversion_factor) || 1 }))
    .filter((u) => u.uom)
  if (list.length) return list
  // A site that has not taken the update yet sends only the two. Kept so a handset that updates
  // first still counts in something real rather than in nothing.
  const out = [{ uom: row.stock_uom, factor: 1 }]
  if (row.order_uom && row.order_uom !== row.stock_uom) {
    out.push({ uom: row.order_uom, factor: Number(row.conversion_factor) || 1 })
  }
  return out.filter((u) => u.uom)
}

function sameAsLast(row) {
  if (!row.has_history) return
  row.qty_display = row.last_display_qty ?? row.last_qty ?? 0
  // In the unit it was counted in last time, where that unit is still on offer. Counting 14 of
  // something in cases when last time it was boxes is not "same as last time".
  if (row.last_uom && unitsFor(row).some((u) => u.uom === row.last_uom)) row.uom = row.last_uom
  row.is_counted = true
}

function factorFor(row) {
  const found = unitsFor(row).find((u) => u.uom === row.uom)
  return found ? found.factor : 1
}

function uomFor(row) {
  return row.uom || row.stock_uom
}

async function save() {
  error.value = ''
  busy.value = true
  try {
    const open = await visitStore.ensureActive()
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
    // Tell the visit, or the rep walks back into the hub and reads "None yet" over the count they
    // just took. Only the server knew about it before this line.
    await visitStore.markTask('Stock Audit')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t('Could not save the count.')
  } finally {
    busy.value = false
  }
}

function done() {
  const open = visitStore.activeVisit.value  // warm by now: save() asked for it
  router.replace(open ? { name: 'visit', params: { uuid: open.clientUuid } } : role.homeRoute.value)
}
</script>

<template>
  <div v-if="saved" class="wrap screen">
    <div class="top">
      <div class="card ok-card">
        <p class="badge">
          <Icon name="check" size="22" /><span>{{ t('Stock saved') }}</span>
        </p>
        <b class="big tnum">
          {{ t('{counted} of {total} counted',
               { counted: saved.counted_lines, total: saved.total_lines }) }}
        </b>
        <p v-if="saved.is_partial" class="muted">
          {{ t('Saved with {n} products not counted.',
               { n: saved.total_lines - saved.counted_lines }) }}
          {{ t('That is fine — a partial count is worth more than none.') }}
        </p>
        <p v-else class="muted">{{ t('Every product on the list was counted.') }}</p>
      </div>
    </div>
    <div class="bottom">
      <button class="btn-primary" @click="done">{{ t('Done') }}</button>
    </div>
  </div>

  <div v-else class="wrap screen">

    <div v-if="loading" class="muted pad">{{ t('Loading the product list…') }}</div>

    <div v-else-if="!rows.length" class="card pad">
      <p>
        <Icon name="alert" size="18" /> {{ t('No products listed for this shop yet.') }}
      </p>
      <p class="muted">{{ t('Ask your manager to set up the catalogue for it.') }}</p>
    </div>

    <template v-else>
      <div class="head">
        <h1>{{ sheet.outlet_name }}</h1>
        <p class="muted tnum">
          <Icon name="clock" size="16" />
          <span v-if="sheet.days_since != null">
            {{ t('Last counted {n} days ago', { n: sheet.days_since }) }}
          </span>
          <span v-else>{{ t('First stock check here') }}</span>
        </p>
      </div>

      <!-- Pinned, because it is the only thing telling him how much is left while he scrolls. -->
      <div class="progress">
        <div class="pline tnum">
          <b>{{ t('{counted} of {total} products counted',
                 { counted, total: rows.length }) }}</b>
          <span :class="pct === 100 ? 'ok' : 'muted'">{{ pct }}%</span>
        </div>
        <div class="track"><span class="fill" :style="{ width: pct + '%' }"></span></div>
        <input v-model="search" class="find" :placeholder="t('Search SKU code or name')" />
      </div>

      <section v-for="group in groups" :key="group.name" class="group">
        <h2 class="ghead">
          <span>{{ group.name }}</span>
          <span class="muted tnum">
            {{ t('{counted} of {total}',
                 { counted: group.counted, total: group.items.length }) }}
          </span>
        </h2>

        <!-- One list, hairlines between rows, rather than a bordered card each. Six products
             used to fill two screens: every line carried its own border, its own heading and a
             footer strip, and a rep counting a shelf of thirty scrolled more than he counted.
             Each row is now two columns - what it is on the left, what he types on the right. -->
        <div class="list">
          <article v-for="row in group.items" :key="row.item_code"
                   class="row" :class="{ done: row.is_counted }">
            <span class="thumb" aria-hidden="true">
              <img v-if="imageFor(row)" :src="imageFor(row)" alt="" @error="onImageError(row)" />
              <template v-else>{{ initials(row) }}</template>
            </span>
            <div class="idn">
              <h3>{{ row.item_name }}</h3>
              <p class="meta tnum">
                <span class="code">{{ row.item_code }}</span>
                <!-- Named, not "per case". The factor describes a particular unit, and saying
                     "per case" over an item sold in boxes was the same lie the buttons told. -->
                <span v-if="factorFor(row) > 1">
                  {{ t('{n} {base} per {uom}',
                       { n: factorFor(row), base: row.stock_uom, uom: uomFor(row) }) }}
                </span>
                <span v-if="row.is_counted && !row.qty_display" class="chip crit">
                  {{ t('Out of stock') }}
                </span>
                <span v-if="row.is_must_sell" class="chip">{{ t('Must sell') }}</span>
              </p>
              <p class="meta last tnum">
                <template v-if="row.has_history">
                  <span>{{ t('Last visit: {qty} {uom}', {
                             qty: row.last_display_qty ?? row.last_qty,
                             uom: row.last_uom }) }}</span>
                  <!-- Icon only, with the sentence left on the label. The words were a
                       full-width button under every line; a rep who wants them reads the
                       figure beside it, which says the same thing. -->
                  <button type="button" class="again" @click="sameAsLast(row)"
                          :aria-label="t('Same as last time')"
                          :title="t('Same as last time')">
                    <Icon name="copy" size="16" />
                  </button>
                </template>
                <template v-else>{{ t('Never counted here') }}</template>
              </p>
            </div>

            <div class="entry">
              <!-- A keypad, not a stepper. He is typing 14, not tapping plus fourteen times. -->
              <input
                class="qty tnum"
                type="number"
                inputmode="numeric"
                min="0"
                :value="row.qty_display"
                :aria-label="t('Count of {item}', { item: row.item_name })"
                placeholder="0"
                @input="setQty(row, $event.target.value)"
              />
              <!-- The item's own units, by their own names. Two buttons reading "Cases" and
                   "Pcs" stood here: hardcoded words, so an item sold in boxes had a button
                   saying Cases over a number that was being stored as boxes, and a third unit
                   could not be reached at all. -->
              <select class="units" v-model="row.uom"
                      :aria-label="t('Unit for {item}', { item: row.item_name })">
                <option v-for="u in unitsFor(row)" :key="u.uom" :value="u.uom">{{ u.uom }}</option>
              </select>
            </div>
          </article>
        </div>
      </section>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>

      <div class="bottom">
        <p v-if="missing" class="note warn-note tnum">
          <Icon name="alert" size="16" />
          <span>
            {{ t('{n} products not counted — save anyway?', { n: missing }) }}
          </span>
        </p>
        <p class="muted note">
          <Icon name="cloud-off" size="16" />
          {{ t('Saved on this phone. Syncs when you have signal.') }}
        </p>
        <button class="btn-primary" :disabled="busy || !counted" @click="save">
          {{ busy ? t('Saving…') : t('Save stock') }}
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

.list { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        overflow: hidden; }
.row { display: flex; align-items: center; gap: 10px; padding: 8px 10px;
       border-left: 3px solid transparent; }
.row + .row { border-top: 1px solid var(--line); }
.row.done { border-left-color: var(--ok); }
/* 40px, not the item list's 46: that screen is a shelf of pack shots to browse, this one is a
   list to work down, and the picture is here to confirm a name rather than to sell anything. */
.thumb { width: 40px; height: 40px; flex: none; border-radius: 6px;
         background: var(--primary-soft); color: var(--primary); display: grid;
         place-items: center; font-weight: 700; font-size: 14px; overflow: hidden; }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.idn { flex: 1; min-width: 0; }
.row h3 { margin: 0; font-size: 15px; font-weight: 600; line-height: 1.3;
          overflow-wrap: anywhere; }
.meta { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 6px; margin: 2px 0 0;
        font-size: 13px; color: var(--muted); }
.meta.last { margin-top: 1px; }
.code { font-weight: 600; background: var(--primary-soft); color: var(--primary);
        padding: 0 5px; border-radius: 4px; }

/* The count box and the unit box share a fixed track, and both widths are stated. A bare
   `select` carries `width: 100%` from the global sheet, which as a flex item reads as a basis
   of the whole row; the count box, asked only for what was left over, was left a sliver too
   narrow to tap or to read two digits in. */
.entry { display: flex; gap: 6px; align-items: stretch; flex: 0 0 158px; min-width: 0; }
/* Basis zero, not `auto`. A text input's intrinsic width is about twenty characters, so `auto`
   made this pair 260px wide; a flex item will not shrink below its content, so the declared
   158px was ignored and the item name was crushed to one letter per line instead. */
.qty { flex: 1 1 0; width: 0; min-width: 0; padding: 0 6px;
       font-size: 18px; font-weight: 700; text-align: center; }
/* Room for a real unit name - "Carton" does not fit in 62px. */
.units { flex: 0 0 88px; width: 88px; min-width: 0; min-height: 48px; padding: 0 6px;
         border-radius: 6px; border: 1px solid var(--line); background: var(--surface);
         color: var(--text); font-weight: 600; font-size: 14px; }

/* Still a 44px target, but it sits inside the meta line rather than owning a strip of its own. */
.again { display: inline-grid; place-items: center; width: 44px; height: 44px; margin: -12px 0;
         padding: 0; background: none; color: var(--primary); border: 0; }

.chip { font-size: 12px; font-weight: 600; padding: 0 6px; border-radius: 4px;
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
