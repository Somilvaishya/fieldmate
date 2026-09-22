<script setup>
import { ref, onMounted } from 'vue'
import { db } from '../db'
import { localOutlets } from '../stores/outlets'

const beats = ref([])
const counts = ref({})

onMounted(async () => {
  beats.value = await db.records.where('doctype').equals('FieldMate Beat').toArray()
  for (const b of beats.value) {
    counts.value[b.name] = (await localOutlets({ beat: b.name })).length
  }
})
</script>

<template>
  <div class="wrap">
    <h2>My beats</h2>
    <p v-if="!beats.length" class="muted">
      No routes on this phone yet. They arrive on the next sync.
    </p>
    <RouterLink v-for="b in beats" :key="b.name" :to="`/outlets?beat=${b.name}`" class="row">
      <div class="line"><b>{{ b.beat_name }}</b><span class="muted">{{ b.visit_day }}</span></div>
      <div class="muted">{{ counts[b.name] ?? 0 }} shops · {{ b.frequency }}</div>
    </RouterLink>
  </div>
</template>

<style scoped>
h2 { margin: 8px 0 12px; }
.muted { color: var(--muted); font-size: 14px; }
.row { display: block; padding: 12px; margin: 8px 0; background: var(--surface);
       border: 1px solid var(--line); border-radius: 6px; text-decoration: none; color: inherit;
       min-height: 48px; }
.line { display: flex; justify-content: space-between; gap: 8px; }
</style>
