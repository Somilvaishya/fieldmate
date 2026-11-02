<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { isSignedOut } from '../lib/session'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

// One rep, from their manager's phone: who they are, their recent orders, and anything their
// phone could not send. The last three things Area and Regional Managers used Desk for.
//
// What the caller may do here arrives with the page and is the same right Desk gave: a Regional
// Manager edits the profile, an Area Manager cancels an order and clears a sync jam. A button the
// server would refuse is not drawn.
const route = useRoute()
const router = useRouter()
const rep = route.params.rep

const page = ref(null)
const loading = ref(true)
const error = ref('')
const notice = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    page.value = await api.teamMember(rep)
  } catch (e) {
    if (isSignedOut(e)) return router.replace('/login')
    error.value = e instanceof ApiError ? e.message : t('Could not load this rep. This needs signal.')
  } finally {
    loading.value = false
  }
}
onMounted(load)

function say(message) {
  notice.value = message
  setTimeout(() => { notice.value = '' }, 2500)
}

function failure(e, fallback) {
  return e instanceof ApiError && e.code === 'OFFLINE'
    ? t('No signal. Nothing was changed - try again when you have one.')
    : (e?.message || fallback)
}

const p = computed(() => page.value?.profile || {})

// ------------------------------------------------------------------ the profile

const editing = ref(false)
const form = ref({})
const saving = ref(false)
const formError = ref('')

function startEdit() {
  form.value = {
    mobile_no: p.value.mobile_no || '',
    designation: p.value.designation || '',
    status: p.value.status || 'Active',
    territory: p.value.territory || '',
    reports_to: p.value.reports_to || '',
    distributor: p.value.distributor || '',
    daily_target_calls: p.value.daily_target_calls || 0,
    can_create_outlet: !!p.value.can_create_outlet,
    can_collect_payment: !!p.value.can_collect_payment,
    notes: p.value.notes || '',
  }
  formError.value = ''
  editing.value = true
}

async function saveProfile() {
  saving.value = true
  formError.value = ''
  try {
    page.value = await api.teamUpdateMember(rep, {
      ...form.value,
      reports_to: form.value.reports_to || null,
      distributor: form.value.distributor || null,
      daily_target_calls: Number(form.value.daily_target_calls) || 0,
      can_create_outlet: form.value.can_create_outlet ? 1 : 0,
      can_collect_payment: form.value.can_collect_payment ? 1 : 0,
    })
    editing.value = false
    say(t('Saved.'))
  } catch (e) {
    formError.value = failure(e, t('That did not go through.'))
  } finally {
    saving.value = false
  }
}

const managerName = computed(() => {
  const m = page.value?.options?.reports_to?.find((r) => r.name === p.value.reports_to)
  return m?.full_name || p.value.reports_to || '—'
})

// ------------------------------------------------------------------ the orders

// Cancelling asks why first: the rep and the depot both read the answer, and the button sits
// under a thumb that is scrolling a list.
const cancelling = ref(null)
const cancelReason = ref('')
const rowError = ref({})
const busy = ref(null)

async function cancelOrder(o) {
  if (!cancelReason.value.trim()) {
    rowError.value = { ...rowError.value, [o.name]: t('Say why. The rep and the depot will both read this.') }
    return
  }
  busy.value = o.name
  try {
    await api.teamCancelOrder(o.name, cancelReason.value.trim())
    o.order_status = 'Cancelled'
    o.can_cancel = false
    cancelling.value = null
    say(t('Order cancelled.'))
  } catch (e) {
    rowError.value = { ...rowError.value, [o.name]: failure(e, t('That did not go through.')) }
  } finally {
    busy.value = null
  }
}

function startCancel(o) {
  cancelling.value = o.name
  cancelReason.value = ''
  rowError.value = { ...rowError.value, [o.name]: '' }
}

// ------------------------------------------------------------------ the sync jams

async function resolve(c, resolution) {
  busy.value = c.name
  try {
    await api.teamResolveConflict(c.name, resolution)
    page.value.conflicts = page.value.conflicts.filter((x) => x.name !== c.name)
    say(resolution === 'Discarded' ? t('Dropped.') : t('Closed.'))
  } catch (e) {
    rowError.value = { ...rowError.value, [c.name]: failure(e, t('That did not go through.')) }
  } finally {
    busy.value = null
  }
}

function day(value) {
  return value ? String(value).slice(0, 10).split('-').reverse().join('/') : ''
}

const STATUS_TONE = { Cancelled: 'crit', Rejected: 'crit', Delivered: 'ok', Invoiced: 'ok',
                      'Pending Approval': 'warn' }
</script>

<template>
  <div class="wrap">
    <header class="head">
      <RouterLink to="/team" class="back" :aria-label="t('Back')"><Icon name="back" size="20" /></RouterLink>
      <div class="who">
        <h1>{{ p.full_name || rep }}</h1>
        <p class="dim">{{ [p.designation, p.territory].filter(Boolean).join(' · ') }}</p>
      </div>
      <a v-if="p.mobile_no" class="call" :href="'tel:' + p.mobile_no" :aria-label="t('Call')">
        <Icon name="phone" size="20" />
      </a>
    </header>

    <p v-if="notice" class="note ok" role="status">{{ notice }}</p>
    <p v-if="loading && !page" class="note">{{ t('Loading…') }}</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else-if="page">
      <!-- The profile -->
      <section class="card">
        <div class="top">
          <h2>{{ t('Profile') }}</h2>
          <button v-if="page.can_edit && !editing" class="link" @click="startEdit">
            <Icon name="edit" size="16" /> {{ t('Edit') }}
          </button>
        </div>

        <dl v-if="!editing" class="facts">
          <dt>{{ t('Reports to') }}</dt><dd>{{ managerName }}</dd>
          <dt>{{ t('Status') }}</dt><dd>{{ p.status }}</dd>
          <dt>{{ t('Distributor') }}</dt><dd>{{ p.distributor || '—' }}</dd>
          <dt>{{ t('Daily calls when there is no route') }}</dt><dd class="tnum">{{ p.daily_target_calls || '—' }}</dd>
          <dt>{{ t('Can add shops') }}</dt><dd>{{ p.can_create_outlet ? t('Yes') : t('No') }}</dd>
          <dt>{{ t('Can collect payment') }}</dt><dd>{{ p.can_collect_payment ? t('Yes') : t('No') }}</dd>
        </dl>

        <div v-else class="form">
          <label class="field"><span>{{ t('Mobile') }}</span>
            <input v-model="form.mobile_no" inputmode="tel" /></label>
          <div class="pair">
            <label class="field"><span>{{ t('Designation') }}</span>
              <select v-model="form.designation">
                <option v-for="d in page.options.designation" :key="d" :value="d">{{ d }}</option>
              </select></label>
            <label class="field"><span>{{ t('Status') }}</span>
              <select v-model="form.status">
                <option v-for="s in page.options.status" :key="s" :value="s">{{ s }}</option>
              </select></label>
          </div>
          <label class="field"><span>{{ t('Territory') }}</span>
            <select v-model="form.territory">
              <option v-for="name in page.options.territory" :key="name" :value="name">{{ name }}</option>
            </select></label>
          <label class="field"><span>{{ t('Reports to') }}</span>
            <select v-model="form.reports_to">
              <option value="">{{ t('Nobody') }}</option>
              <option v-for="m in page.options.reports_to" :key="m.name" :value="m.name">{{ m.full_name }}</option>
            </select></label>
          <label class="field"><span>{{ t('Distributor') }}</span>
            <select v-model="form.distributor">
              <option value="">{{ t('None') }}</option>
              <option v-for="d in page.options.distributor" :key="d" :value="d">{{ d }}</option>
            </select></label>
          <label class="field"><span>{{ t('Daily calls when there is no route') }}</span>
            <input v-model="form.daily_target_calls" type="number" inputmode="numeric" min="0" /></label>
          <label class="toggle"><input type="checkbox" v-model="form.can_create_outlet" />
            <span>{{ t('Can add shops') }}</span></label>
          <label class="toggle"><input type="checkbox" v-model="form.can_collect_payment" />
            <span>{{ t('Can collect payment') }}</span></label>
          <label class="field"><span>{{ t('Notes') }}</span>
            <textarea v-model="form.notes" rows="2"></textarea></label>
          <p v-if="formError" class="note crit">{{ formError }}</p>
          <div class="pair">
            <button class="ghost" :disabled="saving" @click="editing = false">{{ t('Back') }}</button>
            <button class="btn" :disabled="saving" @click="saveProfile">
              {{ saving ? t('Saving…') : t('Save') }}</button>
          </div>
        </div>
      </section>

      <!-- What their phone could not send -->
      <section v-if="page.conflicts.length" class="card warnbox">
        <h2>{{ page.conflicts.length === 1 ? t('1 thing their phone could not send')
                                          : t('{n} things their phone could not send', { n: page.conflicts.length }) }}</h2>
        <div v-for="c in page.conflicts" :key="c.name" class="jam">
          <b>{{ c.reference_doctype?.replace('FieldMate ', '') }} · {{ day(c.creation) }}</b>
          <span class="dim">{{ c.resolution_notes || c.conflict_type }}</span>
          <div class="pair">
            <button class="ghost" :disabled="busy === c.name" @click="resolve(c, 'Discarded')">
              {{ t('Drop what the phone sent') }}</button>
            <button class="ghost" :disabled="busy === c.name" @click="resolve(c, 'Keep Server')">
              {{ t('Leave it as it is') }}</button>
          </div>
          <p v-if="rowError[c.name]" class="note crit">{{ rowError[c.name] }}</p>
        </div>
      </section>

      <!-- Their recent orders -->
      <section class="card">
        <h2>{{ t('Recent orders') }}</h2>
        <p v-if="!page.orders.length" class="dim">{{ t('No orders yet.') }}</p>
        <div v-for="o in page.orders" :key="o.name" class="order">
          <div class="top">
            <div class="who">
              <b>{{ o.outlet_name || o.customer_name || o.outlet || o.customer }}</b>
              <span class="dim mono">{{ o.name }} · {{ day(o.order_date) }}</span>
            </div>
            <div class="right">
              <b class="tnum">{{ formatRupees(o.grand_total || o.net_total) }}</b>
              <span class="pill" :class="STATUS_TONE[o.order_status] || 'flat'">{{ o.order_status }}</span>
            </div>
          </div>
          <template v-if="o.can_cancel">
            <div v-if="cancelling === o.name" class="why">
              <textarea v-model="cancelReason" rows="2" :placeholder="t('Why? The rep and the depot will read this.')"></textarea>
              <div class="pair">
                <button class="ghost" :disabled="busy === o.name" @click="cancelling = null">{{ t('Back') }}</button>
                <button class="no" :disabled="busy === o.name" @click="cancelOrder(o)">
                  {{ busy === o.name ? t('Sending…') : t('Cancel order') }}</button>
              </div>
            </div>
            <button v-else class="link danger" @click="startCancel(o)">{{ t('Cancel this order') }}</button>
          </template>
          <p v-if="rowError[o.name]" class="note crit">{{ rowError[o.name] }}</p>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px 16px 32px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: center; gap: 8px; }
.head .who { flex: 1; min-width: 0; }
.head h1 { font-size: 20px; margin: 0; overflow-wrap: anywhere; }
.back, .call { display: inline-flex; align-items: center; justify-content: center; min-width: 44px;
               min-height: 44px; color: var(--ink); }
.call { color: var(--primary); }
.dim { color: var(--muted); font-size: 13px; margin: 0; }
.mono { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12px; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.card h2 { font-size: 15px; margin: 0; }
.warnbox { border-color: var(--warn); background: var(--warn-soft); }
.top { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.who { display: flex; flex-direction: column; min-width: 0; }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }

.facts { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 12px; margin: 0;
         font-size: 14px; }
.facts dt { color: var(--muted); }
.facts dd { margin: 0; font-weight: 600; text-align: right; overflow-wrap: anywhere; }

.form { display: flex; flex-direction: column; gap: 10px; }
.field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.field > span { font-size: 13px; font-weight: 700; color: var(--muted); }
.field textarea, .why textarea { font: inherit; padding: 10px; border: 1px solid var(--line);
                                 border-radius: 8px; min-height: 60px; resize: vertical; }
.toggle { display: flex; align-items: center; gap: 10px; min-height: 44px; font-weight: 600; }
.toggle input { width: 22px; min-height: 22px; height: 22px; }
.pair { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 8px; }

.jam, .order { display: flex; flex-direction: column; gap: 6px; padding-top: 8px;
               border-top: 1px solid var(--line); }
.why { display: flex; flex-direction: column; gap: 8px; }

.btn, .ghost, .no { min-height: 48px; border-radius: 8px; font-weight: 700; font-size: 14px;
                    padding: 0 10px; }
.btn { border: 0; background: var(--primary); color: var(--on-primary); }
.no { border: 0; background: var(--crit); color: #fff; }
.ghost { border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
.link { align-self: flex-start; display: inline-flex; align-items: center; gap: 4px;
        min-height: 44px; border: 0; background: none; color: var(--primary); font-weight: 700;
        padding: 0; }
.link.danger { color: var(--crit); }

.pill { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; white-space: nowrap; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.crit { background: var(--crit-soft); color: var(--crit); }
.pill.flat { background: var(--primary-soft); color: var(--primary); }

.note { color: var(--muted); font-size: 14px; text-align: center; padding: 12px 0; margin: 0; }
.note.ok { color: var(--ok); background: var(--ok-soft); border-radius: 8px; padding: 10px 12px; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
