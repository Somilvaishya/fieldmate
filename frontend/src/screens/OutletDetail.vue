<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError } from '../api/client'
import { localOutlet } from '../stores/outlets'

const route = useRoute()
const outlet = ref(null)
const detail = ref(null)
const note = ref('')

onMounted(async () => {
  outlet.value = await localOutlet(route.params.name)
  try {
    detail.value = await api.outlet(route.params.name)
    outlet.value = detail.value.outlet
  } catch (e) {
    note.value = e instanceof ApiError && e.code === 'OFFLINE'
      ? 'Offline — showing what is saved on this phone.'
      : e.message
  }
})
</script>

<template>
  <div class="wrap">
    <RouterLink to="/outlets" class="back">← Outlets</RouterLink>
    <p v-if="note" class="muted">{{ note }}</p>
    <div v-if="outlet">
      <h2>{{ outlet.outlet_name }}</h2>
      <p class="muted">{{ outlet.city || '—' }} · {{ outlet.mobile_no || 'no number' }}</p>

      <div v-if="detail" class="card" :class="detail.can_take_order ? 'ok' : 'blocked'">
        <b>{{ detail.can_take_order ? 'Ready to take an order' : 'Cannot take an order yet' }}</b>
        <p v-if="!detail.can_take_order" class="muted">{{ detail.blocked_reason }}</p>
        <p v-if="detail.credit && detail.credit.headroom !== null" class="muted">
          Credit headroom: {{ detail.credit.headroom }}
        </p>
        <p v-else-if="detail.credit && detail.credit.unlimited" class="muted">No credit limit set</p>
      </div>

      <div class="card">
        <div class="kv"><span>Status</span><b>{{ outlet.outlet_status }}</b></div>
        <div class="kv"><span>Approval</span><b>{{ outlet.approval_status }}</b></div>
        <div class="kv"><span>Class</span><b>{{ outlet.outlet_class || '—' }}</b></div>
        <div class="kv"><span>Beat</span><b>{{ outlet.primary_beat || 'not on a route' }}</b></div>
        <div class="kv"><span>Territory</span><b>{{ outlet.territory }}</b></div>
      </div>

      <div v-if="detail && detail.contacts.length" class="card">
        <b>People</b>
        <div v-for="c in detail.contacts" :key="c.person_name" class="kv">
          <span>{{ c.person_name }}<em v-if="c.is_primary"> · primary</em></span>
          <b>{{ c.mobile_no || '—' }}</b>
        </div>
      </div>
    </div>
    <p v-else class="muted">Shop not found on this phone yet.</p>
  </div>
</template>

<style scoped>
.back { display: inline-block; padding: 12px 0; color: var(--primary); text-decoration: none; }
h2 { margin: 4px 0; }
.muted { color: var(--muted); font-size: 14px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 12px; margin: 12px 0; }
.card.ok { border-color: var(--ok); }
.card.blocked { border-color: var(--warn); }
.kv { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; }
.kv span { color: var(--muted); }
em { font-style: normal; color: var(--muted); }
</style>
