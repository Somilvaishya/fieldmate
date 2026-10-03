<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'

const route = useRoute()
const router = useRouter()

const position = ref(null)
const picked = ref(new Set())
const overdueOnly = ref(false)
const loading = ref(true)
const error = ref('')

// Oldest first, because that is the bill being argued about. A rep who collects against the
// newest invoice leaves the one that has been outstanding for six weeks exactly where it was.
const bills = computed(() => {
  const rows = position.value?.bills || []
  return overdueOnly.value ? rows.filter((b) => b.days_overdue > 0) : rows
})

const selected = computed(() =>
  (position.value?.bills || []).filter((b) => picked.value.has(b.reference_name))
)
const selectedTotal = computed(() => selected.value.reduce((t, b) => t + b.pending, 0))

const buckets = computed(() => {
  const a = position.value?.ageing || {}
  return [
    { label: '0–7 days', amount: a.bucket_0_7 || 0, tone: 'ok' },
    { label: '8–14 days', amount: a.bucket_8_14 || 0, tone: 'muted' },
    { label: '15–30 days', amount: a.bucket_15_30 || 0, tone: 'warn' },
    // Kept apart rather than folded into a total, because a total hides it and this is the
    // bucket that decides whether the rep pushes or walks away.
    { label: 'Over 30 days', amount: a.bucket_30_plus || 0, tone: 'crit' },
  ]
})

onMounted(async () => {
  try {
    position.value = await api.outstanding(route.params.outlet)
    // Overdue bills start ticked. It is what the rep came to collect, and pre-selecting it saves
    // the tap that is right nine times in ten.
    for (const bill of position.value.bills || []) {
      if (bill.days_overdue > 0) picked.value.add(bill.reference_name)
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : 'Could not load what this shop owes.'
  } finally {
    loading.value = false
  }
})

function toggle(bill) {
  const next = new Set(picked.value)
  next.has(bill.reference_name) ? next.delete(bill.reference_name) : next.add(bill.reference_name)
  picked.value = next
}

function collect() {
  router.push({
    name: 'collect',
    params: { outlet: position.value.outlet },
    query: { bills: [...picked.value].join(','), amount: selectedTotal.value },
  })
}
</script>

<template>
  <div class="wrap screen">

    <div v-if="loading" class="muted pad">Loading what this shop owes…</div>
    <p v-else-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>

    <template v-else>
      <div class="head">
        <h1>{{ position.outlet_name }}</h1>
        <p class="muted">Owed to {{ position.distributor || 'its distributor' }}</p>
      </div>

      <div class="card total">
        <div class="tline">
          <div>
            <span class="label">Total outstanding</span>
            <b class="big tnum">{{ formatRupees(position.outstanding) }}</b>
          </div>
          <div v-if="position.overdue" class="overdue tnum">
            <span>Overdue · {{ position.days_overdue }} days</span>
            <b>{{ formatRupees(position.overdue) }}</b>
          </div>
        </div>

        <div v-if="position.credit_limit" class="limit tnum">
          <span>Limit {{ formatRupees(position.credit_limit) }}</span>
          <span :class="position.headroom > 0 ? 'ok' : 'crit'">
            {{ position.headroom > 0 ? formatRupees(position.headroom) + ' left' : 'Over limit' }}
          </span>
        </div>
        <!-- A shop nobody has given a limit is not a shop with no room. The two read identically
             as zero, so the difference is said in words. -->
        <p v-else class="muted small">No credit limit set for this shop.</p>
      </div>

      <h2 class="shead">Ageing</h2>
      <div class="card ageing tnum">
        <div v-for="b in buckets" :key="b.label" class="bline" :class="b.tone">
          <span>{{ b.label }}</span>
          <b>{{ formatRupees(b.amount) }}</b>
        </div>
      </div>

      <div class="shead row">
        <h2>Bills to collect</h2>
        <button type="button" class="filter" :class="{ on: overdueOnly }"
                @click="overdueOnly = !overdueOnly">
          {{ overdueOnly ? 'Showing overdue' : 'Overdue only' }}
        </button>
      </div>

      <p v-if="!bills.length" class="card pad muted">
        <Icon name="check" size="18" />
        {{ overdueOnly ? 'Nothing overdue here.' : 'This shop owes nothing.' }}
      </p>

      <article v-for="bill in bills" :key="bill.reference_name"
               class="bill" :class="{ on: picked.has(bill.reference_name), late: bill.days_overdue > 0 }"
               @click="toggle(bill)">
        <div class="btop">
          <span class="box" :class="{ ticked: picked.has(bill.reference_name) }">
            <Icon v-if="picked.has(bill.reference_name)" name="check" size="16" />
          </span>
          <div class="bmain">
            <b class="tnum">{{ bill.bill_no }}</b>
            <span class="muted tnum">Dated {{ bill.bill_date }} · {{ formatRupees(bill.amount) }}</span>
          </div>
          <span class="age tnum" :class="bill.days_overdue > 0 ? 'crit' : 'muted'">
            {{ bill.days_overdue > 0 ? bill.days_overdue + 'd overdue' : 'Due ' + bill.due_date }}
          </span>
        </div>
        <div class="bfoot tnum">
          <span class="muted">Pending</span>
          <b>{{ formatRupees(bill.pending) }}</b>
        </div>
      </article>

      <div v-if="position.last_payment" class="card last tnum">
        <span class="label">Last payment</span>
        <div class="lline">
          <b>{{ formatRupees(position.last_payment.amount) }}</b>
          <span class="muted">{{ position.last_payment.collection_date }} ·
            {{ position.last_payment.mode }} · {{ position.last_payment.receipt_no }}</span>
        </div>
      </div>

      <div class="bottom">
        <p class="muted note tnum" v-if="selected.length">
          {{ selected.length }} bill{{ selected.length > 1 ? 's' : '' }} selected ·
          {{ formatRupees(selectedTotal) }}
        </p>
        <button class="btn-primary" :disabled="!position.outstanding" @click="collect">
          {{ selected.length ? 'Collect ' + formatRupees(selectedTotal) : 'Record a collection' }}
        </button>
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
.label { display: block; font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em;
         color: var(--muted); }
.big { font-size: 24px; display: block; margin-top: 2px; }
.small { font-size: 13px; margin: 8px 0 0; }

.tline { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.overdue { text-align: right; background: var(--crit-soft); color: var(--crit);
           border-radius: 6px; padding: 7px 10px; font-size: 13px; }
.overdue b { display: block; font-size: 17px; margin-top: 2px; }
.limit { display: flex; justify-content: space-between; margin-top: 12px; padding-top: 10px;
         border-top: 1px solid var(--line); font-size: 14px; }
.limit .ok { color: var(--ok); font-weight: 600; }
.limit .crit { color: var(--crit); font-weight: 600; }

.shead { margin: 18px 0 8px; font-size: 14px; text-transform: uppercase;
         letter-spacing: 0.04em; color: var(--muted); }
.shead.row { display: flex; align-items: center; justify-content: space-between; }
.shead h2 { margin: 0; font: inherit; }
.filter { min-height: 48px; padding: 0 12px; background: var(--surface);
          border: 1px solid var(--line); color: var(--muted); font-size: 14px; font-weight: 600; }
.filter.on { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }

.ageing { padding: 4px 14px; }
.bline { display: flex; justify-content: space-between; padding: 10px 0; }
.bline + .bline { border-top: 1px solid var(--line); }
.bline.warn b { color: var(--warn); }
.bline.crit b { color: var(--crit); }
.bline.ok b { color: var(--ok); }

.bill { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--line);
        border-radius: 6px; padding: 12px; margin-bottom: 10px; cursor: pointer; }
.bill.late { border-left-color: var(--crit); }
.bill.on { background: var(--primary-soft); border-color: var(--primary); }
.btop { display: flex; align-items: flex-start; gap: 10px; }
.box { width: 24px; height: 24px; flex-shrink: 0; border: 2px solid var(--line);
       border-radius: 4px; display: grid; place-items: center; background: var(--surface); }
.box.ticked { background: var(--primary); border-color: var(--primary); color: var(--on-primary); }
.bmain { flex: 1; display: grid; gap: 2px; font-size: 14px; }
.age { font-size: 13px; font-weight: 600; white-space: nowrap; }
.bfoot { display: flex; justify-content: space-between; margin-top: 10px; padding-top: 8px;
         border-top: 1px solid var(--line); }
.bfoot b { font-size: 17px; }

.last .lline { display: flex; align-items: baseline; gap: 10px; margin-top: 3px; }
.last b { font-size: 18px; }
.last .muted { font-size: 13px; }

.bottom { padding-top: 18px; }
.note { text-align: center; margin: 0 0 8px; font-size: 14px; }
.err { display: flex; align-items: center; gap: 8px; background: var(--crit-soft);
       color: var(--crit); border-radius: 6px; padding: 10px 12px; }
.crit { color: var(--crit); }
.ok { color: var(--ok); }
</style>
