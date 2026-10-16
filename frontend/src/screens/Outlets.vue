<script setup>
import { ref, onMounted, computed } from 'vue'
import { localOutlets, refreshOutlets } from '../stores/outlets'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const all = ref([])
const query = ref('')
const filter = ref('all')
const loading = ref(true)
const note = ref('')
const visited = ref(new Set())

async function load() {
  all.value = await localOutlets()
  loading.value = false
}

onMounted(async () => {
  await load()
  const today = await visitStore.todaysVisits()
  visited.value = new Set(today.filter((v) => v.state === 'closed').map((v) => v.outlet))
  const result = await refreshOutlets()
  if (result.offline) note.value = t('Showing shops saved on this phone.')
  else await load()
})

function statusOf(o) {
  if (visited.value.has(o.name)) return 'visited'
  if (o.approval_status !== 'Approved') return 'pending'
  return 'todo'
}

const searched = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return all.value
  return all.value.filter((o) =>
    [o.outlet_name, o.city, o.mobile_no].some((v) => (v || '').toLowerCase().includes(q))
  )
})

const rows = computed(() =>
  filter.value === 'all'
    ? searched.value
    : searched.value.filter((o) => statusOf(o) === filter.value)
)

// Counts follow the search, not the whole book. A chip reading "Visited (4)" beside a
// search showing two of them would be lying about the list in front of the rep.
const counts = computed(() => {
  const c = { all: searched.value.length, visited: 0, pending: 0, todo: 0 }
  for (const o of searched.value) c[statusOf(o)] += 1
  return c
})

// A computed, not a const: the keys go to the filter logic and the labels to the rep, and a
// const would hold whichever language was loaded first.
const FILTERS = computed(() => [
  { key: 'all', label: t('All') },
  { key: 'todo', label: t('To visit') },
  { key: 'visited', label: t('Visited') },
  { key: 'pending', label: t('Pending approval') },
])
</script>

<template>
  <div class="wrap screen">
    <div class="head">
      <h2>{{ t(t('Shops')) }}</h2>
      <span class="muted tnum">{{ all.length }} total</span>
    </div>

    <div class="search">
      <Icon class="lead" name="search" size="20" />
      <input v-model="query" type="search" autocomplete="off"
             :placeholder="t('Search by name, area or phone')" :aria-label="t('Search shops')" />
      <button v-if="query" class="clear" :aria-label="t('Clear search')" @click="query = ''">
        <Icon name="close" size="20" />
      </button>
    </div>

    <div class="chips">
      <button v-for="f in FILTERS" :key="f.key" type="button"
              class="chip" :class="{ on: filter === f.key }"
              :aria-pressed="filter === f.key" @click="filter = f.key">
        <span>{{ f.label }}</span>
        <span class="count tnum">{{ counts[f.key] }}</span>
      </button>
    </div>

    <p class="muted result">
      <span v-if="loading">{{ t(t('Loading…')) }}</span>
      <span v-else class="tnum">Showing {{ rows.length }} of {{ all.length }}</span>
      <span v-if="note"> · {{ note }}</span>
    </p>

    <div class="list">
      <RouterLink v-for="o in rows" :key="o.name" :to="`/outlet/${o.name}`" class="row">
        <span class="info">
          <b>{{ o.outlet_name }}</b>
          <span class="muted area">{{ o.city || t('No area recorded') }}</span>
          <span v-if="o.mobile_no" class="muted tnum phone">
            <Icon name="phone" size="14" /> {{ o.mobile_no }}
          </span>
        </span>
        <span v-if="statusOf(o) === 'visited'" class="pill done">
          <Icon name="check" size="18" /> Visited
        </span>
        <span v-else-if="statusOf(o) === 'pending'" class="pill">
          <Icon name="alert" size="18" /> Pending approval
        </span>
        <Icon v-else class="go" name="chevron" size="22" />
      </RouterLink>
    </div>

    <!-- Empty states say which of the two things happened, because the fix is different:
         an over-narrow search is cleared, an empty book is synced. -->
    <div v-if="!loading && !rows.length" class="empty">
      <Icon name="store" size="36" />
      <b v-if="query || filter !== 'all'">{{ t(t('Nothing matches that')) }}</b>
      <b v-else>{{ t(t('No shops on this phone yet')) }}</b>
      <p class="muted" v-if="query || filter !== 'all'">
        No shop matches that name, area or number in this list.
      </p>
      <p class="muted" v-else>
        They arrive on the next sync. You can also add one now.
      </p>
      <button v-if="query || filter !== 'all'" class="ghost"
              @click="query = ''; filter = 'all'">
        {{ t(t('Clear search')) }}
      </button>
    </div>

    <div class="bottom">
      <RouterLink to="/outlet/new" class="btn-primary">
        <Icon name="plus" size="20" /> {{ t(t('Add a shop')) }}
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
h2 { margin: 8px 0 12px; }
.muted { color: var(--muted); font-size: 14px; }

.search { position: relative; display: flex; align-items: center; }
.search .lead { position: absolute; left: 12px; color: var(--muted); pointer-events: none; }
.search input { padding-left: 40px; padding-right: 48px; }
.clear { position: absolute; right: 0; width: 48px; height: 48px; min-height: 48px;
         display: grid; place-items: center; background: none; border: 0; color: var(--muted); }

/* Scrolls sideways rather than wrapping: a wrapped chip row pushes the list off screen,
   and the list is what the rep came for. */
.chips { display: flex; gap: 8px; margin-top: 12px; overflow-x: auto; padding-bottom: 4px;
         scrollbar-width: none; }
.chips::-webkit-scrollbar { display: none; }
.chip { flex: none; display: inline-flex; align-items: center; gap: 6px; min-height: 48px;
        padding: 0 14px; border-radius: 6px; font-size: 14px; font-weight: 600;
        background: var(--surface); border: 1px solid var(--line); color: var(--ink); }
.chip.on { background: var(--primary); border-color: var(--primary); color: var(--on-primary); }
.count { font-weight: 700; opacity: 0.8; }

.result { margin: 10px 0 8px; }
.list { display: grid; gap: 8px; }
.row { display: flex; align-items: center; gap: 10px; padding: 12px;
       background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
       text-decoration: none; color: inherit; min-height: 72px; }
.info { flex: 1; display: grid; gap: 2px; min-width: 0; }
.info b { overflow-wrap: anywhere; }
.area { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.phone { display: flex; align-items: center; gap: 5px; }
.go { color: var(--muted); flex: none; }
.pill { display: inline-flex; align-items: center; gap: 4px; flex: none; text-align: center;
        font-size: 14px; font-weight: 600; padding: 4px 8px; border-radius: 4px;
        border: 1px solid var(--warn); color: var(--warn); background: var(--warn-soft); }
.pill.done { border-color: var(--ok); color: var(--ok); background: var(--ok-soft); }

.empty { display: grid; justify-items: center; gap: 6px; text-align: center;
         padding: 40px 16px; color: var(--muted); }
.empty b { color: var(--ink); font-size: 16px; }
.empty p { margin: 0; max-width: 260px; }
.empty .ghost { margin-top: 8px; }

.bottom { position: sticky; bottom: 0; margin-top: auto; padding: 12px 0 4px;
          background: var(--bg); border-top: 1px solid var(--line); }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               text-decoration: none; padding: 14px; min-height: 52px; border-radius: 6px; }
.ghost { background: var(--surface); color: var(--primary); border: 1px solid var(--primary);
         border-radius: 6px; font-weight: 600; min-height: 48px; padding: 0 16px; }
</style>
