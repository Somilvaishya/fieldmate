<script setup>
import { ref, onMounted, computed } from 'vue'
import { localOutlets, refreshOutlets } from '../stores/outlets'

const rows = ref([])
const query = ref('')
const loading = ref(true)
const note = ref('')

async function load() {
  rows.value = await localOutlets({ query: query.value })
  loading.value = false
}

onMounted(async () => {
  await load()
  const result = await refreshOutlets()
  if (result.offline) note.value = 'Showing shops saved on this phone.'
  else await load()
})

const heading = computed(() =>
  loading.value ? 'Loading…' : `${rows.value.length} shop${rows.value.length === 1 ? '' : 's'}`
)
</script>

<template>
  <div class="wrap">
    <h2>Outlets</h2>
    <input v-model="query" placeholder="Search name, city or mobile" @input="load" />
    <p class="muted">{{ heading }}<span v-if="note"> · {{ note }}</span></p>

    <p v-if="!loading && !rows.length" class="muted empty">
      No shops yet. They arrive on the next sync, or add one with the button below.
    </p>

    <RouterLink v-for="o in rows" :key="o.name" :to="`/outlet/${o.name}`" class="row">
      <div class="line">
        <b>{{ o.outlet_name }}</b>
        <span v-if="o.approval_status !== 'Approved'" class="pill warn">Pending</span>
      </div>
      <div class="sub">{{ o.city || '—' }} · {{ o.mobile_no || 'no number' }}</div>
    </RouterLink>

    <RouterLink to="/outlet/new" class="btn-primary add">Add a shop</RouterLink>
  </div>
</template>

<style scoped>
h2 { margin: 8px 0 12px; }
.muted { color: var(--muted); font-size: 14px; }
.empty { padding: 24px 0; }
.row { display: block; padding: 12px; margin: 8px 0; background: var(--surface);
       border: 1px solid var(--line); border-radius: 6px; text-decoration: none; color: inherit;
       min-height: 48px; }
.line { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.sub { color: var(--muted); font-size: 14px; margin-top: 2px; }
.pill { font-size: 12px; padding: 2px 6px; border-radius: 3px; border: 1px solid; }
.warn { color: var(--warn); border-color: var(--warn); }
.add { display: block; margin-top: 16px; text-decoration: none; padding: 12px; }
</style>
